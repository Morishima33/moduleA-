"""研究级追溯与数据导出；只读当前研究归档，不启动任务、不改变复核。"""

import csv
import io
import json
from copy import deepcopy

from contracts import MODULES, SCHEMA_VERSION, fingerprint, require
from storage import read_json, verified_file

TRACE_VERSION = "ModuleA.trace_export.1"


def _record(value):
    """从任意输入结构提取已经登记的研究相对文件记录，不接受裸路径。"""
    if not isinstance(value, dict):
        return None
    if not all(key in value for key in ("path", "sha256", "bytes")):
        return None
    if not isinstance(value["path"], str) or not isinstance(value["sha256"], str):
        return None
    return {key: value[key] for key in ("path", "sha256", "bytes", "role") if key in value}


def _records(value, output):
    """递归收集输入、结果、附件和证据文件记录，去重后仍保留出现顺序。"""
    item = _record(value)
    if item is not None:
        key = (item["path"], item["sha256"])
        if key not in {(row["path"], row["sha256"]) for row in output}:
            output.append(item)
        return
    if isinstance(value, dict):
        for child in value.values():
            _records(child, output)
    elif isinstance(value, list):
        for child in value:
            _records(child, output)


def _verified_records(root, records):
    """导出前逐件核验归档文件；修改或缺失时整个导出阻断。"""
    verified = []
    for record in records:
        path = verified_file(root, record)
        item = dict(record)
        item["filename"] = path.name
        verified.append(item)
    return verified


def _stage_execution(workflow, manifest, all_files):
    """核验明确请求与成功回执的研究、阶段及运行关系，失败尝试也进入追溯。"""
    from science_modules.plan_stages_contract import STAGES, VERSION, verified_request
    root = workflow.location(manifest['study_id'])
    requests, receipts = [], []
    references = manifest.get('analysis_plan_stage_requests', [])
    for reference in references:
        value = read_json(verified_file(root, reference))
        body = value['request']
        require(body['stage'] in STAGES, '阶段请求包含未知阶段')
        verified_request(root, reference, body['stage'], body['expected_plan_id'], body['expected_a00'])
        require(value['binding']['study_id'] == manifest['study_id'], '阶段请求研究归属不一致')
        requests.append(dict(value, file=deepcopy(reference)))
        _records(reference, all_files)
        _records(value, all_files)
    for reference in manifest.get('analysis_plan_stage_receipts', []):
        value = read_json(verified_file(root, reference))
        require(value['schema_version'] == VERSION and value['study_id'] == manifest['study_id']
                and value['request'] in references, '阶段回执或请求不属于本研究')
        request = read_json(verified_file(root, value['request']))
        run = workflow.run(manifest, value['run_id'])
        require(value['stage'] == request['request']['stage'] == run['module_id']
                and value['result_file'] == manifest['runs'][value['run_id']]['result_file'],
                '阶段回执与实际运行或结果不一致')
        receipts.append(dict(value, file=deepcopy(reference)))
        _records(reference, all_files)
        _records(value, all_files)
    return {'requests': requests, 'receipts': receipts}


