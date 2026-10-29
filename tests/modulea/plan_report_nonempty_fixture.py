"""同研究现代建档非空全链夹具：外部响应明确合成，发布与规范校验真实执行。"""
import json,os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from storage import file_record,write_json
from tests.modulea import plan_report_fixture as upstream
from tests.modulea import test_plan_a05 as enrichment_fixture
from modulea.core import plan_compounds,plan_a05,system_validation,plan_reports
from science_modules import plan_stages_contract as stages
from science_modules.a04 import plan_flow as network
from science_modules.a06 import plan_preparation_v2 as preparation


def string_response(method,params,opener=None):
    """合成五星网络，仍执行真实置信度筛选、网络和受体选择规则。"""
    if method=='get_string_ids':
        rows=[{'queryIndex':i,'ncbiTaxonId':9606,'preferredName':symbol,'stringId':f'9606.{i+1}'} for i,symbol in enumerate(params['identifiers'].split('\r'))]
    else:
        rows=[{'stringId_A':'9606.1','stringId_B':f'9606.{i}','score':.95,'ncbiTaxonId':9606} for i in range(2,6)]
    return {'url':network.BASE+method,'params':params,'response_text':json.dumps(rows),'method':method}


def unavailable_sources(home,packet,folder,progress):
    """合成结构不可用响应有独立证据，不能当作真实官方请求或成功准备。"""
    folder.mkdir(parents=True,exist_ok=False);path=folder/'explicit_synthetic_failure.json'
    write_json(path,{'synthetic':True,'real_official_request_performed':False,'reason':'明确合成结构不可用'})
    return {'id':'explicit_synthetic_unavailable','files':[file_record(home,path,'source_failure_evidence')],
        'compounds':[{**row,'state':'NA','reason_zh':'明确合成来源不可用，不猜补结构'} for row in packet['compounds']],
        'receptors':[{**row,'state':'NA','reason_zh':'明确合成来源不可用，不换低排名受体','candidates':[]} for row in packet['receptors']]}


def prepare(root,tools,rscript):
    """一份公开建档研究完整执行三库/五库、PPI、真实R、全NA准备和生产双报告。"""
    root=Path(root)
    w,sid,draft,_=upstream.prepare(root,modern=True,multiple_targets=True,specification={
        'mode':'personalized','parameters':{'a06.component_count':2,'a06.receptor_count':2}})
    def review(rid):
        """仅明确合成测试的真实审核记录，不冒充用户或专家，不用于自动编排放行。"""
        w.review(sid,rid,'approved','明确合成全链测试复核','仅合成技术验证，不代表用户或正式研究复核')
    m=w.load(sid);a00=m['current']['A00'];a03=m['current']['A03'];pid=draft['plan_id'];review(a03)
    value=plan_compounds.info(w,sid)
    compounds=w.publish_analysis_plan_compounds(sid,{key:value[key] for key in ('expected_a00','expected_a03','expected_selection','expected_plan_id','expected_input_hash')}|
        {'operator':'明确合成全链测试','reason':'同批完整成分名单','confirmed':True});review(compounds['run_id'])
    value=stages.info(w,sid)
    with patch.object(network,'request',side_effect=string_response):
        ppi=w.execute_analysis_plan_stage(sid,{key:value[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')}|
            {'stage':'A04','operator':'明确合成全链测试','reason':'合成外部响应，真实网络计算','confirmed':True})
    review(ppi['run_id']);enrichment_fixture.install_source(root,draft['plan']);value=plan_a05.info(w,sid)
    with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(rscript)}):
        ora=w.publish_analysis_plan_a05(sid,{key:value[key] for key in plan_a05.FIELDS-{'reason'}}|{'reason':'合成注释，真实固定R统计及独立复算'})
    review(ora['run_id'])
    selection=w.save_analysis_plan_a04_selection(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_a04':ppi['run_id'],
        'expected_plan_id':pid,'author':'明确合成全链测试','note':'实际原网络选择'})['record']
    selection_review=w.review_analysis_plan_a04_selection(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_a04':ppi['run_id'],
        'selection_id':selection['selection_id'],'expected_review_id':None,'decision':'approved','reviewer':'明确合成全链测试复核','note':'仅测试受体名单'})['review']
    fixed=w.save_analysis_plan_a06_preparation_input(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_a03':a03,
        'expected_a03_select':compounds['run_id'],'expected_a04':ppi['run_id'],'expected_selection_id':selection['selection_id'],
        'expected_selection_review_id':selection_review['review_id'],'expected_plan_id':pid,'author':'明确合成全链测试','note':'保留实际不足名单，不用低排名对象补位'})['record']
    with patch.object(preparation,'connect',side_effect=unavailable_sources):
        preparation.run(w,sid,{'request_id':'planprep_'+uuid4().hex,'expected_input_id':fixed['input_id'],'author':'明确合成全链测试',
            'note':'真实Vina版本核对；合成结构NA，不运行评分','confirmed':True},Path(tools),lambda _:None)
    with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(rscript)}):
        for rid in w.load(sid)['current'].values():
            expected=system_validation.request(w,sid,rid)
            result=w.validate_analysis_plan_scientific_run(sid,{key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
            assert result['passed'],result
    before=w.load(sid);value=plan_reports.info(w,sid);assert value['enabled'],value
    from science_modules.a05 import plan_flow as enrichment
    # 报告必须消费原统计，任何重新执行R都视为测试失败。
    with patch.object(enrichment,'r_call',side_effect=AssertionError('报告不得重算R')):
        result=w.publish_analysis_plan_report(sid,{key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|{
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成全链测试','note':'同一研究的实际非空结果与完整NA报告','confirmed':True})
    return w,sid,before,result
