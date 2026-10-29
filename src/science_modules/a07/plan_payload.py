"""报告事实由同批真实运行重建；不信任自由填写的结论、通过标记、评分或分支状态。"""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from contracts import fingerprint,require
from storage import read_json,verified_file
from science_modules.analysis_protocol import checked_plan
from modulea.core import system_validation as validation
from . import plan_facts as model

VERSION='A07.plan_payload.1'


def method_references(modules):
    """仅列实际执行分支的既有固定方法文献，读取字面数据，不导入旧报告科学包。"""
    import ast
    source=Path(__file__).resolve().parents[2]/'report_flow.py'
    node=next(item for item in ast.parse(source.read_text('utf8')).body if isinstance(item,ast.Assign)
              and any(isinstance(target,ast.Name) and target.id=='METHOD_REFERENCES' for target in item.targets))
    rows=ast.literal_eval(node.value);ids=set()
    if 'A04' in modules:ids.add('R1')
    if 'A05' in modules:ids.update(('R2','R3'))
    if 'A06' in modules:ids.update(('R4','R5'))
    return [row['文献']+' '+row['链接'] for row in rows if row['编号'] in ids] or [
        '本批未执行PPI、富集或分子对接；各数据库原件与HGNC标准化依据见本研究同批来源及追溯资料。']


def enrichment_source(home,evidence,result,plan,intake):
    """核对归档分类、原译名及统计快照，不能用内联假分类覆盖实际来源。"""
    require(isinstance(evidence,dict) and set(evidence)=={'snapshot','catalog','lexicon'},'富集报告缺少实际归档来源')
    raw={key:verified_file(home,ref).read_bytes() for key,ref in evidence.items()}
    source=json.loads(raw['snapshot']);catalog=json.loads(raw['catalog']);lexicon=json.loads(raw['lexicon'])
    require(source['catalog']==catalog and source['catalog_sha256']==hashlib.sha256(raw['catalog']).hexdigest()
            and source['lexicon_sha256']==hashlib.sha256(raw['lexicon']).hexdigest()
            and all(value==lexicon.get(key,{}) for key,value in source['translations'].items()),'报告分类、译名与原件不一致')
    from science_modules.a05.screening import disease_identity
    require(source['identity']==disease_identity(intake),'报告范围身份不属于当前研究')
    return model.automatic_enrichment(result,plan,source)


def input_reference(workflow,m,run):
    """沿已登记的准备修订寻找固定输入，不读取其他研究或借用当前另一份输入。"""
    home=workflow.location(m['study_id']);seen=set()
    for _ in range(10):
        require(run['run_id'] not in seen,'对接准备修订依赖循环');seen.add(run['run_id'])
        if run['inputs'].get('a06_plan_input'):return run['inputs']['a06_plan_input']
        key=next((key for key in ('reference_preparation_run','source_run','preparation_run') if run['inputs'].get(key)),None)
        require(key,'准备版本缺少原固定输入来源，不能生成报告矩阵')
        ref=run['inputs'][key];value=read_json(verified_file(home,ref));rid=value['run_id']
        require(rid in m['runs'] and m['runs'][rid]['run_file']==ref and value['study_id']==m['study_id'],
                '准备修订不属于本研究真实登记运行')
        run=value
    require(False,'准备修订层数异常，不能推测输入')


