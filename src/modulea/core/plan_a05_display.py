"""A05新版展示资料与明确决定公开桥接；追加独立归档，不改变科学运行和reviews。"""
from copy import deepcopy
import hashlib
from pathlib import Path
from contracts import fingerprint,require,safe_id
from storage import file_record,new_id,now,read_json,verified_file,write_json,write_lock
from science_modules.analysis_protocol import checked_plan

VERSION='A05.plan_display.1'
INDEX='analysis_plan_a05_display_records'
REQUESTS='analysis_plan_a05_display_requests'
FIELDS={'request_id','expected_a05','expected_display_id','expected_input_hash','author','note','confirmed'}
DECISION={'excluded_ids','uncertain_decisions','translations'}


def model_for(result):
    """按实际统计版本分派独立展示协议，不升级旧资料或修改第一版科学实现。"""
    if result['summary'].get('protocol_version')=='A05.plan_enrichment.2':
        from science_modules.a05 import plan_display_utf8 as model
    else:
        from science_modules.a05 import plan_display as model
    return model


def context(workflow,sid):
    """展示消费实际A05绑定方案，不把后来保存的新草稿偷换到旧统计批次。"""
    m=workflow.load(sid);rid=m['current'].get('A05');home=workflow.location(sid)
    if not rid:return m,None,None,None,None
    run=workflow.run(m,rid)
    if run['config'].get('version') not in ('A05.plan_enrichment.1','A05.plan_enrichment.2'):return m,None,None,None,None
    result=workflow.result(m,rid)
    if result is None:return m,None,None,None,None  # 科学任务未finish时仅读任务，不把它当完整统计。
    record=read_json(verified_file(home,run['inputs']['analysis_plan_file']))
    require(record['study_id']==sid and record['plan_id']==run['inputs']['analysis_plan_id']
            and record['expected_a00']==run['inputs']['expected_a00'],'A05绑定方案或登记归属不一致')
    plan=checked_plan(record['plan'])
    require(plan['parameter_hash']==run['inputs']['analysis_parameter_hash']==result['summary']['analysis_parameter_hash'],'A05展示方案与实际参数不一致')
    return m,run,result,record,plan


def read_record(workflow,m,reference):
    """逐件核验展示原件、统计来源及请求归属，不用研究外资料补齐缺口。"""
    home=workflow.location(m['study_id']);value=read_json(verified_file(home,reference))
    require(value.get('schema_version') in (VERSION,'A05.plan_display.2') and value.get('study_id')==m['study_id'],'A05展示资料归属不一致')
    rid=value['a05_run_id'];require(workflow.run(m,rid)['module_id']=='A05','展示未绑定实际A05')
    require(value['statistical_result']==m['runs'][rid]['result_file'],'展示统计来源与实际运行不一致')
    request=read_json(verified_file(home,value['request']))
    require(value['request'] in m.get(REQUESTS,[]),'A05展示请求未登记到本研究')
    require(request['schema_version']==value['schema_version'] and request['study_id']==m['study_id']
            and request['request_hash']==fingerprint(request['request']) and request['request']['confirmed'] is True,
            'A05展示明确请求或归属无效')
    require(request['request']['expected_a05']==rid and request['request']['expected_input_hash']==fingerprint(request['binding']),
            'A05展示请求与固定输入不一致')
    for ref in [value['source'],*value['source_files'],*value['figures'],*value['implementation_files']]:verified_file(home,ref)
    model=model_for(workflow.result(m,rid))
    require(value['schema_version']==model.VERSION,'A05展示协议与实际统计版本不同')
    source=read_json(verified_file(home,value['source']))
    originals={ref['path'].rsplit('/',1)[-1]:ref for ref in value['source_files']}
    require(set(originals)=={'kegg_classification.json','term_translations.json'} and len(value['source_files'])==2,'展示分类或译名原件不完整')
    import json
    catalog=verified_file(home,originals['kegg_classification.json']).read_bytes()
    lexicon=verified_file(home,originals['term_translations.json']).read_bytes()
    require(hashlib.sha256(catalog).hexdigest()==source['catalog_sha256'] and hashlib.sha256(lexicon).hexdigest()==source['lexicon_sha256'],
            '展示来源与归档原件指纹不一致')
    catalog_data=json.loads(catalog.decode('utf8'));lexicon_data=json.loads(lexicon.decode('utf8'))
    require(catalog_data==source['catalog'] and all(entry==lexicon_data.get(key,{}) for key,entry in source['translations'].items()),
            '展示快照与原始分类或核译词典不一致')
    run=workflow.run(m,rid);plan_record=read_json(verified_file(home,run['inputs']['analysis_plan_file']))
    from science_modules.a05.screening import disease_identity
    require(source['identity']==disease_identity(workflow.run(m,run['inputs']['expected_a00'])['inputs']),'展示疾病身份与本批实际登记不一致')
    plan=checked_plan(plan_record['plan']);base=workflow.result(m,rid)
    decision={key:request['request'][key] for key in DECISION|{'confirmed'}} if request['action']=='confirm' else None
    require(value['decision']==decision,'展示决定与明确请求不一致')
    require(fingerprint(model.build(base,plan,source,decision))==fingerprint(value['presentation']),'展示表与原统计、来源及明确决定不一致')
    return value


