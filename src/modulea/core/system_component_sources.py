"""系统获取原件的显式科学输入绑定；独立于旧人工上传清单和科研运行。"""
from copy import deepcopy
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from . import system_acquisition as acquisition

VERSION='A01.system_source_binding.1'
INDEX='analysis_plan_system_component_source_records'
CURRENT='current_system_component_sources'
FIELDS={'request_id','expected_acquisition_request_id','expected_record_sha256','expected_input_hash','author','note','confirmed'}


def read_record(workflow,m,ref):
    """标准库核验绑定来源与真实完整采集记录；不解包或改变归档。"""
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,ref))
    require(ref in m.get(INDEX,[]) and value['schema_version']==VERSION and value['version']==VERSION
        and value['study_id']==m['study_id'] and value['human_review_written'] is False and value['a01_published'] is False,
        '系统三库来源绑定归属或协议错误')
    require(value['request_hash']==fingerprint(value['request']) and value['request']['confirmed'] is True,'三库来源绑定确认不同')
    original=acquisition.read_record(workflow,m,value['acquisition_record'],kind='record')
    request=acquisition.read_record(workflow,m,original['request_file'],kind='request')
    require(original['state']=='complete' and value['plan_file']==original['plan_file'] and value['a00_run_id']==request['binding']['a00']
        and value['herbs']==original['herbs'] and value['request']['expected_record_sha256']==value['acquisition_record']['sha256']
        and value['request']['expected_acquisition_request_id']==request['request']['request_id'],'系统三库绑定不是原完整获取')
    require(value['request']['expected_input_hash']==fingerprint(request['binding']),
        '三库来源绑定并非原获取确认的实际输入')
    require([r['database'] for r in value['datasets']]==['TCMSP','HERB','BATMAN'],'系统三库绑定不能缺库或重复')
    for slot,row in zip(value['datasets'],original['sources']):
        require(slot['source_record']==row['archive'],'系统三库原ZIP被替换')
        for item in [slot['source_record'],*slot['files']]:verified_file(home,item)
    for item in value['implementation_files']:verified_file(home,item)
    return value


def current(workflow,m,*,plan_id=None):
    """只读取单独系统来源指针，不回写旧上传；方案不符不隐式沿用。"""
    ref=m.get(CURRENT)
    if not ref:return None
    value=read_record(workflow,m,ref);plan=read_json(verified_file(workflow.location(m['study_id']),value['plan_file']))
    if value['a00_run_id']!=m['current'].get('A00') or (plan_id is not None and plan['plan_id']!=plan_id):return None
    return deepcopy(ref)


def publish(workflow,sid,body):
    """后台明确将完整原件解包成独立输入；不生成A01/current或人工复核。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'三库来源绑定字段错误，不接受路径或通过标记')
    safe_id(body['request_id'],'systemsourcebindreq');safe_id(body['expected_acquisition_request_id'],'systemacqreq')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),
        '请填写绑定登记人和说明并明确确认')
    m=workflow.load(sid);home=workflow.location(sid)
    require(not m.get('trashed'),'回收站研究只读')
    for ref in m.get(INDEX,[]):
        value=read_record(workflow,m,ref)
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body and m.get(CURRENT)==ref,'来源绑定请求内容或当前指针已改变，请刷新')
            return dict(value,file=deepcopy(ref),created=False)
    require(body['expected_input_hash']==fingerprint(acquisition.snapshot(workflow,m)),'来源绑定输入已改变，请刷新')
    choices=[]
    for ref in m.get(acquisition.RECORDS,[]):
        record=acquisition.read_record(workflow,m,ref,kind='record')
        request=acquisition.read_record(workflow,m,record['request_file'],kind='request')
        if request['request']['request_id']==body['expected_acquisition_request_id']:choices.append((ref,record,request))
    require(choices,'本研究没有明确获取记录');ref,record,request=choices[-1]
    require(record['state']=='complete' and ref['sha256']==body['expected_record_sha256'],'三库未齐或最新获取记录已改变，请刷新')
    acquisition.require_current(workflow,m,request)
    plans=workflow._analysis_plan_records(m)
    require(plans and plans[-1]['plan_id']==request['request']['expected_plan_id'],'绑定只接受当前明确方案，请刷新后按新方案获取')
    from science_modules.a01.system_source_binding import materialize,validate_binding
    folder=home/'raw/A01_system_bindings'/new_id('sourcebinding')
    value=materialize(home,folder,request,record)
    value.update(schema_version=VERSION,version=VERSION,study_id=sid,request=deepcopy(body),request_hash=fingerprint(body),
        acquisition_record=deepcopy(ref),plan_file=deepcopy(record['plan_file']),
        human_review_written=False,a01_published=False,created_at=now())
    validate_binding(home,value,request,record)
    with write_lock(workflow.root):
        current_m=workflow.load(sid);acquisition.require_current(workflow,current_m,request)
        require(body['expected_input_hash']==fingerprint(acquisition.snapshot(workflow,current_m))
            and current_m.get(CURRENT)==m.get(CURRENT),'来源绑定发布期间输入已改变，请刷新')
        require(workflow._analysis_plan_records(current_m)[-1]['plan_id']==request['request']['expected_plan_id'],'绑定发布期间方案已改变，请刷新')
        path=folder/'binding.json';write_json(path,value);result_ref=file_record(home,path,'system_component_source_binding')
        current_m.setdefault(INDEX,[]).append(result_ref);current_m[CURRENT]=result_ref;workflow.save(current_m)
    return dict(value,file=result_ref,created=True)
