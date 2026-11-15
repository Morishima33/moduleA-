"""报告三版明确补救事实接续：旧完成批可另存，不重跑统计评分，不升级旧请求。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import hashlib
from contracts import ContractError, fingerprint, require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from . import plan_reports as original
from .plan_report_contract import validate_receipts

VERSION = 'A07.plan_report.3'
CONFIG = {'version': VERSION, 'dependency_kind': 'system_validation', 'automatic_approval': False,
          'payload_version': 'A07.plan_payload.3', 'documents_version': 'A07.plan_documents.3',
          'figures_version': 'A07.plan_figures.3', 'translation_version': 'A07.plan_translation.2'}
REQUESTS = 'analysis_plan_report_rescue_requests'
RECEIPTS = 'analysis_plan_report_rescue_receipts'
FAILURES = 'analysis_plan_report_rescue_failures'
FIELDS = original.FIELDS
_NAMESPACE = dict(vars(original), VERSION=VERSION, CONFIG=CONFIG, REQUESTS=REQUESTS, RECEIPTS=RECEIPTS, FAILURES=FAILURES)


# 复用原科学依赖、写锁、回执和失败诊断；二版只替换明确的新展示实现。
for _name in ('binding', 'scientific_binding', 'read_receipt', 'validate_request', 'begin', 'is_active', 'output', 'publish'):
    _source = getattr(original, _name)
    _function = FunctionType(_source.__code__, _NAMESPACE, _name, _source.__defaults__, _source.__closure__)
    _function.__kwdefaults__ = dict(_source.__kwdefaults__ or {})
    globals()[_name] = _NAMESPACE[_name] = _function
_info_base = FunctionType(original._info.__code__, _NAMESPACE, '_info_base')


def _info(workflow, sid):
    """只读资格补上实际图表译名核查；未知条目给稳定ID，不生成Word或写快照。"""
    value = _info_base(workflow, sid)
    value['missing_translations'] = []
    if value['supported']:
        m = workflow.load(sid)
        a03 = m['current'].get('A03')
        if a03 and workflow.result(m, a03)['summary']['交集靶点数'] and m['current'].get('A05'):
            plan = read_json(verified_file(workflow.location(sid), workflow.run(m, a03)['inputs']['analysis_plan_file']))['plan']
            if plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']:
                try:
                    from science_modules.a05 import plan_display, plan_display_utf8
                    from science_modules.a07.plan_translations_v2 import merged_lexicon, check_readability
                    from science_modules.a07.plan_facts_v2 import automatic_enrichment
                    base = workflow.result(m, m['current']['A05'])
                    model = plan_display_utf8 if base['summary'].get('protocol_version') == 'A05.plan_enrichment.2' else plan_display
                    intake = workflow.result(m, m['current']['A00'])['summary']
                    source = model.make_source(base, plan, intake, lexicon=merged_lexicon())
                    facts = automatic_enrichment(base, plan, source)
                    value['missing_translations'] = facts['pending_translations']
                    check_readability({'enrichment': facts})
                except (ValueError, KeyError, TypeError, OSError) as error:
                    value['blockers'].append(str(error))
    value['enabled'] = not value['blockers']
    value['message_zh'] = '明确生成本批第三版报告；按实际补救评分、原范围和逐区域限制归档，缺译或未完成时阻断，历史报告保持。'
    return value


def info(workflow, sid):
    """使用原同次读取缓存；刷新仅查询资格，不启动生成或修订。"""
    if getattr(workflow, '_view_cache', None) is None and hasattr(workflow, 'handoff_read_cache'):
        with workflow.handoff_read_cache():
            return _info(workflow, sid)
    return _info(workflow, sid)


def archive_enrichment(workflow, m, folder):
    """仅为新请求合并并归档原词典与独立核译补充，历史字节不改。"""
    a03 = m['current']['A03']
    if not workflow.result(m, a03)['summary']['交集靶点数']:
        return None
    home = workflow.location(m['study_id'])
    plan = read_json(verified_file(home, workflow.run(m, a03)['inputs']['analysis_plan_file']))['plan']
    rid = m['current'].get('A05')
    if not rid or not (plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']):
        return None
    from science_modules.a05 import plan_display, plan_display_utf8
    from science_modules.a07.plan_translations_v2 import merged_lexicon
    base = workflow.result(m, rid)
    model = plan_display_utf8 if base['summary'].get('protocol_version') == 'A05.plan_enrichment.2' else plan_display
    lexicon = merged_lexicon()
    intake = workflow.result(m, m['current']['A00'])['summary']
    source = model.make_source(base, plan, intake, lexicon=lexicon)
    target = folder/'a05_source'; target.mkdir(parents=True, exist_ok=False)
    catalog = target/'catalog.json'; catalog.write_bytes(model.screening.CATALOG.read_bytes())
    lexicon_path = target/'lexicon.json'; write_json(lexicon_path, lexicon)
    source['lexicon_sha256'] = hashlib.sha256(lexicon_path.read_bytes()).hexdigest()
    source['lexicon_kind'] = 'report_revision_snapshot'
    snapshot = target/'snapshot.json'; write_json(snapshot, source)
    return {'catalog': file_record(home, catalog, 'report_enrichment_source'),
            'lexicon': file_record(home, lexicon_path, 'report_enrichment_source'),
            'snapshot': file_record(home, snapshot, 'report_enrichment_snapshot')}


def checked_inputs_archive(workflow,m,inputs):
    """状态读取只核已发表的不可变证据与当前完整依赖，标准库内不运行科学工厂。"""
    require(set(inputs)=={'request_file','payload_file'} and inputs['request_file'] in m.get(REQUESTS,[]),'报告请求未登记或输入字段错误')
    home=workflow.location(m['study_id']);request=read_json(verified_file(home,inputs['request_file']))
    require(request.get('schema_version')==VERSION and request.get('study_id')==m['study_id']
            and request['request_hash']==fingerprint(request['request']) and request['request']['confirmed'] is True
            and request['input_hash']==fingerprint(request['binding'])
            and original.system.same_binding_after_first_approval(
                workflow,m,scientific_binding(request['binding']),scientific_binding(binding(workflow,m))),
            '报告明确请求、校验或上游已改变，请刷新')
    payload=read_json(verified_file(home,inputs['payload_file']))
    require(payload.get('schema_version')==CONFIG['payload_version'] and payload.get('study_id')==m['study_id'],
            '补救报告事实版本或研究不同')
    validate_receipts(workflow,m,payload)
    require(all(workflow.active(m,rid) for rid in payload['run_ids'].values()), '补救报告真实上游已失效')
    from science_modules.a07.plan_facts_v2 import completion
    require(payload['completion']==completion(payload['completion']['branches'])
            and payload['completion']['all_applicable_finished'], '报告必须等待所有适用分支结束')
    from .trace_export import _records
    from .read_archive import ReadArchive
    references=[];_records(payload,references)
    index=read_json(verified_file(home,payload['figure_source']));_records(index,references)
    require(index.get('schema_version')==CONFIG['figures_version'] and index.get('study_id')==m['study_id']
            and index.get('run_ids')==payload['run_ids'] and index.get('figures')==payload['figures']
            and index.get('human_review_written') is False, '报告图件归档归属不同')
    base=deepcopy(payload);base['figures']=[];base['figure_source']=None
    require(index.get('payload_hash')==fingerprint(base), '报告图件与原事实指纹不同')
    unique={(ref['path'],ref['sha256'],ref['bytes']):ref for ref in references}
    ReadArchive().verify_all(home,list(unique.values()))
    return request,payload


def checked_inputs(workflow,m,inputs):
    """生产begin/validator仍完整重建同批事实和科学规范，不采用只读归档作为放行。"""
    request,payload=checked_inputs_archive(workflow,m,inputs)
    home=workflow.location(m['study_id'])
    from science_modules.a07.plan_payload_v3 import validate
    validate(payload,home,require_figures=True);validate_receipts(workflow,m,payload)
    require(payload['completion']['all_applicable_finished'],'报告必须等待所有适用分支结束')
    return request,payload


def is_active(workflow,m,run):
    """三版状态保持真实完整父链、回执与配置，读取不导入科学或文档依赖。"""
    if m['current'].get('A07')!=run['run_id']:
        return False
    try:
        _,payload=checked_inputs_archive(workflow,m,run['inputs'])
        parents=payload['run_ids']
        artifacts=[workflow.run(m,parents[key])['artifact_id'] for key in sorted(parents)]
        return (run['config']==CONFIG and run['config_hash']==fingerprint(CONFIG)
                and run.get('execution_authority')=='system_validation' and run['parent_review_ids']=={}
                and run['parent_runs']==parents and run['parent_artifact_ids']==artifacts
                and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':artifacts})
                and run['parent_validation_records']=={row['module']:row['source'] for row in payload['validation_records']})
    except ContractError:
        return False

def _publish(workflow,sid,body):
    """公开Workflow委托：先保存明确请求，锁外绘图/Word，锁内再核对真实上游并发布。"""
    with write_lock(workflow.root):
        m=workflow.load(sid)
        for ref in m.get(RECEIPTS,[]):
            old=read_receipt(workflow,m,ref)
            if old['request_id']==body.get('request_id'):
                request=read_json(verified_file(workflow.location(sid),old['request_file']))
                require(request['request']==body,'报告请求编号已用于其他内容');return workflow.result(m,old['run_id'])
        m=validate_request(workflow,sid,body);home=workflow.location(sid)
        for ref in m.get(REQUESTS,[]):
            old=read_json(verified_file(home,ref));require(old['request_id']!=body['request_id'],'该报告请求已受理但尚未完整发布，请明确提交新请求')
        folder=home/'decisions/analysis_plans/reports'/body['request_id']
        record={'schema_version':VERSION,'study_id':sid,'request_id':body['request_id'],'request':deepcopy(body),
                'request_hash':fingerprint(body),'binding':binding(workflow,m),'input_hash':body['expected_input_hash'],'created_at':now()}
        path=folder/'request.json';write_json(path,record);request_ref=file_record(home,path,'plan_report_request')
        m.setdefault(REQUESTS,[]).append(request_ref);workflow.save(m)
    source=archive_enrichment(workflow,m,folder)
    from science_modules.a07.plan_payload_v3 import build as facts
    from science_modules.a07.plan_figures_v3 import attach
    from science_modules.a07.plan_documents_v3 import build as document,validate_document
    payload=facts(workflow,sid,source_evidence=source)
    require(payload['completion']['all_applicable_finished'],'报告必须等待所有适用分支结束，明确请求已保留')
    validate_receipts(workflow,workflow.load(sid),payload)
    from science_modules.a07.plan_translations_v2 import check_readability
    check_readability(payload)
    payload=attach(workflow,payload,folder/'figures');path=folder/'payload.json';write_json(path,payload)
    inputs={'request_file':request_ref,'payload_file':file_record(home,path,'plan_report_payload')}
    with write_lock(workflow.root):
        m=validate_request(workflow,sid,body);run=workflow._begin(m,'A07',inputs,CONFIG,body['note']);workflow.save(m)
    documents=[];output_folder=home/'runs/A07'/run['run_id']/'plan_report'
    for concise,name,role in ((False,'主报告.docx','detailed_report'),(True,'简略版.docx','brief_report')):
        path=document(payload,output_folder/name,home,concise=concise);validate_document(path,payload,concise=concise)
        documents.append(file_record(home,path,role))
    summary,tables,outcome=output(payload,documents)
    with write_lock(workflow.root):
        m=workflow.load(sid);require(is_active(workflow,m,run),'报告生成期间上游或校验已改变，不发布旧报告')
        from science_modules.a07.plan_report_flow_v3 import validate_result
        validate_result(workflow.root,run,summary,tables,[],outcome)
        from .trace_export import _records
        sources=[];_records(inputs,sources);_records(payload,sources)
        index=read_json(verified_file(home,payload['figure_source']));_records(index,sources)
        for rid in payload['run_ids'].values():_records(workflow.result(m,rid),sources)
        result=workflow._finish(m,run['run_id'],summary,tables,[],outcome,sources=sources,attachments=documents)
        receipt={'schema_version':VERSION,'study_id':sid,'request_id':body['request_id'],'request_file':request_ref,
                 'run_id':run['run_id'],'result_file':m['runs'][run['run_id']]['result_file'],'payload_file':inputs['payload_file'],
                 'files':deepcopy(result['files']),
                 'human_review_written':False,'created_at':now()}
        path=folder/'receipt.json';write_json(path,receipt);m.setdefault(RECEIPTS,[]).append(file_record(home,path,'plan_report_receipt'));workflow.save(m)
    return result

_base_output = output


def output(payload, documents):
    """补救代次、未成功区域和限制与报告同源，不将区域次数写成组合数。"""
    summary, tables, outcome = _base_output(payload, documents)
    rescue = (payload.get('docking') or {}).get('rescue')
    if rescue:
        tables['rescue_summary'] = [deepcopy(rescue['summary'])]
        tables['rescue_failed_regions'] = [
            {key: row[key] for key in ('compound_id', 'target_id', 'region_id', 'state', 'score', 'reason_zh')}
            for row in rescue['failed_regions']]
        tables['limitations'].append({'限制': rescue['notice_zh']})
    return summary, tables, outcome


_NAMESPACE.update(info=info, _info=_info, archive_enrichment=archive_enrichment, output=output, is_active=is_active,
                  checked_inputs=checked_inputs, _publish=_publish)