def _plan_decisions(workflow, manifest, all_files):
    """完整保留受体选择、独立复核和固定输入历史，不把它们当科学运行。"""
    root=workflow.location(manifest['study_id'])
    output={}
    for key,index,version in (
            ('receptor_selections','analysis_plan_selection_records','A04.plan_selection.1'),
            ('selection_reviews','analysis_plan_selection_reviews','A04.plan_selection_review.1'),
            ('preparation_inputs','analysis_plan_a06_input_records','A06.plan_preparation_record.1'),
            ('preparation_requests','analysis_plan_preparation_ui_requests','ModuleA.plan_preparation_ui.1'),
            ('preparation_receipts','analysis_plan_preparation_ui_receipts','ModuleA.plan_preparation_ui.1'),
            ('a05_display_requests','analysis_plan_a05_display_requests','A05.plan_display.1'),
            ('a05_display_records','analysis_plan_a05_display_records','A05.plan_display.1'),
            ('system_validation_requests','analysis_plan_system_validation_requests','ModuleA.system_validation.1'),
            ('system_validations','analysis_plan_system_validation_records','ModuleA.system_validation.1'),
            ('system_batches','analysis_plan_system_batch_records','ModuleA.system_execution.1'),
            ('system_batch_events','analysis_plan_system_batch_events','ModuleA.system_execution.1'),
            ('system_decisions','analysis_plan_system_decisions','ModuleA.system_decision.1'),
            ('system_decision_failures','analysis_plan_system_decision_failures','ModuleA.system_decision.1'),
            ('system_qualifications','analysis_plan_system_qualification_records','A06.system_qualification.1'),
            ('system_qualification_failures','analysis_plan_system_qualification_failures','A06.system_qualification.1'),
            ('system_scores','analysis_plan_system_scoring_records','A06.system_scoring.1'),
            ('system_scoring_failures','analysis_plan_system_scoring_failures','A06.system_scoring.1'),
            ('system_pipeline','analysis_plan_system_pipeline_records','ModuleA.system_pipeline.1'),
            ('system_acquisition_requests','analysis_plan_system_acquisition_requests','A01.system_acquisition.1'),
            ('system_acquisitions','analysis_plan_system_acquisition_records','A01.system_acquisition.1'),
            ('system_acquisition_sources','analysis_plan_system_acquisition_source_records','A01.system_acquisition.1'),
            ('system_acquisition_failures','analysis_plan_system_acquisition_failures','A01.system_acquisition.1'),
            ('system_component_sources','analysis_plan_system_component_source_records','A01.system_source_binding.1'),
            ('disease_acquisition_requests','analysis_plan_disease_acquisition_requests','A02.system_acquisition.1'),
            ('disease_acquisitions','analysis_plan_disease_acquisition_records','A02.system_acquisition.1'),
            ('disease_acquisition_sources','analysis_plan_disease_acquisition_sources','A02.system_acquisition.1'),
            ('disease_acquisition_failures','analysis_plan_disease_acquisition_failures','A02.system_acquisition.1'),
            ('report_requests','analysis_plan_report_requests','A07.plan_report.1'),
            ('report_receipts','analysis_plan_report_receipts','A07.plan_report.1'),
            ('report_failures','analysis_plan_report_failures','A07.plan_report.1')):
        output[key]=[]
        for reference in manifest.get(index,[]):
            value=read_json(verified_file(root,reference))
            require(value.get('schema_version')==version and value.get('study_id')==manifest['study_id'],
                    '方案选择或固定输入归属不一致')
            if key=='a05_display_requests':
                require(value['request_hash']==fingerprint(value['request']) and value['request']['confirmed'] is True
                        and value['request']['expected_input_hash']==fingerprint(value['binding'])
                        and value['binding']['study_id']==manifest['study_id'],'A05展示明确请求与输入快照不一致')
                run=workflow.run(manifest,value['request']['expected_a05'])
                require(run['module_id']=='A05' and value['binding']['a05_result']==manifest['runs'][run['run_id']]['result_file'],
                        'A05展示请求统计来源不一致')
            if key=='a05_display_records':
                from .plan_a05_display import read_record
                value=read_record(workflow,manifest,reference)
            if key=='system_validations':
                from .system_validation import read_receipt
                value=read_receipt(workflow,manifest,reference)
            if key=='system_validation_requests':
                require(value['request_hash']==fingerprint(value['request']),'系统校验请求指纹不一致')
            if key=='system_decisions':
                from .system_decisions import read_record
                value=read_record(workflow,manifest,reference)
            if key=='system_decision_failures':
                require(value['state']=='failed' and value['human_review_written'] is False
                    and value['batch_file'] in manifest.get('analysis_plan_system_batch_records',[])
                    and value['error_type'] and value['error_zh'],'系统选择失败不能写作成功名单')
            if key=='system_qualifications':
                run=workflow.run(manifest,value['run_id'])
                require(value['human_review_written'] is False and value['request_hash']==fingerprint(value['request'])
                    and run['config'].get('version')==version and run['batch_file']==value['batch_file']
                    and run['inputs']['source_preparation_run']==value['source_run']
                    and manifest['runs'][run['run_id']]['result_file']==value['result_file'],'系统资格回执与真实归档不同')
            if key=='system_qualification_failures':
                require(value['human_review_written'] is False and value['state']=='failed'
                    and value['error_type'] and value['error_zh'],'系统资格失败诊断无效')
            if key=='system_scores':
                run=workflow.run(manifest,value['run_id'])
                require(value['human_review_written'] is False and run['config'].get('version')==version
                    and run['batch_file']==value['batch_file'] and run['inputs']['scoring_request']==value['request_file']
                    and manifest['runs'][run['run_id']]['result_file']==value['result_file'],'系统评分回执与真实归档不同')
            if key=='system_pipeline':
                from .system_pipeline import read_record
                value=read_record(workflow,manifest,reference)
            if key in ('system_acquisition_requests','system_acquisitions','system_acquisition_failures','system_acquisition_sources'):
                from .system_acquisition import read_record
                kind={'system_acquisition_requests':'request','system_acquisitions':'record','system_acquisition_failures':'failure','system_acquisition_sources':'source'}[key]
                value=read_record(workflow,manifest,reference,kind=kind)
            if key=='system_component_sources':
                from .system_component_sources import read_record
                value=read_record(workflow,manifest,reference)
            if key in ('disease_acquisition_requests','disease_acquisitions','disease_acquisition_sources','disease_acquisition_failures'):
                from .system_disease_acquisition import read_record
                kind={'disease_acquisition_requests':'request','disease_acquisitions':'record',
                    'disease_acquisition_sources':'source','disease_acquisition_failures':'failure'}[key]
                value=read_record(workflow,manifest,reference,kind=kind)
            if key=='system_scoring_failures':
                run=workflow.run(manifest,value['run_id'])
                require(value['human_review_written'] is False and value['state']=='failed'
                    and run['config'].get('version')==version and run['batch_file']==value['batch_file']
                    and value['error_type'] and value['error_zh'],'系统评分失败诊断无效')
            if key=='system_batches':
                from .system_execution import read_batch
                value=read_batch(workflow,manifest,reference)[0]
            if key=='system_batch_events':
                require(value['human_review_written'] is False
                        and value['batch_file'] in manifest.get('analysis_plan_system_batch_records',[]),
                        '系统阶段回执缺少实际批次授权')
                if value['state']=='completed':
                    run=workflow.run(manifest,value['run_id'])
                    require(value['result_file']==manifest['runs'][value['run_id']]['result_file']
                        and run.get('execution_protocol')==version
                        and run['module_id']==value['stage']
                        and run['batch_file']==value['batch_file'],
                        '系统批次阶段回执与实际运行不一致')
                else:
                    require(value['state']=='failed' and value['run_id'] is None and value['error_type'] and value['error_zh'],
                            '系统失败诊断不能伪造科学成功结果')
            if key=='report_requests':
                require(value['request_hash']==fingerprint(value['request']) and value['request']['confirmed'] is True
                        and value['input_hash']==fingerprint(value['binding']),'报告明确请求与实际上游指纹不一致')
            if key=='report_receipts':
                from .plan_reports import read_receipt
                value=read_receipt(workflow,manifest,reference)
            if key=='report_failures':
                require(value.get('authority_kind')=='execution_failure' and value.get('human_review_written') is False
                        and value['request_file'] in manifest.get('analysis_plan_report_requests',[]),'报告失败诊断来源或类型错误')
                if value.get('run_id'):
                    run=workflow.run(manifest,value['run_id'])
                    require(run['module_id']=='A07' and run['inputs']['request_file']==value['request_file'],'报告失败诊断绑定其他运行')
            if key=='preparation_requests':
                require(value['request_hash']==fingerprint(value['request'])
                        and value['request']['confirmed'] is True
                        and value['request']['expected_input_hash']==fingerprint(value['binding'])
                        and value['binding']['study_id']==manifest['study_id'], '准备明确请求与输入快照不一致')
            if key=='preparation_receipts':
                require(value['request'] in manifest.get('analysis_plan_preparation_ui_requests',[]),
                        '准备回执请求不属于本研究')
                run=workflow.run(manifest,value['run_id'])
                require(run['module_id']=='A06_PREP' and value['result_file']==manifest['runs'][value['run_id']]['result_file'],
                        '准备回执与实际运行或结果不一致')
            output[key].append(dict(value,file=deepcopy(reference)))
            _records(reference,all_files);_records(value,all_files)
    return output


