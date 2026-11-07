"""隔离验证轻量状态、实例安全停止、原子标识及CLI退出；不启动常驻服务。"""
from contextlib import redirect_stdout
from copy import deepcopy
import builtins
import errno
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulea import __main__ as cli
from modulea import config
from modulea import service_control as control
from modulea.service_identity import ServiceIdentity, expected_identity


class ServiceControlTests(unittest.TestCase):
    """只在临时最小工程内读写服务标识，不创建或修改studies。"""

    # 最小源码和前端满足身份签名，配置根不引用真实项目资料。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.static = self.root/'static'
        for name, content in {'src/modulea/entry.py':'# shell', 'src/science_modules/model.py':'# model',
                              'src/legacy.py':'# legacy', 'static/index.html':'<script src="app.js"></script><link rel="stylesheet" href="app.css">',
                              'static/app.js':'// bundle', 'static/app.css':'body{}'}.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.settings = config.Settings(project_root=self.root, data_root=self.root/'data', runtime_dir=self.root/'runtime', static_dir=self.static)
        self.settings.data_root.mkdir()
        self.health = ServiceIdentity(self.settings).describe(8780)
        self.expected = expected_identity(self.settings)

    # 清理时验证所有测试均未触碰任何科学研究包。
    def tearDown(self):
        self.assertFalse((self.settings.data_root/'studies').exists())

    # 本地配置、环境和CLI按原优先级覆盖；既有科学参数不随runtime扩展改变。
    def test_runtime_config_priority_preserves_existing_settings(self):
        local = self.root/'config/local.toml'
        local.parent.mkdir()
        local.write_text('[paths]\nruntime_dir='+json.dumps(str(self.root/'local_runtime'))+'\ndata_root='+json.dumps(str(self.root/'local_data'))+'\nscience_python="local_python"\n[server]\nallowed_origins=["http://local"]\n[resources]\ncompute_slots=2\n', encoding='utf-8')
        original = config.Settings
        def settings():
            return original(project_root=self.root, data_root=self.root, runtime_dir=self.root/'default_runtime')
        with patch.object(config, 'Settings', side_effect=settings), patch.dict(os.environ, {}, clear=True):
            first = config.load_settings()
            self.assertEqual(first.runtime_dir, (self.root/'local_runtime').resolve())
            self.assertEqual(first.data_root, (self.root/'local_data').resolve())
            self.assertEqual(first.science_python, 'local_python')
            self.assertEqual(first.allowed_origins, ['http://local'])
            self.assertEqual(first.compute_slots, 2)
            with patch.dict(os.environ, {'MODULEA_RUNTIME_DIR':str(self.root/'env_runtime'), 'MODULEA_DATA_ROOT':str(self.root/'env_data'), 'MODULEA_SCIENCE_PYTHON':'env_python'}):
                second = config.load_settings()
                self.assertEqual(second.runtime_dir, (self.root/'env_runtime').resolve())
                third = config.load_settings(runtime_dir=self.root/'cli_runtime', data_root=self.root/'cli_data', allowed_origins='http://cli,http://other')
                self.assertEqual(third.runtime_dir, (self.root/'cli_runtime').resolve())
                self.assertEqual(third.data_root, (self.root/'cli_data').resolve())
                self.assertEqual(third.science_python, 'env_python')
                self.assertEqual(third.allowed_origins, ['http://cli', 'http://other'])
                self.assertEqual(third.compute_slots, 2)

    # ConnectionRefused才表示没有监听；超时和权限拒绝均不能当作安全空端口。
    def test_probe_distinguishes_refused_timeout_and_access_denied(self):
        denied, refused = OSError('Windows denied'), OSError('Windows refused')
        denied.winerror, refused.winerror = 10013,10061
        for error, state in ((ConnectionRefusedError(errno.ECONNREFUSED, 'refused'), 'not_running'),
                             (TimeoutError('timeout'), 'unreachable'), (PermissionError(errno.EACCES, 'denied'), 'access_denied'),
                             (OSError(errno.EIO, 'io'), 'unreachable'), (denied,'access_denied'),(refused,'not_running')):
            with self.subTest(state=state), patch.object(control, '_request', side_effect=error):
                value = control.probe_service(self.settings)
                self.assertEqual(value['state'], state)
                self.assertFalse(value['ready'])

    # 只读探测既不加载Workflow，也不创建任务目录或试图结束任何PID。
    def test_probe_does_not_import_workflow_or_manage_processes(self):
        original = builtins.__import__
        def guard(name,*args,**kwargs):
            if name in ('workflow','modulea.core.kernel') or name.startswith('science_modules'):
                raise AssertionError('probe must not load Workflow or science')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=guard),patch.object(control,'_request',return_value=(200,self.health)),patch.object(os,'kill',side_effect=AssertionError('no PID termination')):
            self.assertTrue(control.probe_service(self.settings)['ready'])
        self.assertFalse(self.settings.runtime_dir.exists())

    # 当前身份才就绪，不匹配、关闭中、非200及前端缺失都有明确不同状态。
    def test_probe_requires_matching_identity_status_and_frontend(self):
        for code, change, state in ((200, {}, 'running'), (200, {'schema_version':'foreign'}, 'mismatch'),
                                    (200, {'data_root':'foreign'}, 'mismatch'), (200, {'stopping':True}, 'stopping'),
                                    (503, {}, 'degraded')):
            health = dict(self.health, **change)
            with self.subTest(state=state), patch.object(control, '_request', return_value=(code,health)) as request:
                value = control.probe_service(self.settings,8780,timeout=1.5)
                self.assertEqual(value['state'], state)
                self.assertEqual(value['ready'], state=='running')
                request.assert_called_once_with(8780,'GET','/api/v1/health',timeout=1.5)
        (self.static/'app.js').unlink()
        with patch.object(control, '_request', return_value=(200,self.health)):
            value = control.probe_service(self.settings)
            self.assertFalse(value['ready'])
            self.assertFalse(value['preflight_ready'])

    # HTTP客户固定127.0.0.1、设置超时、限制读取且不追随302。
    def test_request_is_loopback_bounded_and_never_redirects(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'application/json; charset=utf-8'
        response.read.return_value = b'{"redirect":"https://foreign/"}'
        with patch.object(control.http.client, 'HTTPConnection', return_value=connection) as factory:
            code, value = control._request(8780,'GET','/api/v1/health',timeout=1.25)
            factory.assert_called_once_with('127.0.0.1',8780,timeout=1.25)
            self.assertEqual(code,302)
            self.assertIn('redirect',value)
            self.assertEqual(connection.request.call_count,1)
            response.read.assert_called_once_with(control.MAX_RESPONSE+1)
            connection.close.assert_called_once()

    # 超大、非JSON或非对象响应严格失败并关闭连接。
    def test_request_rejects_oversize_non_json_and_non_object(self):
        for raw, mime in ((b'x'*(control.MAX_RESPONSE+1),'application/json'), (b'{}','text/html'),
                          (b'[]','application/json'), (b'bad','application/json')):
            connection = Mock()
            response = connection.getresponse.return_value
            response.read.return_value, response.getheader.return_value = raw,mime
            with self.subTest(mime=mime,size=len(raw)), patch.object(control.http.client,'HTTPConnection',return_value=connection):
                with self.assertRaises(ValueError):
                    control._request(8780,'GET','/api/v1/health')
                connection.close.assert_called_once()
        with patch.object(control.http.client,'HTTPConnection') as factory:
            with self.assertRaises(ValueError):
                control._request(True,'GET','/api/v1/health')
            factory.assert_not_called()

    # 未确认、非同目录或无效实例标识均不取得session或发送停止。
    def test_stop_requires_confirmation_full_identity_and_valid_nonce(self):
        cases = [(False,self.health,'confirmation_required'), (True,dict(self.health,instance_id='service_bad'),'mismatch')]
        cases.extend((True,dict(self.health,**{key:'foreign'}),'mismatch')
                     for key in ('project_root','data_root','runtime_dir','static_dir','schema_version'))
        cases.extend((True,dict(self.health,port=port),'mismatch') for port in (True,8781))
        for confirmed, actual, state in cases:
            before = {'state':'running','ready':True,'actual':actual,'expected':self.expected}
            with self.subTest(state=state,actual=actual['instance_id']), patch.object(control,'probe_service',return_value=before), patch.object(control,'_request') as request:
                self.assertEqual(control.stop_service(self.settings,confirmed=confirmed)['state'],state)
                request.assert_not_called()

    # 允许明确关闭同目录旧实现，但POST必须携带首次确认实例的原nonce。
    def test_explicit_stop_of_own_old_code_keeps_original_nonce(self):
        old = dict(self.health,code_signature='0'*64)
        before = {'state':'mismatch','ready':False,'actual':old,'expected':self.expected}
        after = {'state':'not_running','ready':False,'actual':None,'expected':self.expected}
        with patch.object(control,'probe_service',side_effect=[before,after]), patch.object(control,'_request',side_effect=[(200,{'token':'isolated_token'}),(202,{'stopping':True})]) as request, patch.object(control.time,'sleep'):
            result = control.stop_service(self.settings,confirmed=True)
        self.assertEqual(result['state'],'stopped')
        self.assertEqual(request.call_args_list[1].args,(8780,'POST','/api/v1/service/stop',{'instance_id':old['instance_id'],'confirmed':True},'isolated_token'))

    # nonce在会话取得期间已变化，服务端409后不得重复停止新实例。
    def test_nonce_changed_before_post_is_rejected_without_retry(self):
        before = {'state':'running','ready':True,'actual':self.health,'expected':self.expected}
        with patch.object(control,'probe_service',return_value=before) as probe, patch.object(control,'_request',side_effect=[(200,{'token':'new_instance_token'}),(409,{'error':{'message_zh':'实例已变化'}})]) as request:
            result = control.stop_service(self.settings,confirmed=True)
        self.assertEqual(result['state'],'stop_rejected')
        self.assertEqual(result['http_status'],409)
        self.assertEqual(request.call_count,2)
        self.assertEqual(probe.call_count,1)
        self.assertEqual(request.call_args.args[3]['instance_id'],self.health['instance_id'])

    # 停止后看到新nonce，只报告实例变化，不再获取session或发送停止。
    def test_new_instance_after_stop_is_never_stopped(self):
        before = {'state':'running','ready':True,'actual':self.health,'expected':self.expected}
        newer = dict(before,actual=dict(self.health,instance_id='service_'+'b'*32))
        with patch.object(control,'probe_service',side_effect=[before,newer]), patch.object(control,'_request',side_effect=[(200,{'token':'token'}),(202,{})]) as request, patch.object(control.time,'sleep'):
            result = control.stop_service(self.settings,confirmed=True)
        self.assertEqual(result['state'],'instance_changed')
        self.assertEqual(request.call_count,2)

    # 原子替换前完整临时JSON已写好，旧标识在replace之前仍完整存在。
    def test_marker_is_atomic_and_old_nonce_cannot_clear_new_marker(self):
        marker = control.register_service(self.settings,self.health)
        self.assertEqual(marker,self.settings.runtime_dir/f"service/service_8780_{self.health['instance_id']}.json")
        old_bytes = marker.read_bytes()
        updated = dict(self.health,pid=self.health['pid']+1)
        replace = os.replace
        def inspect(source,destination):
            self.assertEqual(Path(destination),marker)
            self.assertEqual(marker.read_bytes(),old_bytes)
            self.assertEqual(json.loads(Path(source).read_bytes()),updated)
            self.assertEqual(Path(source).parent,marker.parent)
            return replace(source,destination)
        with patch.object(control.os,'replace',side_effect=inspect):
            control.register_service(self.settings,updated)
        newer = dict(self.health,instance_id='service_'+'c'*32)
        new_marker = control.register_service(self.settings,newer)
        control.clear_service(self.settings,8780,self.health['instance_id'])
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(new_marker.read_bytes())['instance_id'],newer['instance_id'])
        control.clear_service(self.settings,8780,newer['instance_id'])
        self.assertFalse(new_marker.exists())
        self.assertEqual(list(marker.parent.glob('*.tmp')),[])

    # 原子提交失败保留原标识，同时清理临时文件。
    def test_failed_atomic_replace_keeps_previous_marker_and_cleans_temp(self):
        marker = control.register_service(self.settings,self.health)
        old = marker.read_bytes()
        with patch.object(control.os,'replace',side_effect=OSError('replace denied')):
            with self.assertRaises(OSError):
                control.register_service(self.settings,dict(self.health,pid=self.health['pid']+1))
        self.assertEqual(marker.read_bytes(),old)
        self.assertEqual(list(marker.parent.glob('*.tmp')),[])

    # 研究包、目录链接越界及标识文件链接均不能被写入。
    def test_studies_runtime_and_directory_or_file_link_are_rejected(self):
        forbidden = deepcopy(self.settings)
        forbidden.runtime_dir = forbidden.data_root/'studies/hidden_runtime'
        with self.assertRaises(ValueError):
            control.register_service(forbidden,self.health)
        folder = self.settings.runtime_dir/'service'
        original = Path.resolve
        def resolve(path,*args,**kwargs):
            return self.root/'outside' if path==folder else original(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):
            with self.assertRaises(ValueError):
                control.register_service(self.settings,self.health)
        self.assertFalse((self.root/'outside').exists())
        marker = folder/f"service_8780_{self.health['instance_id']}.json"
        is_link = Path.is_symlink
        with patch.object(Path,'is_symlink',lambda path:True if path==marker else is_link(path)):
            with self.assertRaises(ValueError):
                control.register_service(self.settings,self.health)
        self.assertFalse(marker.exists())

    # runtime允许是数据根或其祖先，但service目录链接仍不得落进任何研究包。
    def test_service_folder_resolving_inside_studies_is_rejected(self):
        for runtime in (self.settings.data_root,self.settings.data_root.parent):
            settings = deepcopy(self.settings)
            settings.runtime_dir = runtime
            folder = runtime/'service'
            forbidden = self.settings.data_root/'studies/study_virtual'
            original = Path.resolve
            def resolve(path,*args,**kwargs):
                return forbidden if path==folder else original(path,*args,**kwargs)
            with self.subTest(runtime=runtime),patch.object(Path,'resolve',resolve):
                with self.assertRaises(ValueError):
                    control.runtime_location(settings)

    # 合法JSON中的error字段可能为空或错误类型；停止失败必须可说明且不重试。
    def test_stop_non_object_error_payload_does_not_raise_attribute_error(self):
        before = {'state':'running','ready':True,'actual':self.health,'expected':self.expected}
        for error in (None,'bad response',[],42):
            with self.subTest(error=error),patch.object(control,'probe_service',return_value=before),patch.object(control,'_request',side_effect=[(200,{'token':'isolated'}),(409,{'error':error})]) as request:
                result = control.stop_service(self.settings,confirmed=True)
                self.assertEqual(result['state'],'stop_rejected')
                self.assertEqual(result['http_status'],409)
                self.assertIsInstance(result['reasons_zh'][0],str)
                self.assertEqual(request.call_count,2)

    # 用受控listener替身测试serve生命周期，不绑定端口或创建后台进程。
    def _listener(self,side_effect=None):
        server = SimpleNamespace(server_port=8780,server_close=Mock(),serve_forever=Mock(side_effect=side_effect))
        app = SimpleNamespace(get_health=Mock(return_value=self.health),service_identity=SimpleNamespace(instance_id=self.health['instance_id']))
        module = ModuleType('modulea.api.server')
        module.create_server = Mock(return_value=(server,app))
        return server,app,module

    # --check只短暂创建并关闭受控listener，不登记、不常驻、不开浏览器。
    def test_serve_check_never_registers_or_serves_forever(self):
        server,app,module = self._listener()
        with patch.dict('sys.modules',{'modulea.api.server':module}), patch.object(cli,'load_settings',return_value=self.settings), patch.object(control,'register_service') as register, patch.object(cli.webbrowser,'open') as browser, redirect_stdout(StringIO()):
            self.assertEqual(cli.main(['serve','--port','8780','--check']),0)
        register.assert_not_called()
        browser.assert_not_called()
        server.serve_forever.assert_not_called()
        server.server_close.assert_called_once()

    # 正常结束或KeyboardInterrupt都只清自己的marker，保留后来实例标识。
    def test_serve_exit_cleans_own_marker_but_keeps_replacement(self):
        for interrupt,replace_nonce in ((False,False),(True,False),(False,True)):
            server,app,module = self._listener()
            def run():
                marker = self.settings.runtime_dir/f"service/service_8780_{self.health['instance_id']}.json"
                self.assertEqual(json.loads(marker.read_bytes())['instance_id'],self.health['instance_id'])
                if replace_nonce:
                    control.register_service(self.settings,dict(self.health,instance_id='service_'+'e'*32))
                if interrupt:
                    raise KeyboardInterrupt()
            server.serve_forever.side_effect = run
            with self.subTest(interrupt=interrupt,replacement=replace_nonce), patch.dict('sys.modules',{'modulea.api.server':module}), patch.object(cli,'load_settings',return_value=self.settings), patch.object(cli.webbrowser,'open') as browser, redirect_stdout(StringIO()):
                self.assertEqual(cli.main(['serve','--port','8780','--no-browser']),0)
            browser.assert_not_called()
            server.server_close.assert_called_once()
            marker = self.settings.runtime_dir/f"service/service_8780_{self.health['instance_id']}.json"
            self.assertFalse(marker.exists())
            if replace_nonce:
                newer = self.settings.runtime_dir/f"service/service_8780_service_{'e'*32}.json"
                self.assertEqual(json.loads(newer.read_bytes())['instance_id'],'service_'+'e'*32)
                newer.unlink()

    # 标识登记失败必须关闭listener并传播明确错误，不继续serve。
    def test_serve_registration_error_closes_listener(self):
        server,app,module = self._listener()
        with patch.dict('sys.modules',{'modulea.api.server':module}), patch.object(cli,'load_settings',return_value=self.settings), patch.object(control,'register_service',side_effect=ValueError('运行目录错误')), redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError,'运行目录错误'):
                cli.main(['serve','--no-browser'])
        server.server_close.assert_called_once()
        server.serve_forever.assert_not_called()

    # CLI保留状态退出码及显式confirmed，源码损坏返回configuration_error。
    def test_service_cli_flags_and_configuration_failure_are_explicit(self):
        for action,args,state,ready,code in (('status',[],'not_running',False,3),('status',[],'running',True,0),
                                            ('stop',[],'confirmation_required',False,4),('stop',['--confirmed'],'stopped',False,0)):
            result={'state':state,'ready':ready,'reasons_zh':[]}
            target='probe_service' if action=='status' else 'stop_service'
            output=StringIO()
            with patch.object(cli,'load_settings',return_value=self.settings) as load,patch.object(control,target,return_value=result) as call,redirect_stdout(output):
                self.assertEqual(cli.main(['--runtime-dir',str(self.root/'from_cli'),'service',action,'--port','8780','--json']+args),code)
            self.assertEqual(json.loads(output.getvalue())['state'],state)
            self.assertEqual(load.call_args.kwargs['runtime_dir'],str(self.root/'from_cli'))
            if action=='stop':self.assertIs(call.call_args.kwargs['confirmed'],'--confirmed' in args)
        broken=deepcopy(self.settings)
        broken.project_root=self.root/'missing_source'
        output=StringIO()
        with patch.object(cli,'load_settings',return_value=broken),redirect_stdout(output):
            self.assertEqual(cli.main(['service','status','--json']),4)
        self.assertEqual(json.loads(output.getvalue())['state'],'configuration_error')

    # 配置加载阶段的错误同样要以非零JSON说明，不应绕过service错误处理。
    def test_service_cli_invalid_configuration_returns_json_error(self):
        output = StringIO()
        with patch.object(cli,'load_settings',side_effect=ValueError('runtime配置无效')),redirect_stdout(output):
            self.assertEqual(cli.main(['service','status','--json']),4)
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'],'configuration_error')
        self.assertIn('runtime配置无效',result['reasons_zh'])


if __name__ == '__main__':
    unittest.main()
