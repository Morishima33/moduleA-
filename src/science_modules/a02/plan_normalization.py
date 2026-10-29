"""新版三库A01已标准化：疾病侧沿用原科学核算，保留同映射A01及其方案和复核。"""
from copy import deepcopy
from types import FunctionType
from contracts import fingerprint,require
import normalization as legacy

VERSION='A02.plan_normalization_bridge.1'


def functions(workflow,sid):
    """局部适配旧双侧入口，不修改全局函数、不重筛A01或伪造批准。"""
    m=workflow.load(sid);rid=m['current'].get('A01');require(rid,'请先整理新方案A01三库结果')
    run=workflow.run(m,rid);base=workflow.result(m,rid)
    require(run['config'].get('version')=='A01.plan_publication.1' and base is not None,'当前A01不是完整新方案三库结果')
    require(workflow.approved(m,rid),'请先复核通过新方案A01三库结果，疾病标准化不会替换它')
    # 真实生产三库验证器重新核对原件、参数、HGNC及完整关系，不能仅信任表名。
    from science_modules.a01.plan_flow import validator
    def reject(*_):require(False,'A01协议不能回退旧候选校验')
    validator(workflow.root,reject)(run,base['summary'],base['tables'],base['anomalies'],base['outcome'])
    require('normalized_compound_targets' in base['tables'] and 'identity_issues' in base['tables'],
            '新方案A01缺少真实标准化关系或身份清单')
    original=legacy.compute
    def compute(current,mapper,module,*args,**kwargs):
        """只有已经独立核对的A01复用原结果；疾病计算仍逐项调用原compute。"""
        if module!='A01':return original(current,mapper,module,*args,**kwargs)
        latest=workflow.load(sid)
        require(latest['current'].get('A01')==rid and workflow.approved(latest,rid),
                '新方案A01或复核已改变，请刷新后重新确认')
        require(fingerprint(current)==fingerprint(base),'标准化期间A01原结果已改变，请刷新')
        summary=base['summary'];supplement=mapper.supplement.digest if mapper.supplement else ''
        require(summary.get('mapping_snapshot')==mapper.digest and summary.get('mapping_rule')==mapper.rule
                and summary.get('identity_evidence_snapshot','')==supplement,
                '新方案A01与当前HGNC/补充证据不同，请按原方案重新发布A01，不沿用旧批准')
        return deepcopy(summary),deepcopy(base['tables']),deepcopy(base['anomalies'])
    namespace=dict(vars(legacy),compute=compute)
    preview=FunctionType(legacy.preview.__code__,namespace,legacy.preview.__name__,legacy.preview.__defaults__,legacy.preview.__closure__)
    namespace['preview']=preview
    publish=FunctionType(legacy.publish.__code__,namespace,legacy.publish.__name__,legacy.publish.__defaults__,legacy.publish.__closure__)
    return preview,publish


def preview(workflow,sid):
    """规范验证后的原A01保持，仅预览真实五库疾病身份与范围。"""
    action,_=functions(workflow,sid);return action(workflow,sid)


def publish(workflow,sid,stamp,reviewer,reason,accept_scope,accept_omit,accept_source_exception=False):
    """旧发布器在写锁内再核对指纹；A01同源原件和已有复核保持，A02另存待复核。"""
    _,action=functions(workflow,sid)
    return action(workflow,sid,stamp,reviewer,reason,accept_scope,accept_omit,accept_source_exception)
