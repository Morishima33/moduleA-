"""本机工作台的轻量状态、安全停止和实例登记；不启动进程、不改研究或科学任务。"""
from __future__ import annotations

from pathlib import Path
import errno
import http.client
import json
import os
import re
import tempfile
import time

from .service_identity import PROTOCOL, compare_identity, expected_identity, frontend_status

PROBE_VERSION='ModuleA.service_probe.1'
MAX_RESPONSE=64*1024


def _port(value):
    """只使用明确本机端口，拒绝布尔值、外部地址或隐式换端口。"""
    if type(value) is not int or not 1<=value<=65535:raise ValueError('端口须为1—65535的整数')
    return value


def _request(port,method,path,body=None,token=None,timeout=3):
    """固定127.0.0.1，无重定向或代理；只读取有界JSON，不记录令牌。"""
    connection=http.client.HTTPConnection('127.0.0.1',_port(port),timeout=timeout)
    headers={'Accept':'application/json'};raw=None
    if body is not None:
        raw=json.dumps(body,ensure_ascii=False).encode('utf-8');headers['Content-Type']='application/json'
    if token is not None:headers.update({'X-ModuleA-Token':token,'Origin':f'http://127.0.0.1:{port}'})
    try:
        connection.request(method,path,body=raw,headers=headers);response=connection.getresponse()
        content=response.read(MAX_RESPONSE+1)
        if len(content)>MAX_RESPONSE:raise ValueError('本机服务返回超出允许的状态内容')
        if response.getheader('Content-Type','').split(';')[0].strip()!='application/json':raise ValueError('该端口没有返回工作台JSON状态')
        value=json.loads(content)
        if not isinstance(value,dict):raise ValueError('本机服务状态不是JSON对象')
        return response.status,value
    finally:connection.close()


def runtime_location(settings):
    """运行记录必须在本次配置的runtime内，并禁止写入任何研究包。"""
    root=Path(settings.runtime_dir).resolve();studies=(Path(settings.data_root).resolve()/'studies').resolve()
    if root==studies or root.is_relative_to(studies):raise ValueError('运行目录不得放进studies研究目录')
    folder=root/'service'
    resolved=folder.resolve()
    if not resolved.is_relative_to(root):raise ValueError('服务运行目录链接超出配置范围')
    if resolved==studies or resolved.is_relative_to(studies):
        raise ValueError('服务运行目录链接不得指向studies研究目录')
    return folder


def probe_service(settings,port=8780,*,timeout=3):
    """只检查端口身份、代码与前端；不展开研究、不联网取科学原件或恢复任务。"""
    _port(port);expected=expected_identity(settings);preflight=[]
    front=frontend_status(settings.static_dir)
    if not front['ready']:preflight.extend(front['errors_zh'])
    if not Path(settings.data_root).is_dir():preflight.append('配置的数据目录不存在')
    try:runtime_location(settings)
    except ValueError as error:preflight.append(str(error))
    value={'schema_version':PROBE_VERSION,'state':'not_running','ready':False,'expected':expected,'actual':None,
           'url':f'http://127.0.0.1:{port}','reasons_zh':[],'preflight_ready':not preflight,'preflight_errors_zh':preflight}
    try:
        status,actual=_request(port,'GET','/api/v1/health',timeout=timeout);value['actual']=actual
        differences=compare_identity(actual,expected,port)
        if actual.get('schema_version')!=PROTOCOL:
            value.update(state='mismatch',reasons_zh=['该端口不是本版Module A工作台，不会停止或替换它'])
        elif differences:
            value.update(state='mismatch',reasons_zh=differences)
        elif actual.get('stopping'):
            value.update(state='stopping',reasons_zh=['工作台正在停止，请稍后核对'])
        elif status!=200 or not front['ready']:
            value.update(state='degraded',reasons_zh=['工作台或当前前端未准备齐备']+preflight)
        else:value.update(state='running',ready=True)
    except ConnectionRefusedError:
        value['reasons_zh']=['此端口尚无运行中的工作台']
    except (TimeoutError,http.client.HTTPException) as error:
        value.update(state='unreachable',reasons_zh=['端口未能完成状态响应：'+type(error).__name__])
    except OSError as error:
        code=getattr(error,'winerror',None) or error.errno
        if code in (10061,errno.ECONNREFUSED):value['reasons_zh']=['此端口尚无运行中的工作台']
        elif code in (10013,errno.EACCES,errno.EPERM):value.update(state='access_denied',reasons_zh=['系统拒绝本机连接，未尝试更改权限或换端口'])
        else:value.update(state='unreachable',reasons_zh=['本机状态连接失败：'+type(error).__name__])
    except (ValueError,UnicodeError) as error:
        value.update(state='mismatch',reasons_zh=[str(error)])
    if preflight:
        value['ready']=False
        if value['state']=='running':value.update(state='degraded',reasons_zh=preflight)
    return value