def build(workflow,sid,*,source_evidence=None):
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
    require(runs['A01']['config'].get('version')=='A01.plan_publication.1','新报告方剂侧尚未形成实际三库新方案结果')
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
        require(run['config'].get('version')==version and run['inputs'].get('analysis_plan_file')==reference
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
            ppi=bound('A04','A04.plan_network.1')
            state='technical_blocked' if ppi['outcome']=='failed' or ppi['summary'].get('handoff_blocked') else 'valid_empty' if ppi['outcome']=='empty' else 'completed'
            branch('PPI网络',state,'本批实际PPI已归档；状态按原科学输出，未以网络节点或文件存在推断成功')
        else:branch('PPI网络','waiting','适用PPI分支尚未完整归档')
        applicable=plan['parameters']['a05.include_go'] or plan['parameters']['a05.include_kegg']
        if not applicable:
            branch('GO与KEGG富集','not_applicable','本方案明确未纳入GO及KEGG，不启动统计')
            reasons['enrichment']='本方案未纳入GO及KEGG，不表示已计算后的零显著。'
            require(source_evidence is None,'未纳入富集的方案不能混入统计来源')
        elif m['current'].get('A05') and m['runs'][m['current']['A05']].get('result_file'):
            result=bound('A05','A05.plan_enrichment.1');enrichment=enrichment_source(home,source_evidence,result,plan,intake)
            state='technical_blocked' if result['outcome']=='failed' or result['summary'].get('handoff_blocked') else 'valid_empty' if result['outcome']=='empty' else 'completed'
            branch('GO与KEGG富集',state,'实际R统计按各自检验族及背景生成；未改变BH、显著阈值和完整原统计')
        else:
            branch('GO与KEGG富集','waiting','适用富集分支尚未完整归档');reasons['enrichment']='等待本批真实富集结果，不借用其他研究。'
        score=m['current'].get('A06');prep=m['current'].get('A06_PREP')
        score_current=bool(score and workflow.run(m,score)['parent_runs'].get('A06_PREP')==prep)
        module='A06' if score_current else 'A06_PREP' if prep else None
        if module and m['runs'][m['current'][module]].get('result_file'):
            result=add(module);run=runs[module];preparation_only=module=='A06_PREP'
            if not preparation_only:require(run['config'].get('version')=='A06.plan_scoring.1','当前评分不属于新方案评分协议')
            fixed_ref=input_reference(workflow,m,run);fixed=read_json(verified_file(home,fixed_ref))
            require(fixed_ref in m.get('analysis_plan_a06_input_records',[]) and fixed['study_id']==sid
                    and fixed['packet']['plan_ref']==reference and fixed['packet']['analysis_parameter_hash']==plan['parameter_hash'],
                    '报告固定对接名单不属于本批方案')
            for key,value in fixed['packet']['runs'].items():require(m['current'].get(key)==value,'对接固定名单的上游已改变')
            pairs=result['tables'].get('planned_pairs') if preparation_only else result['tables'].get('plan_scoring_pairs')
            packet={'study_id':sid,'run_id':run['run_id'],'compounds':fixed['packet']['compounds'],
                    'receptors':fixed['packet']['receptors'],'planned_pairs' if preparation_only else 'pairs':pairs}
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
    return {'schema_version':VERSION,'study_id':sid,'intake':intake,'plan':plan,'plan_source':deepcopy(reference),
            'counts':{'a01_genes':counts['A01'],'a02_genes':counts['A02'],'intersection':count},
            'run_ids':run_ids,'completion':state,'enrichment':enrichment,'docking':docking,'branch_reasons':reasons,
            'conclusion':conclusion,'network_summary':[description,model.BOUNDARY],
            'sources':sources,
            'research_leads':[],'validation_records':records,
            'references':method_references(run_ids),
            'source_evidence':deepcopy(source_evidence),'figure_source':None,'figures':[]}


def validate(payload,home,*,require_figures=False):
    """正式报告逐字段重建；有效系统回执不能授权篡改结论、评分或完成状态。"""
    from modulea.core.analysis_plans import AnalysisPlanWorkflow
    home=Path(home).resolve();workflow=AnalysisPlanWorkflow(home.parents[1]);sid=payload['study_id']
    require(workflow.location(sid).resolve()==home,'报告实际归档目录与研究不一致')
    expected=build(workflow,sid,source_evidence=payload.get('source_evidence'))
    value=deepcopy(payload)
    if payload.get('figure_source'):
        from .plan_figures import validate as validate_figures
        validate_figures(home,payload,expected);value['figures']=[];value['figure_source']=None
    else:require(not require_figures,'正式报告缺少同批图件，不能交付不完整报告')
    require(fingerprint(expected)==fingerprint(value),'报告事实、来源或结论与同批实际运行重建不一致')
    return expected
