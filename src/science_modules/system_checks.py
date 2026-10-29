"""新版系统技术校验的登记补充：只核对真实A00快照，不制造人工批准。"""
from contracts import check_intake,check_result,fingerprint,require


def intake(run,summary,tables,anomalies,outcome):
    """复验原登记契约和输入结果一致性，正式疾病身份仍由原契约核验。"""
    require(run['module_id']=='A00' and run['parent_runs']=={} and run['parent_review_ids']=={}
            and run['parent_artifact_ids']==[],'登记运行不应有虚构上游或批准')
    check_intake(run['inputs']);check_result(summary,tables,anomalies,outcome)
    require(summary.get('analysis_plan_profile')=='ModuleA.analysis_plan.1','登记不属于新版分析方案')
    require(fingerprint(summary)==fingerprint(run['inputs']) and tables=={} and anomalies==[] and outcome=='success',
            '登记结果与原始输入不一致')
    require(run['config']=={} and run['config_hash']==fingerprint({})
            and run['input_hash']==fingerprint({'inputs':run['inputs'],'parents':[]}), '登记参数或输入指纹不一致')