def build_trace(workflow, study_id, include_data=False):
    """生成同一研究的模块、版本、来源、参数、结果和文件指纹清单。"""
    manifest = workflow.load(study_id)
    root = workflow.location(study_id)
    modules = []
    all_files = []
    for module_id, (label, dependencies) in MODULES.items():
        run_id = manifest.get("current", {}).get(module_id)
        item = {"module_id": module_id, "label_zh": label, "dependencies": list(dependencies),
                "run_id": run_id, "state": "idle", "result": None, "files": []}
        if run_id:
            run = workflow.run(manifest, run_id)
            if run.get('execution_authority')=='system_validation':
                item['execution_authority']=run['execution_authority']
                item['parent_validation_records']=deepcopy(run['parent_validation_records'])
                if run.get('execution_protocol'):
                    item['execution_protocol']=run['execution_protocol']
                    if run['execution_protocol']=='A02.system_collection.1':
                        item['acquisition_record']=deepcopy(run['inputs']['acquisition_record'])
                    else:item['batch_file']=deepcopy(run['batch_file'])
            item.update({"state": "completed" if manifest["runs"][run_id].get("result_file") else "running",
                         "parent_runs": deepcopy(run.get("parent_runs", {})),
                         "parent_review_ids": deepcopy(run.get("parent_review_ids", {})),
                         "input_hash": run.get("input_hash"), "config_hash": run.get("config_hash"),
                         "code_version": run.get("code_version"), "environment_version": run.get("environment_version"),
                         "inputs": deepcopy(run.get("inputs", {})), "config": deepcopy(run.get("config", {})),
                         "reason": run.get("reason"), "created_at": run.get("created_at")})
            _records(run.get("inputs", {}), all_files)
            if run.get('config',{}).get('version')=='A03.plan_selection.1':
                reference=run['inputs']['execution_request_file']
                request=read_json(verified_file(root,reference))
                body=request['request']
                require(request['schema_version']=='A03.plan_selection.request.1' and request['study_id']==study_id
                        and body['confirmed'] is True and body['expected_input_hash']==fingerprint(request['binding'])
                        and body['expected_a03']==run['parent_runs']['A03']
                        and body['expected_plan_id']==run['inputs']['analysis_plan_id'],
                        '成分选择执行确认与当前运行不一致')
                item['execution_request']=request
            _records(run.get("config", {}), all_files)
            run_ref = manifest["runs"][run_id].get("run_file")
            _records(run_ref, all_files)
            if manifest["runs"][run_id].get("result_file"):
                result = workflow.result(manifest, run_id)
                item["result"] = {"outcome": result.get("outcome"), "summary": deepcopy(result.get("summary", {})),
                                   "anomalies": deepcopy(result.get("anomalies", [])),
                                   "table_names": sorted(result.get("tables", {}).keys())}
                _records(result, all_files)
                if include_data:
                    item["result"]["tables"] = deepcopy(result.get("tables", {}))
                result_ref = manifest["runs"][run_id].get("result_file")
                _records(result_ref, all_files)
        item["files"] = [row for row in all_files if row.get("role", "").startswith(module_id.lower())]
        modules.append(item)

    # 将运行文件与结果文件按模块绑定；未知role仍进入总清单，不能因标签缺失而丢失。
    verified = _verified_records(root, all_files)
    plans = []
    for reference in manifest.get("analysis_plan_records", []):
        plan = read_json(verified_file(root, reference))
        plans.append({"plan_id": plan.get("plan_id"), "parent_draft_id": plan.get("parent_draft_id"),
                      "state": plan.get("state"), "created_at": plan.get("created_at"),
                      "request_hash": plan.get("request_hash"), "plan": deepcopy(plan.get("plan", {})),
                      "file": deepcopy(reference)})
        _records(reference, all_files)
    execution = _stage_execution(workflow, manifest, all_files)
    decisions = _plan_decisions(workflow, manifest, all_files)
    # 方案与执行确认加入后再次核验，并把运行文件回挂到对应模块。
    verified = _verified_records(root, all_files)
    for item in modules:
        marker = f"/runs/{item['module_id']}/"
        item["files"] = [row for row in verified if marker in row["path"]]
    payload = {"schema_version": SCHEMA_VERSION, "trace_version": TRACE_VERSION, "study_id": study_id,
               "manifest_updated_at": manifest.get("updated_at"), "created_at": manifest.get("created_at"),
               "workflow_profile": manifest.get("workflow_profile"), "kind": manifest.get("kind"),
               "current": deepcopy(manifest.get("current", {})), "modules": modules, "plans": plans,
               "stage_execution": execution,
               "plan_decisions": decisions,
               "files": verified, "file_count": len(verified), "include_data": include_data,
               "read_only": True, "note_zh": "本清单及导出数据来自同一研究的当前归档版本；文件均已在导出前核验指纹。"}
    return payload


