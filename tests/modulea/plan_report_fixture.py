"""报告全链的真实上游构建器：合成三库/五库原件，所有当前结果经生产验证器生成。"""
from pathlib import Path
import gzip,hashlib,json
from uuid import uuid4
from modulea.core.kernel import full_workflow
from science_modules.a01 import uploads
from science_modules import plan_stages_contract as stages
from disease import DATABASES,run_disease
from science_modules.a02.plan_normalization import preview,publish
from tests.modulea.test_plan_a01_publication import source_package


def prepare(root,*,empty=False,stop_before_normalization=False):
    """既有科学发布、明确测试复核和新方案交集；不使用假validator/直接改manifest。"""
    root=Path(root);refs=root/'references';refs.mkdir(parents=True)
    hgnc=('hgnc_id\tsymbol\tstatus\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\tentrez_id\n'+
          ''.join(f'HGNC:{i}\t{symbol}\tApproved\t\t\tENSG{i}\tP{i}\t{i}\n' for i,symbol in enumerate('ABC',1))).encode()
    files={'hgnc_complete_set_20260913.tsv':hgnc,
           'ncbi_human_gene_info_20260913.gz':gzip.compress(('#tax_id\tGeneID\tSymbol\tSymbol_from_nomenclature_authority\tSynonyms\tdbXrefs\ttype_of_gene\n'+
               ''.join(f'9606\t{i}\t{symbol}\t{symbol}\t-\tHGNC:HGNC:{i}\tprotein-coding\n' for i,symbol in enumerate('ABC',1))).encode()),
           'ncbi_human_gene_history_20260913.tsv':b'#tax_id\tGeneID\tDiscontinued_GeneID\tDiscontinued_Symbol\tDiscontinue_Date\n',
           'identity_queries_20260913_v3.json':b'{}'}
    for name,content in files.items():
        (refs/name).write_bytes(content)
        meta='identity_queries_20260913_v3_manifest.json' if name.endswith('.json') else Path(name).with_suffix('.json').name
        (refs/meta).write_text(json.dumps({'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),
            'source_url':'explicit_synthetic_fixture'}),encoding='utf8')
    w=full_workflow(root)
    sid=w.create({'formula':'全链合成方','herbs':'测试药','disease':'COPD','disease_scope':'仅本病',
        'operator':'隔离上游测试','species':9606,'analysis_purpose':'workflow_test',
        'analysis_plan_profile':'ModuleA.analysis_plan.1'},kind='contract_test')
    a00=w.load(sid)['current']['A00'];w.review(sid,a00,'approved','明确合成测试复核','仅测试，不代表用户或正式研究复核')
    draft=w.save_analysis_plan_draft(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_draft_id':'',
        'specification':{'mode':'standard'},'author':'隔离上游测试','note':'同研究全链原件测试'})['draft']
    for database in uploads.DATABASES:
        m=w.load(sid)
        uploads.stage(w,sid,a00,m['current'].get('A01',''),(m.get('current_component_uploads') or {}).get('sha256',''),
            {'database':database,'format':'source_zip','version':'explicit_synthetic_fixture','data':source_package(database)},root/'parse')
    m=w.load(sid);a01=w.publish_analysis_plan_a01(sid,{'expected_a00':a00,'expected_a01':'',
        'expected_plan_id':draft['plan_id'],'expected_staging':m['current_component_uploads']['sha256'],'reason':'实际三库及HGNC合成发布'})
    w.review(sid,a01['run_id'],'approved','明确合成测试复核','仅对隔离三库结果测试')
    content=('raw_symbol\tdisease_term\n'+('B' if empty else 'A')+'\tCOPD\n').encode()
    base={'format':'tsv','query':'COPD','retrieved_at':'2026-10-29','version':'explicit_synthetic_fixture',
          'source_url':'explicit_synthetic_fixture','name':'synthetic_disease.tsv','encoding':'utf-8-sig','data':content}
    run_disease(w,sid,a00,'',[dict(base,database=database) for database in DATABASES],'实际五库合成候选')
    if stop_before_normalization:return w,sid,draft,None
    data=preview(w,sid);normalized=publish(w,sid,data[-1],'明确合成测试复核','明确采用本病合成范围，无身份例外',True,False)
    assert normalized['A01']['run_id']==a01['run_id'],'疾病标准化不应替换已核对且同映射的新版A01'
    w.review(sid,normalized['A02']['run_id'],'approved','明确合成测试复核','仅测试五库标准化')
    info=stages.info(w,sid)
    body={key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|{
        'stage':'A03','operator':'隔离上游测试','reason':'同批真实科学交集，不写人工签名','confirmed':True}
    result=w.execute_analysis_plan_stage(sid,body)
    return w,sid,draft,result
