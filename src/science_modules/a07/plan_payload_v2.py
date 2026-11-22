"""报告二版同批事实：复用科学结果，附Degree第二轮范围和精确核译来源。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import hashlib
import json

from contracts import fingerprint, require
from storage import read_json, verified_file
from . import plan_payload as original, plan_facts_v2 as model
from .plan_translations_v2 import check_readability
from science_modules.analysis_protocol import checked_plan
from modulea.core import system_validation as validation
method_references = original.method_references
input_reference = original.input_reference

VERSION = 'A07.plan_payload.2'


def enrichment_source(home, evidence, result, plan, intake):
    """核对新快照实际字节，英文和译文均沿稳定ID归档，不更换富集统计。"""
    require(isinstance(evidence, dict) and set(evidence) == {'snapshot', 'catalog', 'lexicon'}, '富集报告缺少归档来源')
    raw = {key: verified_file(home, ref).read_bytes() for key, ref in evidence.items()}
    source = json.loads(raw['snapshot']); catalog = json.loads(raw['catalog']); lexicon = json.loads(raw['lexicon'])
    require(source['catalog'] == catalog and source['catalog_sha256'] == hashlib.sha256(raw['catalog']).hexdigest()
            and source['lexicon_sha256'] == hashlib.sha256(raw['lexicon']).hexdigest()
            and all(value == lexicon.get(key, {}) for key, value in source['translations'].items()),
            '报告分类、核译或归档指纹不同')
    from science_modules.a05.screening import disease_identity
    require(source['identity'] == disease_identity(intake), '报告来源不属于本病登记')
    return model.automatic_enrichment(result, plan, source)


def network_facts(workflow, manifest, payload):
    """原固定选择优先，缺固定选择时按原A04选择算法派生相同Degree第二轮。"""
    from science_modules.a04.selection_flow import select_from_network, validate_selection
    from .plan_figures_v2 import network_scope
    rid = payload['run_ids'].get('A04')
    if not rid:
        return None
    home = workflow.location(payload['study_id'])
    result = workflow.result(manifest, rid)
    selection = None; reference = None
    for module in ('A06', 'A06_PREP'):
        source_id = payload['run_ids'].get(module)
        if not source_id:
            continue
        fixed_ref = original.input_reference(workflow, manifest, workflow.run(manifest, source_id))
        fixed = read_json(verified_file(home, fixed_ref))
        packet = fixed['payload'] if fixed.get('schema_version') == 'ModuleA.system_decision.1' else fixed['packet']
        require(packet['runs']['A04'] == rid, '报告固定选择不是本批网络')
        reference = packet.get('a04_system_selection_ref')
        if reference:
            record = read_json(verified_file(home, reference))
            require(record['study_id'] == payload['study_id'] and record['stage'] == 'A04_SELECTION', '报告选择来源归属错误')
            selection = record['payload']
            validate_selection(selection, rid, result['summary'], result['tables'], payload['plan'])
            break
    if selection is None:
        selection = select_from_network(rid, result['summary'], result['tables'], payload['plan'])
    return {'network_run_id': rid, 'selection_source': reference, 'selection': selection,
            'main': network_scope(result, selection), 'overview': network_scope(result, selection, overview=True)}


def build(workflow, sid, *, source_evidence=None):
    """从完整原依赖构造新展示事实；不重新统计、不签审核、不修改当前研究。"""
    if getattr(workflow, '_view_cache', None) is None and hasattr(workflow, 'handoff_read_cache'):
        with workflow.handoff_read_cache():
            value = _build_base(workflow, sid, source_evidence=source_evidence)
    else:
        value = _build_base(workflow, sid, source_evidence=source_evidence)
    manifest = workflow.load(sid)
    value['network'] = network_facts(workflow, manifest, value)
    for source in value['sources']:
        if source['label'] == '疾病靶点来源与筛选范围':
            source['description'] = source['description'].replace('组身份未精确对应的疾病范围', '组疾病条目尚未与本病范围精确匹配，暂缓纳入')
    # 已废弃条目保留原统计，只记录当前官方状态，不能默默替换稳定ID。
    value['translation_audit'] = []
    if source_evidence:
        snapshot = read_json(verified_file(workflow.location(sid), source_evidence['snapshot']))
        for tid, entry in snapshot['translations'].items():
            if entry.get('source_obsolete'):
                value['translation_audit'].append({'ID': tid, 'source': entry['source'], 'source_obsolete': True,
                    'note_zh': '原统计使用的注释条目现已废弃；原编号、原英文及统计保持，未替换或重新富集。'})
        if value['translation_audit']:
            value['sources'].append({'label': '注释状态说明', 'description': '、'.join(row['ID'] for row in value['translation_audit'])+'：原注释条目现已废弃；本展示修订保留原统计编号及结果。'})
    return value


def validate(payload, home, *, require_figures=False):
    """逐字段从实际上游重建；图件及核译检查不允许篡改科学事实。"""
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    require(payload.get('schema_version') == VERSION, '报告事实包不是明确第二版')
    home = Path(home).resolve(); workflow = AnalysisPlanWorkflow(home.parents[1]); sid = payload['study_id']
    require(workflow.location(sid).resolve() == home, '报告目录与研究不一致')
    expected = build(workflow, sid, source_evidence=payload.get('source_evidence'))
    value = deepcopy(payload)
    if payload.get('figure_source'):
        from .plan_figures_v2 import validate as validate_figures
        validate_figures(home, payload, expected)
        value['figures'] = []; value['figure_source'] = None
    else:
        require(not require_figures, '正式报告缺少同批完整图件')
    require(fingerprint(value) == fingerprint(expected), '报告事实、范围、名称或核译与实际来源不一致')
    check_readability(payload)
    return expected


# 冻结一版的事实重建结构保留于旧模块；二版仅显式扩展新来源版本。
def _build_base(workflow,sid,*,source_evidence=None):
    """只读重建当前同方案事实；缺分支为waiting，合法空交集不借用旧下游。"""
    m=workflow.load(sid);home=workflow.location(sid);runs={};results={};run_ids={}
    def add(module):
        """纳入完整真实父链；没有完成或祖先已替换时停止，不拼接旧批次。"""
        rid=m['current'].get(module);require(rid,'报告上游尚未生成：'+module)
        run=workflow.run(m,rid);result=workflow.result(m,rid);require(result is not None,'报告上游尚未归档：'+module)
        require(all(m['current'].get(key)==value for key,value in run['parent_runs'].items()),'报告上游已改变，请刷新')
        require(workflow.active(m,rid),'报告来源的真实依赖或独立选择决定已失效：'+module)
        if module in runs:return result
        runs[module]=run;results[module]=result;run_ids[module]=rid
        for parent in run['parent_runs']:add(parent)
        return result
    a03=add('A03')
    for module in ('A00','A01','A02'):add(module)
    require(runs['A01']['config'].get('version') in ('A01.plan_publication.1','A01.system_publication.1','A01.system_publication.2'),
        '新报告方剂侧尚未形成实际三库新方案结果')
    require(runs['A03']['config'].get('version')=='A03.plan_intersection.1','正式新报告须绑定真实新方案交集')
    reference=runs['A03']['inputs']['analysis_plan_file'];record=read_json(verified_file(home,reference));plan=checked_plan(record['plan'])
    require(reference in m.get('analysis_plan_records',[]) and record['study_id']==sid and record['expected_a00']==run_ids['A00']
            and record['plan_id']==runs['A03']['inputs']['analysis_plan_id'],'报告绑定方案不属于本批实际交集')
    intake=deepcopy(results['A00']['summary']);count=a03['summary']['交集靶点数']
    require(type(count) is int and count>=0,'报告交集数量无效')
    branches=[{'branch':'两侧标准化与交集','state':'valid_empty' if count==0 else 'completed',
               'reason_zh':f'本研究同一HGNC口径的交集为{count}个人类基因，来源为本批A01/A02标准化结果'}]
    enrichment=None;docking=None;reasons={}
    def branch(name,state,reason):branches.append({'branch':name,'state':state,'reason_zh':reason})
    def bound(module,version):
        """不同草稿即使研究相同也不能混用；只读取原运行绑定的真实方案。"""
        result=add(module);run=runs[module]
        require(run['config'].get('version') in (version if isinstance(version,tuple) else (version,)) and run['inputs'].get('analysis_plan_file')==reference
                and result['summary'].get('analysis_parameter_hash')==plan['parameter_hash'],
                module+'结果不属于本批新方案，不能拼接报告')
        return result
    if count==0:
        for name in ('PPI网络','GO与KEGG富集','分子对接'):branch(name,'not_applicable','本批交集为空，没有适用分析对象；不运行该分支或借用历史结果')
        reasons={'enrichment':'本批真实交集为空，富集分支不适用，不表示已运行后的零显著。',
                 'docking':'本批真实交集为空，对接分支不适用；没有评分，也不把缺失填零。'}
        require(source_evidence is None,'空交集报告不能混入另一批富集来源')
    else:
        if m['current'].get('A04') and m['runs'][m['current']['A04']].get('result_file'):
            ppi=bound('A04',('A04.plan_network.1','A04.plan_network.2'))
            state='technical_blocked' if ppi['outcome']=='failed' or ppi['summary'].get('handoff_blocked') else 'valid_empty' if ppi['outcome']=='empty' else 'completed'
            branch('PPI网络',state,'本批实际PPI已归档；状态按原科学输出，未以网络节点或文件存在推断成功')
        else:branch('PPI网络','waiting','适用PPI分支尚未完整归档')
        applicable=plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']
        if not applicable:
            branch('GO与KEGG富集','not_applicable','本方案明确未纳入GO及KEGG，不启动统计')
            reasons['enrichment']='本方案未纳入GO及KEGG，不表示已计算后的零显著。'
            require(source_evidence is None,'未纳入富集的方案不能混入统计来源')
        elif m['current'].get('A05') and m['runs'][m['current']['A05']].get('result_file'):
            result=bound('A05',('A05.plan_enrichment.1','A05.plan_enrichment.2'));enrichment=enrichment_source(home,source_evidence,result,plan,intake)
            state='technical_blocked' if result['outcome']=='failed' or result['summary'].get('handoff_blocked') else 'valid_empty' if result['outcome']=='empty' else 'completed'
            branch('GO与KEGG富集',state,'实际R统计按各自检验族及背景生成；未改变BH、显著阈值和完整原统计')
        else:
            branch('GO与KEGG富集','waiting','适用富集分支尚未完整归档');reasons['enrichment']='等待本批真实富集结果，不借用其他研究。'
        score=m['current'].get('A06');prep=m['current'].get('A06_PREP')
        score_current=bool(score and workflow.run(m,score)['parent_runs'].get('A06_PREP')==prep)
        module='A06' if score_current else 'A06_PREP' if prep else None
        if module and m['runs'][m['current'][module]].get('result_file'):
            result=add(module);run=runs[module];preparation_only=module=='A06_PREP'
            if not preparation_only:
                system_scores = ('A06.system_scoring.1', 'A06.system_scoring.2', 'A06.system_scoring_paths.1', 'A06.system_scoring.3')
                require(run['config'].get('version') in ('A06.plan_scoring.1', *system_scores),'当前评分不属于新方案评分协议')
                if run['config'].get('version') in system_scores:
                    require(run.get('execution_protocol')=='ModuleA.system_execution.1' and run['parent_review_ids']=={}
                        and run['inputs'].get('system_input_ref'),'报告系统评分缺少真实系统执行绑定')
            fixed_ref=input_reference(workflow,m,run);fixed=read_json(verified_file(home,fixed_ref))
            if fixed.get('schema_version')=='ModuleA.system_decision.1':
                from modulea.core import system_decisions
                fixed=system_decisions.read_record(workflow,m,fixed_ref)
                require(fixed['stage']=='A06_INPUT' and system_decisions.active(workflow,m,fixed),'报告系统固定名单已失效')
                fixed_packet=fixed['payload']
            else:
                require(fixed_ref in m.get('analysis_plan_a06_input_records',[]),'报告旧固定输入未登记')
                fixed_packet=fixed['packet']
            require(fixed['study_id']==sid and fixed_packet['plan_ref']==reference
                    and fixed_packet['analysis_parameter_hash']==plan['parameter_hash'],'报告固定对接名单不属于本批方案')
            for key,value in fixed_packet['runs'].items():require(m['current'].get(key)==value,'对接固定名单的上游已改变')
            pairs=result['tables'].get('planned_pairs') if preparation_only else result['tables'].get('plan_scoring_pairs')
            packet={'study_id':sid,'run_id':run['run_id'],'compounds':fixed_packet['compounds'],
                    'receptors':fixed_packet['receptors'],'planned_pairs' if preparation_only else 'pairs':pairs}
            docking=model.docking(packet,run['config'],preparation_only=preparation_only)
            branch('分子对接',docking['state'],docking['reason_zh'])
        else:branch('分子对接','waiting','本批对接准备或评分尚未归档');reasons['docking']='等待本批固定对象和实际评分；不填零、不补用其他对象。'
    state=model.completion(branches);records=[]
    actual_receipts=[(ref,validation.read_receipt(workflow,m,ref)) for ref in m.get(validation.INDEX,[])]
    for module,rid in run_ids.items():
        expected=validation.request(workflow,sid,rid);candidates=[]
        for ref,value in actual_receipts:
            if value['run_id']==rid and value['input_hash']==expected['expected_input_hash']:candidates.append((ref,value))
        if candidates:
            ref,value=candidates[-1];records.append({'module':module,'study_id':sid,'authority_kind':'system_validation',
                'passed':value['passed'],'source':deepcopy(ref),'scientific_status':deepcopy(value['scientific_status'])})
    counts={key:results[key]['summary'].get('标准化基因数') for key in ('A01','A02')}
    require(all(type(value) is int and value>=0 for value in counts.values()),'报告两侧缺少实际标准化数量，不能猜测')
    description=f"本研究方剂侧{counts['A01']}个、疾病侧{counts['A02']}个人类标准化基因，交集{count}个。"
    conclusion=description+('交集为空，后续PPI、富集和分子对接不适用。' if count==0 else
        '仍有适用分支未完成，不能表述为整套分析成功。' if not state['all_applicable_finished'] else '各分支按实际完成、空值及失败分别保留，详见完成情况。')
    databases=sorted({str(row['source']) for row in results['A01']['tables'].get('component_sources',[])}|
                     {str(row['database']) for row in results['A01']['tables'].get('source_coverage',[])})
    disease_databases=[str(row['database']) for row in results['A02']['tables'].get('source_summary',[])]
    sources=[{'label':'方剂成分与靶点来源','description':'、'.join(databases)+'；本研究原始三库资料经方案门槛及唯一人类身份核对后形成标准化集合，逐条原件见追溯包。'},
             {'label':'疾病靶点来源与筛选范围','description':'、'.join(disease_databases)+'；只采用本批保存的本病直接范围，标准化后按同一HGNC口径去重；未用缺失评分补零或附加阈值。'},
             {'label':'基因身份口径','description':str(results['A01']['summary']['mapping_rule'])+'；两侧实际映射及补充依据的版本和SHA保存在同批原件索引。'}]
    if runs['A02']['config'].get('version') in ('A02.system_normalization.1','A02.system_normalization.2','A02.system_normalization.3','A02.system_normalization.4','A02.system_normalization.5','A02.system_normalization.6'):
        scope=results['A02'];deferred=scope['summary']['暂缓范围组数']
        require(deferred==sum(row['action']=='deferred' for row in scope['tables']['scope_system_decisions']),
            '报告疾病暂缓数量与实际范围记录不同')
        sources[1]['description']='、'.join(disease_databases)+f'；仅纳入本批系统规则明确的本病直接范围；暂缓{deferred}组身份未精确对应的疾病范围，不作为已排除。'
        sources[1]['description']+='未产生人工范围审核；逐条原因、原文及已有范围意见见A02的scope_system_decisions与同批追溯。标准化按同一HGNC口径去重，无新增评分阈值。'
    if runs['A02']['config'].get('version') in ('A02.system_normalization.4','A02.system_normalization.5'):
        require(intake['analysis_purpose']=='workflow_test' and results['A02']['summary']['database_versions_complete'] is False,'历史版本例外不能作为正式研究或版本完整')
        for notice in results['A02']['summary']['source_limitations_zh']:sources.append({'label':'历史数据库版本限制','description':notice})
    for module in ('A01','A02'):
        if results[module]['summary'].get('identity_exception_protocol')=='ModuleA.identity_exception.1':
            require(intake['analysis_purpose']=='workflow_test','身份例外不能进入正式研究报告')
            for notice in results[module]['summary']['identity_limitations_zh']:
                sources.append({'label':module+'本批身份例外','description':notice+' 明确不采用问题组数：'+str(len(results[module]['tables']['identity_exception_scope']))+'；清单和原始身份问题保留。'})
    if 'A04' in runs and runs['A04']['config'].get('version')=='A04.plan_network.2':
        require(intake['analysis_purpose']=='workflow_test', 'PPI清单例外不能用于正式研究报告')
        ppi=results['A04'];notice=ppi['summary']['identity_notice_zh']
        omitted=ppi['tables']['identity_temporarily_omitted']
        sources.append({'label':'本批PPI身份清单限制','description':notice+' 本批暂不采用'+str(len(omitted))+'项：'+
            '、'.join(row['symbol']+'（'+row['target_id']+'；'+row['reason_zh']+'）' for row in omitted)+
            '；原运行、完整精确清单、用户决定和全部查询原文见同批追溯。'})
    return {'schema_version':VERSION,'study_id':sid,'intake':intake,'plan':plan,'plan_source':deepcopy(reference),
            'counts':{'a01_genes':counts['A01'],'a02_genes':counts['A02'],'intersection':count},
            'run_ids':run_ids,'completion':state,'enrichment':enrichment,'docking':docking,'branch_reasons':reasons,
            'conclusion':conclusion,'network_summary':[description,model.BOUNDARY],
            'sources':sources,
            'research_leads':[],'validation_records':records,
            'references':method_references(run_ids),
            'source_evidence':deepcopy(source_evidence),'figure_source':None,'figures':[]}
