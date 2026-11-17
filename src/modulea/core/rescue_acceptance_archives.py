"""同图表修订的完整验收包公开账本；锁外落盘，短锁登记，不改科学结果或人工意见。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from contracts import ContractError, fingerprint, require, safe_id
from storage import new_id, now, write_json, write_lock
from . import acceptance_archive_io as archive_io
from . import rescue_presentations as graphs
from .bounded_evidence import digest_file, file_record, read_verified_json, verified_file
from .read_evidence import current_evidence
from .rescue_acceptance_inventory import member_plan, file_entries, presentation_files
from .rescue_pose_evidence import _artifacts
from .rescue_presentation_read import matches_current, select_presentation
from .rescue_presentations import RescuePresentationWorkflow

VERSION='ModuleA.rescue_acceptance_archive.1'
REQUESTS='analysis_plan_rescue_acceptance_archive_requests'
CANDIDATES='analysis_plan_rescue_acceptance_archive_candidates'
INDEX='analysis_plan_rescue_acceptance_archive_records'
FIELDS={'request_id','expected_run_id','expected_revision_id','expected_revision_sha256','expected_input_key',
        'expected_input_hash','author','note','confirmed'}
IMPLEMENTATION_NAMES=('modulea/core/rescue_acceptance_archives.py','modulea/core/acceptance_archive_io.py',
    'modulea/core/rescue_acceptance_inventory.py','modulea/core/rescue_pose_evidence.py',
    'modulea/core/rescue_presentation_read.py','modulea/core/rescue_result_read.py',
    'modulea/core/bounded_evidence.py','modulea/core/kernel.py','modulea/tasks/rescue_presentation.py',
    'modulea/tasks/manager.py','modulea/tasks/worker.py','modulea/tasks/process_tree.py',
    'modulea/tasks/resource_runner.py','modulea/tasks/compute_budget.py','modulea/tasks/process_identity.py')


def implementation():
    """绑定完整包实际实现和现有任务/资源入口；不升级原科学或图表请求。"""
    root=Path(__file__).resolve().parents[2]
    return {name:digest_file(root/name)[1] for name in IMPLEMENTATION_NAMES}


def _check(callback):
    """任务身份/取消检查由原任务入口提供，不建立另一套状态。"""
    if callback:callback()


def _read(w,sid,ref):
    """HTTP范围显式收集证据，其余调用完整流式核原件。"""
    evidence=current_evidence(w.root)
    return evidence.reader.read(w.location(sid),ref) if evidence else read_verified_json(w.location(sid),ref)


def _verify(w,sid,ref):
    """原件也必须进入响应前证明，不能仅核JSON。"""
    evidence=current_evidence(w.root)
    return evidence.reader.verify(w.location(sid),ref) if evidence else verified_file(w.location(sid),ref)


def confirmed(body):
    """严格只接受明确同修订技术请求，路径/名称许可/评分不能由浏览器覆盖。"""
    require(isinstance(body,dict) and set(body)==FIELDS and body['confirmed'] is True,'完整包请求字段或确认无效')
    safe_id(body['request_id'],'rescuezipreq');safe_id(body['expected_run_id'],'run');safe_id(body['expected_revision_id'],'rescueview')
    require(all(isinstance(body[key],str) and 0<len(body[key].strip())<=2000 for key in ('author','note','expected_input_key')),
            '请填写完整包登记人、说明和固定输入')
    for key in ('expected_revision_sha256','expected_input_hash'):
        require(isinstance(body[key],str) and len(body[key])==64 and all(ch in '0123456789abcdef' for ch in body[key]),
                '完整包版本指纹无效')


def material(selected,request_id):
    """沿原验收成员口径保留全证据；逐组合只留下实际MODEL1/context，不缓存全部模式。"""
    bundle=selected['bundle'];w,m,home,run,result,packet=bundle
    plan=member_plan(result,selected);entries=file_entries(plan)
    evidence=current_evidence(w.root)
    for index,pair in enumerate(packet['pairs'],1):
        if pair['state']!='completed':continue
        require(pair.get('execution'),'完整包已评分组合缺少原执行')
        artifacts,_,_=evidence.call(_artifacts,bundle,pair) if evidence else _artifacts(bundle,pair)
        for kind in ('top1','context'):
            raw,name,_=artifacts[kind]
            entries.append({'name':f'poses/pair_{index:06d}/{name}','data':raw,'role':kind})
    entries.append({'name':'目录说明.txt','data':(
        'registered/保留本运行全部原登记；presentation/保留所选图表修订和名称证据。\n'
        'poses/来自原MODEL 1原字节和实际执行说明，不生成新构象。\n'
        '本包固定于归档当时的明确修订；历史适用性另看网页，不代表当前科研批准或严格质控通过。\n'
        '目录逐项给出长度/SHA和原登记关系，不删减大证据，不生成Word。\n').encode('utf8'),'role':'readme'})
    record=selected['record'];bound=selected['binding']
    revision={'revision_id':record['revision_id'],'receipt_sha256':record['file']['sha256'],
        'input_key':bound['source']['basis']['input_key'],'input_hash':record['input_hash'],'matches_input':True,
        'name_counts':deepcopy(selected['view']['name_counts']),
        'allowed_original_name_ids':deepcopy(bound['names']['allowed_original_name_ids'])}
    metadata={'schema_version':'ModuleA.acceptance_bundle.1','archive_protocol':VERSION,'request_id':request_id,
        'study_id':run['study_id'],'run_id':run['run_id'],'input_key':packet['summary']['input_key'],
        'configuration':deepcopy(run['config']),'inputs':deepcopy(run['inputs']),'summary':deepcopy(result['summary']),
        'registered_reference_count':len(result['files']),'registered_unique_file_count':len(plan['registered']),
        'presentation_revision':revision,'presentation_files':presentation_files(plan),'translation_missing_ids':[],
        'scientific_computation_performed':False,'human_review_written':False,
        'note_zh':'完整包只整理本修订全部原件和同批MODEL 1；术语/专名不代表结构身份核实，技术核验不代替科研批准。'}
    return entries,metadata,plan


def binding(selected,min_free_bytes):
    """源由已核图表回执传递，成员集合/构象字节/实现和磁盘配置均绑定。"""
    require(type(min_free_bytes) is int and min_free_bytes>=0,'完整包运行磁盘余量无效')
    entries,_,plan=material(selected,'preview')
    signatures=_signatures(entries)
    record=selected['record']
    return {'schema_version':VERSION,'study_id':record['study_id'],'run_id':record['run_id'],
        'revision_id':record['revision_id'],'presentation_file':deepcopy(record['file']),
        'presentation_request':deepcopy(record['request_file']), 'input_key':selected['bundle'][5]['summary']['input_key'],
        'member_plan_hash':fingerprint(signatures),'implementation':implementation(),'min_free_bytes':min_free_bytes,
        'source_bytes':plan['registered_bytes'],'member_count':len(entries)}


def _signatures(entries):
    """生成与历史读取共用同一成员身份口径，空登记亦显式保留。"""
    return [{'name':entry['name'],'bytes':entry['file']['bytes'] if 'file' in entry else len(entry['data']),
        'sha256':entry['file']['sha256'] if 'file' in entry else sha256(entry['data']).hexdigest(),
        'role':entry['role'],'registrations':entry.get('registrations',[])} for entry in entries]


def validate_request(w,sid,body,min_free_bytes):
    """新生成/恢复都要求原图表仍当前适用；历史读取使用独立路径。"""
    confirmed(body);selected=select_presentation(w,sid,body['expected_run_id'],body['expected_revision_id'])
    require(selected['record']['file']['sha256']==body['expected_revision_sha256']
        and selected['bundle'][5]['summary']['input_key']==body['expected_input_key'],'完整包图表或固定输入已改变')
    require(matches_current(w,selected['manifest'],selected['record']),'完整包来源已暂停、退回或不是当前适用图表')
    bound=binding(selected,min_free_bytes)
    require(fingerprint(bound)==body['expected_input_hash'],'完整包来源、实现或运行条件已改变')
    return selected,bound


def _read_request(w,m,ref):
    """只接受索引中的不可变请求，归档实现字节可历史读取但不能换码恢复。"""
    require(ref in m.get(REQUESTS,[]),'完整包请求未登记')
    sid=m['study_id'];value=_read(w,sid,ref);confirmed(value['request'])
    require(value['schema_version']==VERSION and value['study_id']==sid
        and value['request_hash']==fingerprint(value['request'])
        and value['input_hash']==fingerprint(value['binding'])==value['request']['expected_input_hash'], '完整包请求或绑定损坏')
    body=value['request'];bound=value['binding']
    require(set(bound)=={'schema_version','study_id','run_id','revision_id','presentation_file','presentation_request',
        'input_key','member_plan_hash','implementation','min_free_bytes','source_bytes','member_count'}
        and bound['schema_version']==VERSION and bound['study_id']==sid
        and (bound['run_id'],bound['revision_id'],bound['input_key'],bound['presentation_file']['sha256'])==
            (body['expected_run_id'],body['expected_revision_id'],body['expected_input_key'],body['expected_revision_sha256']),
        '完整包请求声明与图表/研究/运行绑定不同')
    prefix=f'decisions/analysis_plans/rescue_acceptance_archives/{body["request_id"]}/preparations/'
    require(ref['path'].startswith(prefix),'完整包请求归档位置不属于该请求')
    attempt,separator,leaf=ref['path'][len(prefix):].partition('/')
    require(separator and leaf=='request.json','完整包请求归档层级不同');safe_id(attempt,'rescuezippreparation')
    snapshots=value['implementation_files']
    require(set(snapshots)==set(value['binding']['implementation'])==set(IMPLEMENTATION_NAMES),'完整包实现快照缺件')
    prefix=str(Path(ref['path']).parent.as_posix())+'/implementation/'
    for name,file in snapshots.items():
        require(file['path']==prefix+name and file['sha256']==value['binding']['implementation'][name], '完整包实现快照归属不同')
        _verify(w,sid,file)
    return value


def _expected(w,m,request):
    """从固定历史图表重新构造预期，ZIP自述不能替代真实评分/原件。"""
    body=request['request'];selected=select_presentation(w,m['study_id'],body['expected_run_id'],body['expected_revision_id'])
    require(selected['record']['file']==request['binding']['presentation_file'],'完整包固定图表回执不同')
    entries,metadata,plan=material(selected,body['request_id'])
    require(fingerprint(_signatures(entries))==request['binding']['member_plan_hash']
            and plan['registered_bytes']==request['binding']['source_bytes']
            and len(entries)==request['binding']['member_count'],'完整包成员集合或原件数量与绑定不同')
    inventory=[]
    for entry in entries:
        ref=entry.get('file');raw=entry.get('data')
        row={'path':entry['name'],'role':entry['role'],'bytes':ref['bytes'] if ref else len(raw),
             'sha256':ref['sha256'] if ref else sha256(raw).hexdigest()}
        if 'registrations' in entry:row['registrations']=deepcopy(entry['registrations'])
        inventory.append(row)
    metadata.update(files=inventory,inventory_self_hash_excluded=True)
    require(fingerprint(m)==fingerprint(w.load(m['study_id'])),'完整包历史读取期间登记改变')
    return entries,inventory,metadata


def _candidate(w,m,ref,request_ref,request,check_task=None):
    """完整候选必须核同源、同修订、元数据及每个成员，不凭zip存在恢复。"""
    require(fingerprint(_read_request(w,m,request_ref))==fingerprint(request),'完整包请求或归档实现已改变')
    value=_read(w,m['study_id'],ref)
    safe_id(value['archive_id'],'rescuearchive')
    prefix=f'decisions/analysis_plans/rescue_acceptance_archives/{request["request"]["request_id"]}/attempts/'
    require(ref['path'].startswith(prefix),'完整包候选不属于本请求目录')
    attempt,separator,leaf=ref['path'][len(prefix):].partition('/')
    require(separator and leaf=='candidate.json','完整包候选层级不同');safe_id(attempt,'rescuezipattempt')
    parent=ref['path'].rsplit('/',1)[0]
    require(value['archive_file']['path']==parent+'/complete.zip' and value['metadata_file']['path']==parent+'/metadata.json',
            '完整包ZIP与目录不是本次候选的完整原件')
    require(value['schema_version']==VERSION and value['study_id']==m['study_id']
            and value['request_file']==request_ref and value['input_hash']==request['input_hash']
            and value['run_id']==request['binding']['run_id'] and value['revision_id']==request['binding']['revision_id']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False, '完整包候选与固定请求不同')
    _,inventory,metadata=_expected(w,m,request)
    require(fingerprint(_read(w,m['study_id'],value['metadata_file']))==fingerprint(metadata),'完整包目录与同批原件不同')
    path=_verify(w,m['study_id'],value['archive_file'])
    archive_io.validate_archive(path,inventory,metadata,check_task=check_task)
    return value


def read_record(w,sid,ref):
    """历史包仍核原来源，不因新current或后续暂停而丢失原件。"""
    m=w.load(sid);require(ref in m.get(INDEX,[]),'完整包回执未登记')
    value=_read(w,sid,ref);request=_read_request(w,m,value['request_file'])
    require(ref['path']==f'decisions/analysis_plans/rescue_acceptance_archives/{request["request"]["request_id"]}/receipt.json',
            '完整包回执归档位置与请求不同')
    require(value['candidate_file'] in m.get(CANDIDATES,[]),'完整包候选未登记')
    candidate=_candidate(w,m,value['candidate_file'],value['request_file'],request)
    expected=dict(candidate,candidate_file=value['candidate_file'])
    require(fingerprint(value)==fingerprint(expected),'完整包回执与原候选不同')
    require(fingerprint(m)==fingerprint(w.load(sid)),'完整包读取期间研究登记改变')
    return dict(value,file=deepcopy(ref))


def info(w,sid,rid,revision_id,min_free_bytes):
    """只读技术资格与完整包目录，不生成、不登记、不提交科研复核。"""
    selected=select_presentation(w,sid,rid,revision_id);m=selected['manifest'];records=[]
    for ref in m.get(INDEX,[]):
        header=_read(w,sid,ref)
        if header.get('run_id')==rid and header.get('revision_id')==revision_id:records.append(read_record(w,sid,ref))
    applicable=matches_current(w,m,selected['record']);blockers=[]
    if not applicable:blockers.append('所选图表当前不适用；完整历史包仅供追溯')
    bound=binding(selected,min_free_bytes) if applicable else None
    return {'schema_version':VERSION,'run_id':rid,'revision_id':revision_id,
        'enabled':bool(applicable),'blockers_zh':blockers,'expected_input_hash':fingerprint(bound) if bound else None,
        'required_source_bytes':bound['source_bytes'] if bound else None,'current':records[-1] if records and applicable else None,
        'history':records,'read_only':True}


def _register(w,sid,snapshot,field,ref,check_task):
    """长读取与ZIP校验在锁外；短锁只比较完整manifest和任务身份再追加。"""
    with write_lock(w.root):
        _check(check_task);current=w.load(sid)
        require(fingerprint(current)==fingerprint(snapshot),'完整包登记前研究版本已改变，原件保留')
        current.setdefault(field,[]).append(ref);w.save(current)
    return current


def publish(w,sid,body,min_free_bytes,check_task):
    """独立请求/完整候选/回执链；中断后的完整登记候选复用，残件保留但不冒充成功。"""
    _check(check_task);selected,bound=validate_request(w,sid,body,min_free_bytes)
    m=selected['manifest'];home=w.location(sid);request_ref=request=None
    for ref in m.get(REQUESTS,[]):
        value=_read_request(w,m,ref)
        if value['request']['request_id']==body['request_id']:
            require(value['request']==body and value['binding']==bound,'相同完整包请求不能改字段、输入或实现')
            require(request_ref is None,'完整包请求编号重复登记');request_ref,request=ref,value
    for ref in m.get(INDEX,[]):
        value=_read(w,sid,ref)
        if request_ref and value['request_file']==request_ref:return dict(read_record(w,sid,ref),created=False)
    folder=home/'decisions/analysis_plans/rescue_acceptance_archives'/body['request_id']
    if request is None:
        attempt=folder/'preparations'/new_id('rescuezippreparation');attempt.mkdir(parents=True,exist_ok=False)
        snapshots={};root=Path(__file__).resolve().parents[2]
        for name,digest in bound['implementation'].items():
            _check(check_task);raw=(root/name).read_bytes();require(sha256(raw).hexdigest()==digest,'完整包实现准备期间改变')
            target=attempt/'implementation'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            snapshots[name]=file_record(home,target,'rescue_acceptance_implementation')
        request={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                 'binding':bound,'input_hash':fingerprint(bound),'implementation_files':snapshots,'created_at':now()}
        path=attempt/'request.json';write_json(path,request);request_ref=file_record(home,path,'rescue_acceptance_request')
        m=_register(w,sid,m,REQUESTS,request_ref,check_task)
    available=[]
    for ref in m.get(CANDIDATES,[]):
        value=_read(w,sid,ref)
        if value['request_file']==request_ref:available.append(ref)
    if available:
        require(len(available)==1,'同请求完整包候选重复登记');candidate_ref=available[0]
        candidate=_candidate(w,m,candidate_ref,request_ref,request,check_task)
    else:
        _check(check_task);selected,current=validate_request(w,sid,body,min_free_bytes)
        require(current==bound,'完整包打包前来源已改变')
        attempt=folder/'attempts'/new_id('rescuezipattempt');attempt.mkdir(parents=True,exist_ok=False)
        entries,metadata,_=material(selected,body['request_id'])
        produced=archive_io.write_archive(home,attempt/'complete.zip',entries,metadata,
                                          check_task=check_task,min_free_bytes=min_free_bytes)
        _check(check_task);selected,current=validate_request(w,sid,body,min_free_bytes)
        require(current==bound,'完整包完成后来源已改变，未发表')
        require(fingerprint(_read_request(w,selected['manifest'],request_ref))==fingerprint(request),
                '完整包请求或归档实现在打包期间改变，未登记候选')
        path=attempt/'metadata.json';write_json(path,produced['metadata'])
        candidate={'schema_version':VERSION,'study_id':sid,'run_id':bound['run_id'],'revision_id':bound['revision_id'],
            'archive_id':new_id('rescuearchive'),'request_file':request_ref,'input_hash':request['input_hash'],
            'archive_file':produced['archive'],'metadata_file':file_record(home,path,'rescue_acceptance_metadata'),
            'human_review_written':False,'scientific_results_changed':False,'created_at':now()}
        path=attempt/'candidate.json';write_json(path,candidate);candidate_ref=file_record(home,path,'rescue_acceptance_candidate')
        m=_register(w,sid,selected['manifest'],CANDIDATES,candidate_ref,check_task)
    _check(check_task);selected,current=validate_request(w,sid,body,min_free_bytes)
    require(current==bound,'完整包发表前来源或实现已改变')
    m=selected['manifest'];_candidate(w,m,candidate_ref,request_ref,request,check_task)
    value=dict(candidate,candidate_file=candidate_ref);path=folder/'receipt.json'
    if path.exists():
        ref=file_record(home,path,'rescue_acceptance_record')
        require(fingerprint(_read(w,sid,ref))==fingerprint(value),'完整包未登记回执与候选不同，保留待核')
    else:write_json(path,value);ref=file_record(home,path,'rescue_acceptance_record')
    _register(w,sid,m,INDEX,ref,check_task)
    return dict(value,file=ref,created=True)


class RescueAcceptanceArchivesMixin:
    """只叠公开完整包方法，不覆盖原状态/存储/开始或完成科学运行。"""
    def rescue_acceptance_archive_info(self,sid,rid,revision_id,*,min_free_bytes=16*1024*1024):
        return info(self,sid,rid,revision_id,min_free_bytes)

    def publish_rescue_acceptance_archive(self,sid,body,*,min_free_bytes=16*1024*1024,check_task=None):
        return publish(self,sid,body,min_free_bytes,check_task)

    def read_rescue_acceptance_archive(self,sid,ref):
        return read_record(self,sid,ref)


class RescueAcceptanceArchivesWorkflow(RescueAcceptanceArchivesMixin,RescuePresentationWorkflow):
    """公开完整包能力接在现有原生/救援/图表Workflow之上。"""