def stop_service(settings,port=8780,*,confirmed=False,timeout=10):
    """明确停止本目录实例；只调用其认证接口，不杀PID，不自动取消后台任务。"""
    value=probe_service(settings,port)
    if confirmed is not True:
        return dict(value,state='confirmation_required',ready=False,reasons_zh=['请明确确认停止当前工作台'])
    if value['state']=='not_running':return dict(value,state='stopped',reasons_zh=['工作台已经停止，未执行进程操作'])
    actual=value.get('actual');expected=value['expected']
    # 允许显式关闭本目录的旧代码实例以便更新；数据/运行/静态目录不同则拒绝。
    owns=bool(isinstance(actual,dict) and actual.get('schema_version')==PROTOCOL and type(actual.get('port')) is int
              and actual['port']==port and all(actual.get(k)==expected.get(k) for k in ('project_root','data_root','runtime_dir','static_dir')))
    if not owns:return dict(value,state='mismatch',ready=False,reasons_zh=['当前端口不属于本次配置的工作台，未发停止请求'])
    instance=actual.get('instance_id')
    if not isinstance(instance,str) or not re.fullmatch(r'service_[0-9a-f]{32}',instance):
        return dict(value,state='mismatch',ready=False,reasons_zh=['工作台实例标识无效，未发停止请求'])
    try:
        status,session=_request(port,'GET','/api/v1/session');token=session.get('token')
        if status!=200 or not isinstance(token,str) or not token:raise ValueError('未取得本实例的有效操作令牌')
        status,result=_request(port,'POST','/api/v1/service/stop',{'instance_id':instance,'confirmed':True},token)
        if status!=202:
            error=result.get('error')
            reason=error.get('message_zh') if isinstance(error,dict) else None
            if not isinstance(reason,str) or not reason.strip():reason='工作台未接受停止请求'
            return dict(value,state='stop_rejected',ready=False,reasons_zh=[reason],http_status=status)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            time.sleep(.15)
            # Windows本机拒连可能约2秒后才明确返回，1秒会把正常释放误报超时。
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            after=probe_service(settings,port,timeout=min(3,remaining))
            if after['state']=='not_running':return dict(after,state='stopped',reasons_zh=['工作台已安全停止，研究和任务记录保留'])
            other=after.get('actual')
            if isinstance(other,dict) and other.get('instance_id')!=instance:
                return dict(after,state='instance_changed',ready=False,reasons_zh=['停止期间端口实例已变化，未操作新的实例'])
        return dict(value,state='stop_pending',ready=False,reasons_zh=['已提交停止，但尚未确认端口释放；未强制结束任何进程'])
    except (OSError,ValueError,http.client.HTTPException) as error:
        return dict(value,state='stop_failed',ready=False,reasons_zh=['未能确认停止：'+type(error).__name__])


def _marker(settings,port,instance_id):
    """每实例独立文件名，旧服务退出绝不会删除后来实例的运行标识。"""
    if not isinstance(instance_id,str) or not re.fullmatch(r'service_[0-9a-f]{32}',instance_id):
        raise ValueError('服务实例标识格式无效')
    return runtime_location(settings)/('service_'+str(_port(port))+'_'+instance_id+'.json')


def register_service(settings,health):
    """仅绑定成功的CLI服务登记运行标识，不保存令牌或修改研究包。"""
    folder=runtime_location(settings);folder.mkdir(parents=True,exist_ok=True)
    # 创建后重新核对完整范围，目录链接变化也不能把运行记录写入研究包。
    if runtime_location(settings)!=folder:raise ValueError('服务运行目录已变化')
    marker=_marker(settings,health['port'],health['instance_id'])
    if marker.is_symlink():raise ValueError('服务标识文件不能是链接')
    raw=(json.dumps(health,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    descriptor,temp=tempfile.mkstemp(prefix='service_',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(descriptor,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,marker)
    finally:
        if Path(temp).exists():Path(temp).unlink()
    return marker


def clear_service(settings,port,instance_id):
    """只删除仍指向自己nonce的精确标识；不按PID清理其他实例或历史日志。"""
    marker=_marker(settings,port,instance_id)
    if not marker.exists() or marker.is_symlink():return
    try:value=json.loads(marker.read_text('utf-8'))
    except (OSError,ValueError):return
    if isinstance(value,dict) and value.get('instance_id')==instance_id:marker.unlink()