def binding(workflow,m,run):
    """指纹只绑定本A05及其登记/上游/批准、真实方案和最新同批展示资料。"""
    rid=run['run_id'];ids={rid,*run['parent_runs'].values(),run['inputs']['expected_a00']}
    latest=None;current=None
    for ref in m.get(INDEX,[]):
        item=read_record(workflow,m,ref)
        if item['a05_run_id']==rid:latest,current=ref,item
    home=workflow.location(m['study_id']);artifacts={workflow.run(m,key)['artifact_id'] for key in ids}
    reviews=[deepcopy(ref) for ref in m.get('reviews',[]) if read_json(verified_file(home,ref)).get('artifact_id') in artifacts]
    snapshot={'study_id':m['study_id'],'a05_run':m['runs'][rid]['run_file'],'a05_result':m['runs'][rid]['result_file'],
              'analysis_plan':run['inputs']['analysis_plan_file'],'parent_review_ids':deepcopy(run['parent_review_ids']),
              'reviews':reviews,
              'current_parents':{key:m['current'].get(key) for key in ('A00','A03','A05')},'display':latest,'trashed':bool(m.get('trashed'))}
    return snapshot,current


def info(workflow,sid):
    """标准库只读已归档展示；未准备时不联网、不生成分类、图件或决定。"""
    m,run,result,record,plan=context(workflow,sid)
    if run is None:return {'supported':False,'enabled':False,'blockers':['当前没有完整新版A05统计，请等待科学任务归档'],'current':None}
    snapshot,current=binding(workflow,m,run);blockers=[]
    if m.get('trashed'):blockers.append('回收站研究只读')
    if not workflow.active(m,run['run_id']):blockers.append('A05统计或其上游批准已失效，请先重新生成正确批次')
    if result['outcome']=='failed' or result['summary'].get('handoff_blocked'):blockers.append('A05统计失败或关键身份待核，不能以展示决定放行')
    return {'supported':True,'enabled':not blockers,'blockers':blockers,'expected_a05':run['run_id'],
            'expected_display_id':current['display_id'] if current else '', 'expected_input_hash':fingerprint(snapshot),
            'plan_id':record['plan_id'],'parameter_hash':plan['parameter_hash'],
            'parameters':{key.removeprefix('a05.'):value for key,value in plan['parameters'].items() if key.startswith('a05.')},
            'current':dict(current,file=snapshot['display']) if current else None,
            'message_zh':'分类和核译只影响本批展示；完整统计及人工批准保持。准备后可明确保存展示范围、暂缓理由与核译依据。'}


def validate(workflow,sid,body,action):
    """拒绝路径、参数和批准注入；准备与明确决定都固定当前完整输入指纹。"""
    require(action in ('prepare','confirm'),'展示动作不支持')
    require(isinstance(body,dict) and set(body)==FIELDS|(DECISION if action=='confirm' else set()),'A05展示请求字段不完整或含未支持选项')
    safe_id(body['request_id'],'a05displayreq');safe_id(body['expected_a05'],'run')
    require(isinstance(body['expected_display_id'],str),'展示版本编号须为字符串')
    if body['expected_display_id']:safe_id(body['expected_display_id'],'a05display')
    require(body['confirmed'] is True and all(isinstance(body[key],str) and 0<len(body[key].strip())<=2000 for key in ('author','note')),
            '请填写展示登记人、依据并明确确认，最多2000字')
    require(not workflow.load(sid).get('trashed'),'回收站研究只读')
    value=info(workflow,sid)
    require(value['supported'],'仅新版A05统计支持本展示协议')
    require(value['enabled'],'展示条件未就绪：'+'；'.join(value['blockers']))
    require(all(body[key]==value[key] for key in ('expected_a05','expected_display_id','expected_input_hash')),'A05统计、展示或复核已改变，请刷新后重新确认')
    require((action=='prepare' and value['current'] is None) or (action=='confirm' and value['current'] is not None),
            '已有展示请保存明确决定，尚未准备则先创建分类与核译资料')
    if action=='confirm':
        m,_,result,_,plan=context(workflow,sid)
        source=read_json(verified_file(workflow.location(sid),value['current']['source']))
        model_for(result).build(result,plan,source,{key:body[key] for key in DECISION|{'confirmed'}})
    return value


