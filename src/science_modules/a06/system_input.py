"""系统批次的原受体筛选和固定准备范围，不复用人工签名字段。"""
from copy import deepcopy
from pathlib import Path
from contracts import fingerprint,require
from storage import read_json,verified_file

VERSION='A06.system_preparation_input.1'


def implementation_files():
    from science_modules.a04 import selection,personalized_selection,selection_flow
    return [Path(__file__),Path(selection.__file__),Path(personalized_selection.__file__),Path(selection_flow.__file__)]


def facts(workflow,m,stage,binding,plan):
    from science_modules.a04.selection_flow import select_from_network
    from science_modules.analysis_protocol import checked_plan
    plan=checked_plan(plan);home=workflow.location(m['study_id']);parents=binding['parent_runs']
    network=workflow.result(m,parents['A04']);run=workflow.run(m,parents['A04'])
    require(run['inputs']['analysis_plan_file']==binding['plan_file']
        and network['summary']['analysis_parameter_hash']==plan['parameter_hash'],'系统受体筛选与本批方案不同')
    selected=select_from_network(parents['A04'],network['summary'],network['tables'],plan)
    if stage=='A04_SELECTION':return selected
    require(stage=='A06_INPUT','未知系统准备输入阶段')
    source=read_json(verified_file(home,binding['selection_ref']))
    require(source['stage']=='A04_SELECTION' and source['payload']==selected,'固定输入名单与本批网络独立复算不同')
    compounds=workflow.result(m,parents['A03_SELECT'])['tables']['selected'];receptors=selected['selected']
    require(compounds,'本批实际成分选择为空，结构准备不适用')
    require(workflow.run(m,parents['A03_SELECT'])['parent_runs']['A03']==parents['A03']
        and run['parent_runs']['A03']==parents['A03'],'固定成分与网络不属于同一交集')
    crun=workflow.run(m,parents['A03_SELECT'])
    require(crun['inputs']['analysis_plan_file']==binding['plan_file'],'成分固定范围不属于本批方案')
    from science_modules.plan_compounds import configuration
    require(crun['config']==configuration(plan),'成分目标或排序不属于本批方案')
    cids=[r['compound_id'] for r in compounds];tids=[r['target_id'] for r in receptors]
    require(all(isinstance(v,str) and v for v in cids+tids) and len(cids)==len(set(cids)) and len(tids)==len(set(tids)),
        '固定名单身份缺失或重复')
    symbols=[r.get('symbol') for r in receptors]
    require(all(isinstance(v,str) and v for v in symbols) and len(symbols)==len(set(symbols)),
        '固定受体标准基因名缺失或重复')
    require(all(r.get('selection_order')==i for i,r in enumerate(receptors,1)),'固定受体次序与A04不一致')
    core={'schema_version':VERSION,'study_id':m['study_id'],'runs':deepcopy(parents),
        'result_refs':{key:deepcopy(refs['result_file']) for key,refs in binding['parent_files'].items()},
        'validation_records':deepcopy(binding['parent_validation_records']),'human_reviews':{},'human_review_written':False,
        'authority_kind':'system_validation','batch_file':deepcopy(binding['batch_file']),
        'plan_ref':deepcopy(binding['plan_file']),'a04_system_selection_ref':deepcopy(binding['selection_ref']),
        'analysis_parameter_hash':plan['parameter_hash'],'compounds':deepcopy(compounds),'receptors':deepcopy(receptors),
        'replacement_after_preparation_failure':False}
    return dict(core,input_key=fingerprint(core),pair_count=len(cids)*len(tids),
        structure_preparation_state='pending' if cids and tids else 'empty_range',execution_available=False)


def validate(workflow,m,stage,binding,plan,payload):
    require(fingerprint(payload)==fingerprint(facts(workflow,m,stage,binding,plan)),
        '系统受体选择或固定准备输入与原算法独立复算不同')


def pair_statuses(packet,compound_statuses,receptor_statuses):
    """只接受本新协议，复用原笛卡尔状态计算；NA及失败不补位。"""
    from types import FunctionType
    from . import plan_input as legacy
    require(packet.get('schema_version')==VERSION and packet.get('human_reviews')=={}
        and packet.get('human_review_written') is False,'系统准备输入版本或人工字段错误')
    # 原函数仅检查版本/指纹/完整组合与ready/NA；局部绑定版本，不修改旧全局协议。
    calculate=FunctionType(legacy.pair_statuses.__code__,dict(vars(legacy),VERSION=VERSION),legacy.pair_statuses.__name__)
    return calculate(packet,compound_statuses,receptor_statuses)
