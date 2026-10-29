"""新版报告的标准库依赖契约：真实系统证据独立于人工批准，不接受客户端通过标记。"""
from contracts import fingerprint,require
from .system_validation import INDEX,read_receipt,binding


def validate_receipts(workflow,manifest,payload):
    """核对适用运行闭包及每个当前规范回执，报告自身最终复核不污染上游证据。"""
    sid=manifest['study_id'];require(payload.get('study_id')==sid,'报告系统校验研究归属不一致')
    runs=payload.get('run_ids');require(isinstance(runs,dict) and all(runs.get(key) for key in ('A00','A01','A02','A03')),
        '正式报告缺少固定上游运行链')
    for module,rid in runs.items():
        require(manifest['current'].get(module)==rid,'报告运行已改变，请刷新')
        run=workflow.run(manifest,rid);require(run['module_id']==module,'报告上游模块归属不一致')
        review=workflow.latest_review(manifest,run['artifact_id'])
        require(not review or review['decision']=='approved','报告来源已有明确暂存或退回决定，不能用系统回执覆盖：'+module)
        require(all(runs.get(parent)==value for parent,value in run['parent_runs'].items()),'报告未固定完整同批上游运行')
    seen=set();records=payload.get('validation_records');require(isinstance(records,list),'报告缺少实际系统校验列表')
    for supplied in records:
        module=supplied.get('module');require(module in runs and module not in seen,'报告系统校验模块未知或重复')
        reference=supplied.get('source');require(reference in manifest.get(INDEX,[]),'系统校验回执未登记到本研究')
        value=read_receipt(workflow,manifest,reference);rid=runs[module]
        require(value['passed'] is True and value['module_id']==module and value['run_id']==rid
                and supplied.get('study_id')==sid and supplied.get('authority_kind')=='system_validation'
                and supplied.get('passed') is True,'报告缺少该模块真实通过的规范回执')
        _,_,_,snapshot=binding(workflow,sid,rid)
        require(fingerprint(snapshot)==value['input_hash'],'系统校验所绑定的完整依赖或相关复核已改变')
        seen.add(module)
    require(seen==set(runs),'报告仍缺少适用模块系统校验回执')
    return True