def publish(workflow,sid,body,action):
    """公开Workflow委托：先存明确请求，锁外派生图表，锁内重验后追加资料，不改A05。"""
    from science_modules.a05 import plan_display as model
    from science_modules.a05 import screening
    from science_modules.a05.display import LEXICON
    with write_lock(workflow.root):
        m=workflow.load(sid);home=workflow.location(sid)
        for ref in m.get(INDEX,[]):
            previous=read_record(workflow,m,ref)
            old=read_json(verified_file(home,previous['request']))
            if old['request']['request_id']==body.get('request_id'):
                require(old['request']==body and old['action']==action,'请求编号已用于其他展示输入或内容')
                require(m['current'].get('A05')==previous['a05_run_id'] and workflow.active(m,previous['a05_run_id']),'原展示所属A05已改变')
                return previous
        validate(workflow,sid,body,action);m,run,result,_,plan=context(workflow,sid)
        model=model_for(result)
        snapshot,current=binding(workflow,m,run)
        request={'schema_version':model.VERSION,'study_id':sid,'created_at':now(),'action':action,'request':deepcopy(body),
                 'request_hash':fingerprint(body),'binding':snapshot}
        request_ref=None
        for ref in m.get(REQUESTS,[]):
            old=read_json(verified_file(home,ref))
            if old['request']['request_id']==body['request_id']:
                require(old['request']==body and old['action']==action,'请求编号已用于其他内容');request_ref=ref
        if request_ref is None:
            path=home/'decisions/analysis_plans/a05_display/requests'/(body['request_id']+'.json')
            write_json(path,request);request_ref=file_record(home,path,'a05_display_request')
            m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
        if action=='prepare':
            intake=workflow.run(m,run['inputs']['expected_a00'])['inputs']
            source=model.make_source(result,plan,intake)
            raw_sources=[(screening.CATALOG.read_bytes(),'kegg_classification.json'),(LEXICON.read_bytes(),'term_translations.json')]
            require(hashlib.sha256(raw_sources[0][0]).hexdigest()==source['catalog_sha256'] and hashlib.sha256(raw_sources[1][0]).hexdigest()==source['lexicon_sha256'],
                    '分类或核译源文件在准备期间改变，请重新明确准备')
            sources=[]
        else:
            source=read_json(verified_file(home,current['source']));raw_sources=[];sources=deepcopy(current['source_files'])
    decision={key:body[key] for key in DECISION|{'confirmed'}} if action=='confirm' else None
    presentation=model.build(result,plan,source,decision)
    display_id=new_id('a05display');folder=home/'decisions/analysis_plans/a05_display/artifacts'/display_id
    source_path=folder/'source.json';write_json(source_path,source)
    for original,name in raw_sources:
        target=folder/name;target.write_bytes(original);sources.append(file_record(home,target,'a05_display_source_original'))
    # 科学绘图适配只消费派生资料，不更改旧绘图器或原统计。
    from science_modules.a05 import plan_display_figures,plan_figures,display
    figures=[file_record(home,path,'figure') for path in plan_display_figures.draw(presentation,plan,folder/'figures').values()]
    implementation=[]
    modules=(model,model.original,plan_display_figures,plan_figures,display,screening) if model.VERSION=='A05.plan_display.2' else (model,plan_display_figures,plan_figures,display,screening)
    for module in modules:
        path=Path(module.__file__);target=folder/'implementation'/path.name
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
        implementation.append(file_record(home,target,'a05_display_implementation'))
    value={'schema_version':model.VERSION,'study_id':sid,'display_id':display_id,'created_at':now(),'a05_run_id':run['run_id'],
           'request':request_ref,'statistical_result':snapshot['a05_result'],'source':file_record(home,source_path,'a05_display_source'),
           'source_files':sources,'implementation_files':implementation,'figures':figures,'decision':decision,'presentation':presentation}
    with write_lock(workflow.root):
        validate(workflow,sid,body,action);m=workflow.load(sid)
        path=folder/'display.json';write_json(path,value);reference=file_record(home,path,'a05_plan_display')
        m.setdefault(INDEX,[]).append(reference);workflow.save(m)
    return value