def trace_csv(payload):
    """展开结果与系统固定名单；派生选择不伪造运行号，完整身份在独立表名与元数据。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["study_id", "module_id", "run_id", "table_name", "row_index", "record_json"])
    for module in payload["modules"]:
        result = module.get("result") or {}
        tables = result.get("tables", {})
        for name, value in tables.items():
            rows = value if isinstance(value, list) else [value]
            for index, row in enumerate(rows):
                writer.writerow([payload["study_id"], module["module_id"], module.get("run_id"), name, index,
                                 json.dumps(row, ensure_ascii=False, separators=(",", ":"))])
        if result.get("summary"):
            writer.writerow([payload["study_id"], module["module_id"], module.get("run_id"), "__summary__", 0,
                             json.dumps(result["summary"], ensure_ascii=False, separators=(",", ":"))])
    for display in payload.get('plan_decisions',{}).get('a05_display_records',[]):
        presentation=display['presentation'];tables=dict(presentation['tables'],groups=presentation['groups'])
        tables['__metadata__']={key:value for key,value in presentation.items() if key not in ('tables','groups')}
        for name,value in tables.items():
            rows=value if isinstance(value,list) else [value]
            for index,row in enumerate(rows):
                writer.writerow([payload['study_id'],'A05',display['a05_run_id'],f"display.{display['display_id']}.{name}",index,
                                 json.dumps(row,ensure_ascii=False,separators=(',',':'))])
    for decision in payload.get('plan_decisions',{}).get('system_decisions',[]):
        tables=dict(decision['payload'])
        tables['__metadata__']={key:value for key,value in decision.items() if key!='payload'}
        module='A04' if decision['stage']=='A04_SELECTION' else 'A06_PREP'
        for name,value in tables.items():
            for index,row in enumerate(value if isinstance(value,list) else [value]):
                writer.writerow([payload['study_id'],module,'',f"system_decision.{decision['decision_id']}.{name}",index,
                                 json.dumps(row,ensure_ascii=False,separators=(',',':'))])
    return output.getvalue().encode("utf-8-sig")


def trace_file_json(payload):
    """保留完整结构化追溯包，便于后续恢复和机器核对。"""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
