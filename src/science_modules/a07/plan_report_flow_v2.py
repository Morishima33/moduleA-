"""独立新A07规范验证：真实系统依赖、同批事实及两份Word内容复核，旧协议原样分派。"""
from contracts import fingerprint,require
from storage import verified_file
from modulea.core.plan_reports_v2 import CONFIG,VERSION,checked_inputs,output


def validate_result(root,run,summary,tables,anomalies,outcome):
    """正式结果逐字段复算，不以Word文件存在或客户端通过标记替代内容一致性。"""
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    from .plan_documents_v2 import validate_document
    workflow=AnalysisPlanWorkflow(root);m=workflow.load(run['study_id']);home=workflow.location(run['study_id'])
    require(run['module_id']=='A07' and run['config']==CONFIG and run.get('execution_authority')=='system_validation'
            and run['parent_review_ids']=={},'新报告必须记录真实系统依赖，不得冒充人工批准')
    _,payload=checked_inputs(workflow,m,run['inputs'])
    parents=payload['run_ids'];artifacts=[workflow.run(m,parents[key])['artifact_id'] for key in sorted(parents)]
    require(run['parent_runs']==parents and run['parent_artifact_ids']==artifacts
            and run['parent_validation_records']=={row['module']:row['source'] for row in payload['validation_records']}
            and run['config_hash']==fingerprint(CONFIG)
            and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':artifacts}),'报告运行指纹或真实上游不一致')
    documents=tables.get('report_files');require(isinstance(documents,list) and len(documents)==2,'新报告必须同时包含主报告和简略版')
    expected=[('detailed_report','主报告.docx',False),('brief_report','简略版.docx',True)]
    for record,(role,name,concise) in zip(documents,expected):
        require(record.get('role')==role and record.get('path')==f"runs/A07/{run['run_id']}/plan_report/{name}",
                '报告文档不属于本次运行或类型不一致')
        validate_document(verified_file(home,record),payload,concise=concise)
    require(fingerprint((summary,tables,outcome))==fingerprint(output(payload,documents)) and anomalies==[],
            '报告摘要、分支状态、结论或数量与同批事实不一致')


def validator(root,fallback):
    """只为显式新版本派发新校验，冻结历史报告行为保持。"""
    def check(run,summary,tables,anomalies,outcome):
        if run.get('config',{}).get('version')!=VERSION:return fallback(run,summary,tables,anomalies,outcome)
        return validate_result(root,run,summary,tables,anomalies,outcome)
    return check
