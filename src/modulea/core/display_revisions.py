"""另存同批图表与核译；科学运行、统计、评分、Word及复核均不改。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json

from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from .system_validation import same_binding_after_first_approval

VERSION='ModuleA.display_revision.1'
RENDERER='ModuleA.presentation_bundle.2'
REQUESTS='analysis_plan_display_revision_requests'
CANDIDATES='analysis_plan_display_revision_candidates'
INDEX='analysis_plan_display_revision_records'
FAILURES='analysis_plan_display_revision_failures'
FIELDS={'request_id','expected_input_hash','author','note','confirmed'}
MODULES=('A00','A01','A02','A03','A03_SELECT','A04','A05','A06_PREP','A06')


def _json(w,m,ref):
    """只解析本研究已核验原字节。"""
    return read_json(verified_file(w.location(m['study_id']),ref))


def _implementation():
    """绘图和核译版本进入明确请求指纹，不静默重用后来改变的生成器。"""
    root=Path(__file__).resolve().parents[2]
    names=('modulea/core/display_revisions.py','science_modules/presentation_revision.py','science_modules/presentation_revision_v2.py',
           'science_modules/a07/plan_figures_v2.py','science_modules/a07/plan_payload_v2.py',
           'science_modules/a07/plan_facts_v2.py','science_modules/a07/plan_translations_v2.py',
           'science_modules/a07/term_translation_supplement_v2.json','science_modules/a05/plan_display_figures.py',
           'science_modules/a07/plan_payload.py','science_modules/a07/plan_facts.py',
           'science_modules/a05/plan_display.py','science_modules/a05/plan_display_utf8.py',
           'science_modules/a05/display.py','science_modules/a05/figures.py','science_modules/a05/plan_figures.py',
           'science_modules/a05/screening.py','science_modules/a04/selection_flow.py',
           'science_modules/a04/personalized_selection.py','science_modules/a04/selection.py',
           'science_modules/a06/matrix_palette.py','science_modules/a06/trial_presentation.py','report_figures.py')
    return {name:sha256((root/name).read_bytes()).hexdigest() for name in names}


def _fonts():
    """标准库固定现有绘图器使用的两件字体；HTTP不导入Pillow或绘图模块。"""
    paths=[Path('C:/Windows/Fonts')/name for name in ('msyh.ttc','msyhbd.ttc')]
    return [{'name':path.name,'bytes':path.stat().st_size,'sha256':sha256(path.read_bytes()).hexdigest()}
            for path in paths if path.is_file()]


def verify_source_files(w,m,bound):
    """开始与发表前完整复核原附件；任何损坏不以重新绘图掩盖。"""
    from .read_archive import ReadArchive
    home=w.location(m['study_id']);records=[]
    for files in bound['source']['run_files'].values():
        for ref in files.values():
            if ref:records.append(ref)
        value=_json(w,m,files['result_file']);records.extend(value['files'])
    basis=bound['source'].get('a05_basis')
    if basis and basis['kind']=='archived_report_source':
        records.extend(basis['evidence'].values());records.append(basis['payload_file'])
    # 只在一次完整扫描内去重，后一次发表检查重新全读所有不同文件。
    unique={ (ref['path'],ref['bytes'],ref['sha256']):ref for ref in records }
    ReadArchive().verify_all(home,list(unique.values()))


def sources(w,m):
    """固定原运行/结果/父链和实际归档分类；目录不展开所有PDB/历史Word。"""
    sid=m['study_id'];home=w.location(sid);runs={};records={};values={}
    for module in MODULES:
        rid=m['current'].get(module)
        if not rid:continue
        ref=m['runs'][rid];require(ref.get('result_file'),'来源尚未完整归档：'+module)
        run=_json(w,m,ref['run_file']);result=_json(w,m,ref['result_file'])
        require(run['study_id']==result['study_id']==sid and run['run_id']==result['run_id']==rid
                and run['module_id']==result['module_id']==module and run['artifact_id']==result['artifact_id'], '展示来源归属不同')
        require(all(m['current'].get(key)==value for key,value in run['parent_runs'].items()),'展示来源的父运行已改变：'+module)
        runs[module]=rid;records[rid]=deepcopy(ref);values[module]=(run,result)
    require(all(module in runs for module in ('A00','A01','A02','A03')),'请先形成本方案两侧标准化及交集')
    require(values['A03'][0]['config'].get('version')=='A03.plan_intersection.1','仅支持已有新方案结果的展示修订')
    plan_ref=values['A03'][0]['inputs']['analysis_plan_file'];plan=_json(w,m,plan_ref)
    require(plan_ref in m.get('analysis_plan_records',[]) and plan['study_id']==sid,'展示方案不是本研究原登记')
    basis=None
    report_id=m['current'].get('A07')
    if report_id:
        report=_json(w,m,m['runs'][report_id]['run_file']);payload_ref=report['inputs'].get('payload_file')
        if payload_ref:
            payload=_json(w,m,payload_ref)
            if payload.get('run_ids')==runs and payload.get('plan_source')==plan_ref:
                evidence=payload.get('source_evidence')
                if evidence:
                    for ref in evidence.values():verified_file(home,ref)
                    basis={'kind':'archived_report_source','payload_file':deepcopy(payload_ref),'evidence':deepcopy(evidence)}
    if 'A05' in runs:
        # 不能用自动范围盖过另行确认的富集展示决定；该分支后续须显式适配原决定。
        for ref in m.get('analysis_plan_a05_display_records',[]):
            value=_json(w,m,ref)
            require(not (value.get('a05_run_id')==runs['A05'] and value.get('decision')),
                    '本批已有独立富集范围决定，不能用自动展示修订替换；请沿原已确认范围处理')
        if basis is None:
            from science_modules.a05 import screening,display
            basis={'kind':'repository_initial_source','catalog_sha256':sha256(screening.CATALOG.read_bytes()).hexdigest(),
                   'lexicon_sha256':sha256(display.LEXICON.read_bytes()).hexdigest()}
    reviews=[];latest={}
    for ref in m.get('reviews',[]):
        value=_json(w,m,ref)
        if value.get('run_id') in records or value.get('artifact_id') in {r['artifact_id'] for r,_ in values.values()}:
            reviews.append(deepcopy(ref));latest[value['artifact_id']]=value
    require(all(value.get('decision')=='approved' for value in latest.values()),
            '来源已有明确暂存或退回意见，展示修订暂停')
    return {'study_id':sid,'run_ids':runs,'run_files':records,'plan_file':deepcopy(plan_ref),
            'reviews':reviews,'a05_basis':basis,'trashed':bool(m.get('trashed'))}


def binding(w,m):
    """科学来源和生成实现分列，历史展示不随新代码静默升级。"""
    return {'source':sources(w,m),'implementation':_implementation(),'fonts':_fonts(),'renderer_protocol':RENDERER}


def read_request(w,m,ref):
    """恢复只认本研究登记的不可变明确请求。"""
    require(ref in m.get(REQUESTS,[]),'展示修订请求未登记')
    value=_json(w,m,ref);body=value['request']
    require(set(body)==FIELDS and value['schema_version']==VERSION and value['study_id']==m['study_id']
            and value['binding']['source']['study_id']==m['study_id']
            and value['request_hash']==fingerprint(body) and body['confirmed'] is True
            and body['expected_input_hash']==fingerprint(value['binding']), '展示明确请求或来源指纹不同')
    return value


def read_record(w,m,ref):
    """所有图表、核译与实现字节逐件验SHA；历史来源不借用当前其他批次。"""
    require(ref in m.get(INDEX,[]) or ref in m.get(CANDIDATES,[]),'展示修订未登记')
    value=_json(w,m,ref);request=read_request(w,m,value['request_file']);source=request['binding']['source']
    require(value['schema_version']==VERSION and value['study_id']==m['study_id']
            and value['input_hash']==fingerprint(request['binding']) and value['source_run_ids']==source['run_ids']
            and value['source_hash']==fingerprint(source)
            and value['scientific_results_changed'] is False and value['human_review_written'] is False,'展示回执与原请求不同')
    safe_id(value['revision_id'],'displayrev')
    for rid,files in source['run_files'].items():
        require(m['runs'].get(rid)==files,'历史展示来源登记已改变')
        for item in files.values():
            if item:verified_file(w.location(m['study_id']),item)
    for item in value['files']+value['implementation_files']+[value['bundle_file'],value['payload_file']]:
        verified_file(w.location(m['study_id']),item)
    bundle=_json(w,m,value['bundle_file'])
    payload=_json(w,m,value['payload_file'])
    require(bundle['study_id']==m['study_id'] and bundle['run_ids']==source['run_ids']
            and bundle['schema_version']==request['binding'].get('renderer_protocol','ModuleA.presentation_bundle.1')
            and payload['study_id']==m['study_id'] and payload['run_ids']==source['run_ids']
            and bundle['payload_hash']==fingerprint(payload) and bundle['statistics_changed'] is False
            and bundle['word_generated'] is False,'展示包不是同批来源')
    folder=Path(value['payload_file']['path']).parent/'bundle'
    expected=[dict(r,path=(folder/r['path']).as_posix()) for r in bundle['files']]
    require(value['files']==expected and len({r['path'] for r in expected})==len(expected),'展示包文件清单不同')
    require(value.get('render_fonts')==request['binding']['fonts'],'绘图字体与明确版本不同')
    base=folder.parent;code=value['implementation_files'];names=request['binding']['implementation']
    require(len(code)==len(names)+(3 if payload.get('source_evidence') else 0),'展示实现或核译清单不完整')
    by_path={item['path']:item for item in code}
    require(len(by_path)==len(code),'展示实现索引重复')
    for name,digest in names.items():
        item=by_path.get((base/'code'/name).as_posix(),{})
        require(item.get('sha256')==digest
                and item['role']=='display_revision_implementation','展示实现与原请求绑定不同')
    if payload.get('source_evidence'):
        evidence=payload['source_evidence']
        require(set(evidence)=={'catalog','lexicon','snapshot'}
                and all(by_path.get(ref['path'])==ref for ref in evidence.values())
                and all(Path(ref['path']).parent==(base/'translation_source') for ref in evidence.values()),
                '展示核译不是本修订独立归档来源')
    return value


def info(w,sid):
    """目录只核元数据/现有修订，不绘图、不读Word、不改变科研状态。"""
    m=w.load(sid);blockers=[];current_binding=None
    try:current_binding=binding(w,m)
    except (ContractError,OSError,KeyError,ValueError) as error:blockers.append(str(error))
    if m.get('trashed'):blockers.append('回收站研究只读')
    if current_binding and len(current_binding['fonts'])!=2:blockers.append('绘图所需的现有中文字体未齐备')
    history=[];current=None
    for ref in m.get(INDEX,[]):
        value=read_record(w,m,ref);request=read_request(w,m,value['request_file'])
        matches=bool(current_binding and same_binding_after_first_approval(
            w,m,request['binding']['source'],current_binding['source']))
        item=dict(value,file=deepcopy(ref),matches_input=matches)
        history.append(item)
        if matches:current=item
    digest=fingerprint(current_binding) if current_binding else None
    if current and current['input_hash']==digest:blockers.append('本批图表与译名修订已归档')
    return {'schema_version':VERSION,'supported':bool(current_binding),'enabled':bool(current_binding and not blockers),
            'expected_input_hash':digest,'blockers':blockers,'current':current,'history':history}


def validate_request(w,sid,body):
    """客户端只给当前来源指纹和明确意愿，不能覆盖科学或核译内容。"""
    require(isinstance(body,dict) and set(body)==FIELDS,'展示请求字段错误')
    safe_id(body['request_id'],'displayreq')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('author','note')),'请明确填写展示修订人和依据')
    m=w.load(sid);require(not m.get('trashed'),'回收站研究只读')
    for ref in m.get(REQUESTS,[]):
        request=read_request(w,m,ref)
        if request['request']['request_id']==body['request_id']:
            require(request['request']==body,'原请求号已用于其他展示内容')
            require(same_binding_after_first_approval(w,m,request['binding']['source'],sources(w,m)),
                    '展示来源已改变，请刷新')
            for record in m.get(INDEX,[]):
                value=read_record(w,m,record)
                if value['request_file']==ref:
                    verify_source_files(w,m,request['binding'])
                    return m,request['binding'],dict(value,created=False)
    value=binding(w,m)
    require(body['expected_input_hash']==fingerprint(value),'展示来源或实现已改变，请刷新')
    return m,value,None


def _translation_source(w,m,bound,folder):
    """复用原分类/身份/统计范围，只在新快照加入有依据的译名。"""
    if 'A05' not in bound['source']['run_ids']:return None,None
    from science_modules.a05 import plan_display,plan_display_utf8,display,screening
    from science_modules.a07.plan_translations_v2 import SUPPLEMENT
    home=w.location(m['study_id']);basis=bound['source']['a05_basis']
    if basis['kind']=='archived_report_source':
        evidence=basis['evidence'];catalog_raw=verified_file(home,evidence['catalog']).read_bytes()
        lexicon=_json(w,m,evidence['lexicon']);old=_json(w,m,evidence['snapshot'])
    else:
        catalog_raw=screening.CATALOG.read_bytes();lexicon=json.loads(display.LEXICON.read_text('utf-8'));old=None
    additions=json.loads(SUPPLEMENT.read_text('utf-8'))
    for key,entry in additions.items():
        require(not lexicon.get(key) or lexicon[key].get('english')==entry['english'],'原核译英文与补充不同：'+key)
        lexicon[key]=deepcopy(entry)
    a05=bound['source']['run_ids']['A05'];base=w.result(m,a05)
    model=plan_display_utf8 if base['summary'].get('protocol_version')=='A05.plan_enrichment.2' else plan_display
    plan=_json(w,m,bound['source']['plan_file'])['plan'];intake=w.result(m,bound['source']['run_ids']['A00'])['summary']
    source=model.make_source(base,plan,intake,catalog=json.loads(catalog_raw),lexicon=lexicon)
    if old:
        require(all(source[key]==old[key] for key in ('catalog','identity','assessments','statistical_result_hash','parameter_hash')),
                '新译名不能改变原分类、范围或统计')
    folder.mkdir(parents=True,exist_ok=False);catalog=folder/'catalog.json';catalog.write_bytes(catalog_raw)
    lexicon_path=folder/'lexicon.json';write_json(lexicon_path,lexicon)
    source.update(catalog_sha256=sha256(catalog_raw).hexdigest(),catalog_kind='archived_unchanged_catalog',
                  lexicon_sha256=sha256(lexicon_path.read_bytes()).hexdigest(),lexicon_kind='display_revision_snapshot')
    snapshot=folder/'snapshot.json';write_json(snapshot,source)
    return {key:file_record(home,path,'display_revision_translation_source') for key,path in
            (('catalog',catalog),('lexicon',lexicon_path),('snapshot',snapshot))},lexicon


def publish(w,sid,body):
    """在原资源worker中另存展示，开始/发表前复核同批；科学元数据不写。"""
    with write_lock(w.root):
        m,bound,existing=validate_request(w,sid,body)
        if existing:return existing
        home=w.location(sid);request_ref=None
        for ref in m.get(REQUESTS,[]):
            if read_request(w,m,ref)['request']['request_id']==body['request_id']:request_ref=ref
        root=home/'decisions/analysis_plans/display_revisions'/body['request_id']
        if request_ref is None:
            root.mkdir(parents=True,exist_ok=False)
            request={'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                     'binding':deepcopy(bound),'created_at':now()}
            path=root/'request.json';write_json(path,request);request_ref=file_record(home,path,'display_revision_request')
            m.setdefault(REQUESTS,[]).append(request_ref);w.save(m)
        before={k:deepcopy(m[k]) for k in ('current','runs','reviews')}
    try:
        require(len(bound['fonts'])==2,'绘图所需的现有中文字体未齐备')
        verify_source_files(w,m,bound)
        candidate=None;m=w.load(sid)
        for ref in m.get(CANDIDATES,[]):
            value=read_record(w,m,ref)
            if value['request_file']==request_ref:candidate=value
        if candidate is None:
            attempt=root/'attempts'/new_id('displayattempt');attempt.mkdir(parents=True,exist_ok=False)
            with w.handoff_read_cache():
                require(sources(w,m)==bound['source'],'绘图前来源已改变')
                for rid in bound['source']['run_ids'].values():
                    require(w.active(m,rid) and w.result(m,rid) is not None,'本批来源依赖已失效')
                evidence,lexicon=_translation_source(w,m,bound,attempt/'translation_source')
                from science_modules.a07.plan_payload_v2 import build
                payload=build(w,sid,source_evidence=evidence)
                a03=w.result(m,bound['source']['run_ids']['A03'])
            from science_modules.presentation_revision_v2 import build_bundle,validate_bundle
            bundle=build_bundle(payload,a03,attempt/'bundle',lexicon=lexicon)
            validate_bundle(payload,a03,attempt/'bundle',bundle,lexicon=lexicon)
            payload_path=attempt/'payload.json';write_json(payload_path,payload)
            bundle_path=attempt/'bundle.json';write_json(bundle_path,bundle)
            files=[dict(item,path=(attempt/'bundle'/item['path']).relative_to(home).as_posix()) for item in bundle['files']]
            implementation=[];src=Path(__file__).resolve().parents[2]
            for rel,digest in bound['implementation'].items():
                raw=(src/rel).read_bytes();require(sha256(raw).hexdigest()==digest,'绘图实现发生改变')
                path=attempt/'code'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                implementation.append(file_record(home,path,'display_revision_implementation'))
            if evidence:implementation.extend(evidence.values())
            candidate={'schema_version':VERSION,'study_id':sid,'revision_id':new_id('displayrev'),'created_at':now(),
                       'source_run_ids':deepcopy(bound['source']['run_ids']),'request_file':request_ref,'input_hash':fingerprint(bound),
                       'source_hash':fingerprint(bound['source']),'payload_file':file_record(home,payload_path,'display_revision_payload'),
                       'bundle_file':file_record(home,bundle_path,'display_revision_bundle'),'files':files,'implementation_files':implementation,
                       'render_fonts':deepcopy(bound['fonts']),'human_review_written':False,'scientific_results_changed':False}
            with write_lock(w.root):
                m=w.load(sid);require(binding(w,m)==bound,'发表前科学来源或实现已改变')
                path=attempt/'candidate.json';write_json(path,candidate);ref=file_record(home,path,'display_revision_candidate')
                m.setdefault(CANDIDATES,[]).append(ref);read_record(w,m,ref);w.save(m)
        with write_lock(w.root):
            m=w.load(sid);require(binding(w,m)==bound,'展示发表前来源已改变')
            require(all(m[key]==value for key,value in before.items()),'展示不能改科学运行或复核')
            verify_source_files(w,m,bound)
            path=root/(candidate['revision_id']+'.json')
            if path.exists():require(read_json(path)==candidate,'已有展示回执内容不同，不允许覆盖')
            else:write_json(path,candidate)
            ref=file_record(home,path,'display_revision_receipt');m.setdefault(INDEX,[]).append(ref)
            read_record(w,m,ref);w.save(m)
        return dict(candidate,created=True,file=ref)
    except Exception as error:
        with write_lock(w.root):
            m=w.load(sid);path=root/(new_id('displayfailure')+'.json')
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'error_zh':str(error),'created_at':now()}
            write_json(path,value);m.setdefault(FAILURES,[]).append(file_record(home,path,'display_revision_failure'));w.save(m)
        raise
