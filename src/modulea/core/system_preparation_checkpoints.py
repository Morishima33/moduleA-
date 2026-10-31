"""同批结构准备逐对象不可变检查点；标准库核验，写入仅在公开阶段调用内完成。"""
from copy import deepcopy
from contracts import fingerprint,require
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_execution as execution,system_decisions

VERSION='A06.system_preparation_checkpoints.1'
PREPARATION='A06.system_preparation.2'
SESSIONS='analysis_plan_system_preparation_sessions'
OBJECTS='analysis_plan_system_preparation_objects'
PACKETS='analysis_plan_system_preparation_packets'


def files(value):
    """递归提取真实文件引用；不能用路径字符串或状态标记代替文件。"""
    output={}
    def visit(item):
        if isinstance(item,dict):
            if {'path','bytes','sha256'}<=set(item):output[item['path']]=deepcopy(item)
            else:
                for child in item.values():visit(child)
        elif isinstance(item,list):
            for child in item:visit(child)
    visit(value);return list(output.values())


def read_session(w,m,ref):
    """历史会话只读归属及指纹核验，不要求历史准备仍是当前运行。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(ref in m.get(SESSIONS,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False,'结构准备会话未登记或研究、版本错误')
    batch,_=execution.read_batch(w,m,value['batch_file'])
    require(batch.get('preparation_protocol')==PREPARATION and batch['batch_id']==value['batch_id']
        and value['system_input_ref'] in m.get(system_decisions.INDEX,[]),'准备会话不是明确新版本批次和固定输入')
    fixed=read_json(verified_file(home,value['system_input_ref']))
    require(fixed['stage']=='A06_INPUT' and fixed['binding']['batch_file']==value['batch_file']
        and fixed['schema_version']==system_decisions.VERSION and fixed['study_id']==m['study_id']
        and fixed['human_review_written'] is False and fixed['payload_hash']==fingerprint(fixed['payload'])
        and value['input_hash']==fingerprint(fixed['payload']) and value['input_key']==fixed['payload']['input_key'],
        '准备会话固定名单、方案或输入指纹不同')
    require(value['binding_hash']==fingerprint(value['binding']) and value['binding']['configuration']==value['configuration']
        and value['binding']['input_hash']==value['input_hash'],'准备会话配置或实际绑定不同')
    for item in [value['vina_binary'],*value['implementation_files']]:verified_file(home,item)
    archived={item['path'].split('/code/',1)[1]:item['sha256'] for item in value['implementation_files']}
    require(archived==value['binding']['implementation_sha256'] and value['configuration']['version']==PREPARATION
        and value['configuration']['object_checkpoint_protocol']==VERSION,'准备会话科学实现或恢复协议不同')
    require(value['vina_sha256']==value['vina_binary']['sha256']==value['binding']['vina_sha256'],'准备会话工具摘要不同')
    return value


def active(w,m,value):
    """每次对象开始/发布时再核对原批、当前阶段和真实上游，人工暂停立即否决。"""
    if getattr(w,'_view_cache',None) is None and hasattr(w,'handoff_read_cache'):
        with w.handoff_read_cache():return _active(w,m,value)
    return _active(w,m,value)


def _active(w,m,value):
    """一次操作共用已核验父运行，离开即清空；不跨下载、写入或下一对象缓存。"""
    execution.require_batch(w,m,value['batch_file'])
    fixed=system_decisions.read_record(w,m,value['system_input_ref'])
    require(system_decisions.active(w,m,fixed),'准备对象输入或人工决定已改变')
    ref,current=system_decisions.current(w,m,value['batch_id'],'A06_INPUT')
    require(ref==value['system_input_ref'] and current==fixed,'准备对象的固定范围已替换')
    require(m['current'].get('A06_PREP')==value['initial_preparation_run_id']
        and execution.parent_records(w,m,value['parents'])==value['parent_validation_records'],
        '准备阶段或实际父回执已改变，不继续旧对象')


def find_session(w,m,batch_ref,input_ref,binding):
    """同批同固定输入只接受原配置/工具/实现；不另建会话掩盖不兼容或损坏。"""
    found=[]
    for ref in m.get(SESSIONS,[]):
        value=read_session(w,m,ref)
        if value['batch_file']==batch_ref and value['system_input_ref']==input_ref:found.append((ref,value))
    require(len(found)<=1,'同一准备输入存在竞争会话，不能择优恢复')
    if found:
        ref,value=found[0];require(value['binding']==binding,'准备参数、工具或科学实现已改变，不能沿用旧对象或静默重算')
        active(w,m,value);return ref,value
    return None


def register(w,sid,batch_ref,input_ref,binding,folder,vina_ref,implementations):
    """代码和工具先在锁外归档，短锁只固定实际授权与会话索引。"""
    with write_lock(w.root):
        m=w.load(sid);existing=find_session(w,m,batch_ref,input_ref,binding)
        if existing:return existing
        batch,_=execution.require_batch(w,m,batch_ref)
        parents={key:m['current'][key] for key in execution.DEPENDENCIES['A06_PREP']}
        fixed=system_decisions.read_record(w,m,input_ref)
        value={'schema_version':VERSION,'study_id':sid,'session_id':folder.name,'batch_id':batch['batch_id'],
            'batch_file':deepcopy(batch_ref),'system_input_ref':deepcopy(input_ref),'input_key':fixed['payload']['input_key'],
            'input_hash':fingerprint(fixed['payload']),'configuration':deepcopy(binding['configuration']),
            'binding':deepcopy(binding),'binding_hash':fingerprint(binding),'initial_preparation_run_id':m['current'].get('A06_PREP'),
            'parents':parents,'parent_validation_records':execution.parent_records(w,m,parents),
            'vina_binary':deepcopy(vina_ref),'vina_sha256':vina_ref['sha256'],'implementation_files':deepcopy(implementations),
            'folder':folder.relative_to(w.location(sid)).as_posix(),'human_review_written':False,'created_at':now()}
        active(w,m,value);path=folder/'session.json';write_json(path,value);ref=file_record(w.location(sid),path,'system_preparation_session')
        m.setdefault(SESSIONS,[]).append(ref);w.save(m);return ref,value


def read_object(w,m,ref):
    """逐件核验对象、前置检查点与全部原件，损坏拒绝而不重新获取掩盖。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(ref in m.get(OBJECTS,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False,'准备对象检查点未登记或归属错误')
    session=read_session(w,m,value['session_ref']);fixed=read_json(verified_file(home,session['system_input_ref']))['payload']
    require(value['object_type'] in ('compound','receptor') and value['stage'] in ('source','preparation','attempt'),
        '准备对象或阶段类型错误')
    rows=fixed['compounds' if value['object_type']=='compound' else 'receptors'];i=value['object_index']
    require(type(i) is int and 0<=i<len(rows) and value['object_input_hash']==fingerprint(rows[i]),'准备对象不属于原固定名单')
    require(value['payload_hash']==fingerprint(value['payload']),'准备对象内容指纹不同')
    for dependency in value['dependencies']:
        parent=read_object(w,m,dependency)
        require(parent['session_ref']==value['session_ref'] and parent['object_type']==value['object_type']
            and parent['object_index']==i,'准备对象引用了其他对象或批次')
    for item in value['files']:verified_file(home,item)
    return value


def latest(w,m,session_ref,stage,object_type,index,candidate_index=None):
    """只取本对象最近检查点；不从历史挑选较早成功覆盖较新失败。"""
    for ref in reversed(m.get(OBJECTS,[])):
        value=read_json(verified_file(w.location(m['study_id']),ref))
        if (value['session_ref'],value['stage'],value['object_type'],value['object_index'],value['candidate_index'])==(
                session_ref,stage,object_type,index,candidate_index):return ref,read_object(w,m,ref)
    return None


def append(w,sid,session_ref,stage,object_type,index,payload,evidence,dependencies=(),candidate_index=None):
    """对象或候选尝试完成即追加，不等整个准备包写成；中断前的原件留存。"""
    with write_lock(w.root):
        m=w.load(sid);session=read_session(w,m,session_ref);active(w,m,session)
        fixed=read_json(verified_file(w.location(sid),session['system_input_ref']))['payload']
        row=fixed['compounds' if object_type=='compound' else 'receptors'][index]
        value={'schema_version':VERSION,'study_id':sid,'session_ref':deepcopy(session_ref),'stage':stage,
            'object_type':object_type,'object_index':index,'candidate_index':candidate_index,'object_input_hash':fingerprint(row),
            'payload':deepcopy(payload),'payload_hash':fingerprint(payload),'dependencies':deepcopy(list(dependencies)),
            'files':files([evidence,payload,list(dependencies)]),'human_review_written':False,'created_at':now()}
        for item in value['files']:verified_file(w.location(sid),item)
        path=w.location(sid)/session['folder']/'checkpoints'/(new_id('object')+'.json');write_json(path,value)
        ref=file_record(w.location(sid),path,'system_preparation_object');m.setdefault(OBJECTS,[]).append(ref);w.save(m)
        read_object(w,m,ref);return ref,value


def read_packet(w,m,ref):
    """完整准备包仅采用已登记事实及所用对象检查点，不扫描未提交目录择优。"""
    home=w.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(ref in m.get(PACKETS,[]) and value['schema_version']==VERSION and value['study_id']==m['study_id']
        and value['human_review_written'] is False,'准备完整包未登记或归属错误')
    read_session(w,m,value['session_ref']);verified_file(home,value['fact'])
    for item in value['object_records']:
        require(read_object(w,m,item)['session_ref']==value['session_ref'],'准备完整包混用了其他会话对象')
    return value


def complete(w,sid,session_ref,fact_ref,object_records):
    """全部对象实际归档后固定一次完整包，发布失败续做仅复验该包。"""
    with write_lock(w.root):
        m=w.load(sid);session=read_session(w,m,session_ref);active(w,m,session)
        for ref in m.get(PACKETS,[]):
            value=read_packet(w,m,ref)
            if value['session_ref']==session_ref:return ref,value
        for ref in object_records:read_object(w,m,ref)
        verified_file(w.location(sid),fact_ref)
        value={'schema_version':VERSION,'study_id':sid,'session_ref':deepcopy(session_ref),'fact':deepcopy(fact_ref),
            'object_records':deepcopy(object_records),'human_review_written':False,'created_at':now()}
        path=w.location(sid)/session['folder']/'completed'/(new_id('packet')+'.json');write_json(path,value)
        ref=file_record(w.location(sid),path,'system_preparation_completed_packet');m.setdefault(PACKETS,[]).append(ref);w.save(m)
        return ref,value
