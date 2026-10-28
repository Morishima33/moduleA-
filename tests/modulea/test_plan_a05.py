"""新方案A05真实固定R统计、参数生效、来源绑定和独立发布回归；仅合成资料。"""
from copy import deepcopy
import gzip
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from contracts import ContractError
from storage import file_record, write_json, verified_file
from modulea.config import Settings
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import full_workflow
from modulea.core import plan_a05
from modulea.api.server import create_server
from science_modules.analysis_protocol import compile_plan
from science_modules.a05 import plan_flow as engine
from science_modules.a05 import flow as old

RSCRIPT = Path(os.environ.get('MODULEA_RSCRIPT','D:/R/R-4.4.1/bin/x64/Rscript.exe'))


def annotations():
    """40基因背景、3个命中条目，保留大小边界与无命中条目供独立复算。"""
    terms=[{'id':'hsa00001','description':'Synthetic small set','genes':[str(i) for i in range(1,6)]},
           {'id':'hsa00002','description':'Synthetic first set','genes':[str(i) for i in range(1,11)]},
           {'id':'hsa00003','description':'Synthetic second set','genes':[str(i) for i in range(1,21)]},
           {'id':'hsa00004','description':'Synthetic background set','genes':[str(i) for i in range(11,41)]}]
    return {g:deepcopy(terms) for g in engine.GROUPS}


def source(plan):
    """合成来源使用真实字段形状，不宣称是官方注释或研究结论。"""
    ann={g:rows for g,rows in annotations().items() if g in engine.groups(plan)}
    kegg={}
    if 'KEGG' in ann:
        kegg={'names':{'response_text':''.join(r['id']+'\t'+r['description']+'\n' for r in ann['KEGG'])},
              'links':{'response_text':''.join('hsa:'+gid+'\tpath:'+r['id']+'\n' for r in ann['KEGG'] for gid in r['genes'])}}
        ann['KEGG']=engine.legacy.kegg_terms(kegg)
    return {'schema_version':engine.SOURCE_VERSION,'config':engine.legacy.CONFIG,'annotations':ann,
            'metadata':{'synthetic_fixture':True},'kegg_sources':kegg,'export_log':'synthetic annotation fixture'}


def prepare(root, **parameters):
    """公开Workflow建立独立合成上游及草稿，原始注释固定到测试数据根。"""
    w=AnalysisPlanWorkflow(root,{'A05':engine.validator(root,lambda *args:None)})
    sid=w.create({'formula':'隔离富集测试方','herbs':'合成药','disease':'合成病','disease_scope':'仅本病',
                  'species':9606,'operator':'隔离测试','analysis_purpose':'workflow_test',
                  'analysis_plan_profile':'ModuleA.analysis_plan.1'},kind='contract_test')
    a00=w.load(sid)['current']['A00'];w.review(sid,a00,'approved','隔离测试','仅合成登记')
    draft=w.save_analysis_plan_draft(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':a00,'expected_draft_id':'',
        'specification':{'mode':'personalized' if parameters else 'standard','parameters':parameters},'author':'隔离测试','note':'合成测试方案'})['draft']
    raw=('hgnc_id\tsymbol\tentrez_id\n'+''.join(f'HGNC:{i}\tG{i}\t{i}\n' for i in range(1,6))).encode()
    home=w.location(sid);path=home/'raw/hgnc.tsv';path.write_bytes(raw);mapping=file_record(home,path,'mapping_source')
    a01=w.begin(sid,'A01',{'mapping_file':mapping,'analysis_plan_id':draft['plan_id']},{},'合成测试上游')
    w.finish(sid,a01['run_id'],{'mapping_snapshot':mapping['sha256']},{})
    w.review(sid,a01['run_id'],'approved','隔离测试','仅合成A01')
    a02=w.begin(sid,'A02',{}, {},'合成测试疾病侧');w.finish(sid,a02['run_id'],{}, {})
    w.review(sid,a02['run_id'],'approved','隔离测试','仅合成A02')
    a03=w.begin(sid,'A03',{}, {},'合成测试交集')
    w.finish(sid,a03['run_id'],{'analysis_purpose':'workflow_test'},
             {'intersection_targets':[{'target_id':f'HGNC:{i}','symbol':f'G{i}'} for i in range(1,6)]})
    w.review(sid,a03['run_id'],'approved','隔离测试','仅合成交集')
    install_source(root,draft['plan'])
    return w,sid,draft


def install_source(root,plan):
    """源包按内容指纹寻址，测试不联网导出真实GO/KEGG。"""
    raw=gzip.compress(json.dumps(source(plan),ensure_ascii=False).encode(),mtime=0)
    path=Path(root)/'references'/('fixture_'+hashlib.sha256(raw).hexdigest()+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    write_json(Path(root)/'environments'/('A05_plan_sources_'+'_'.join(engine.groups(plan))+'.json'),file_record(Path(root),path,'annotation_source'))


class PlanA05Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='plan_a05_');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'MODULEA_RSCRIPT':str(RSCRIPT)});self.env.start();self.addCleanup(self.env.stop)
        self.w,self.sid,self.draft=prepare(self.root)

    def payload(self):
        value=plan_a05.info(self.w,self.sid)
        return {k:value[k] for k in plan_a05.FIELDS-{'reason'}}|{'reason':'隔离合成富集验证'}

    def test_default_statistics_match_frozen_r_and_independent_probability(self):
        plan=compile_plan({'mode':'standard'})
        targets=[{'target_id':f'HGNC:{i}','symbol':f'G{i}'} for i in range(1,6)]
        raw=('hgnc_id\tsymbol\tentrez_id\n'+''.join(f'HGNC:{i}\tG{i}\t{i}\n' for i in range(1,6))).encode()
        summary,tables,_=engine.evaluate(self.root,targets,source(plan),raw,'workflow_test',plan)
        _,previous,_=old.evaluate(self.root,targets,source(plan),raw,'workflow_test')
        for group in engine.GROUPS:
            for key in ('all','significant','background','effective','missing'):
                self.assertEqual(tables[group.lower()+'_'+key],previous[group.lower()+'_'+key])
        row=next(r for r in tables['bp_all'] if r['ID']=='hsa00002')
        self.assertAlmostEqual(row['pvalue'],math.comb(10,5)/math.comb(40,5),places=12)
        self.assertEqual(row['GeneRatio'],'5/5');self.assertEqual(row['BgRatio'],'10/40')
        self.assertEqual(len(tables['bp_all']),2)

    def test_real_custom_parameters_go_only_size_threshold_and_display(self):
        plan=compile_plan({'mode':'personalized','parameters':{'a05.include_kegg':False,'a05.min_term_size':1,
            'a05.max_term_size':10,'a05.adjusted_p_max':.0001,'a05.go_plot_top':10,'a05.go_table_top':20}})
        value={'genes':['1','2','3','4','5','999'],'annotations':source(plan)['annotations'],'parameters':engine.parameters(plan)}
        result,_=engine.r_call(self.root,'analyze',value)
        self.assertEqual(set(result),{'BP','CC','MF'})
        self.assertEqual({r['ID'] for r in result['BP']['all']},{'hsa00001','hsa00002'})
        self.assertEqual([r['ID'] for r in result['BP']['significant']],['hsa00001'])
        self.assertEqual(result['BP']['missing'],'999')

    def test_kegg_only_and_empty_input_are_valid_not_failure(self):
        plan=compile_plan({'mode':'personalized','parameters':{'a05.include_go':False}})
        result,_=engine.r_call(self.root,'analyze',{'genes':['999'],'annotations':source(plan)['annotations'],'parameters':engine.parameters(plan)})
        self.assertEqual(set(result),{'KEGG'});self.assertEqual(result['KEGG']['all'],[])

    def test_both_disabled_is_not_applicable_and_never_runs_r(self):
        body=self.payload()
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':body['expected_a00'],
            'expected_draft_id':self.draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a05.include_go':False,'a05.include_kegg':False}},'author':'隔离测试','note':'合法不纳入富集方案'})
        value=plan_a05.info(self.w,self.sid)
        self.assertFalse(value['applicable']);self.assertFalse(value['enabled'])
        with patch.object(engine,'r_call',side_effect=AssertionError('不应执行')):
            with self.assertRaisesRegex(ContractError,'富集不适用'):self.w.publish_analysis_plan_a05(self.sid,self.payload())

    def test_actual_r_keeps_distinct_plot_and_table_counts(self):
        plan=compile_plan({'mode':'personalized','parameters':{'a05.include_kegg':False,'a05.go_plot_top':10,'a05.go_table_top':20}})
        ann={g:[{'id':f'T{i:02}','description':f'Synthetic term {i}','genes':[str(x) for x in range(1,11)]} for i in range(22)] +
              [{'id':'U','description':'background','genes':[str(x) for x in range(11,41)]}] for g in ('BP','CC','MF')}
        data=source(plan);data['annotations']=ann
        raw=('hgnc_id\tsymbol\tentrez_id\n'+''.join(f'HGNC:{i}\tG{i}\t{i}\n' for i in range(1,6))).encode()
        _,tables,_=engine.evaluate(self.root,[{'target_id':f'HGNC:{i}','symbol':f'G{i}'} for i in range(1,6)],data,raw,'workflow_test',plan)
        self.assertEqual((len(tables['bp_all']),len(tables['bp_significant']),len(tables['bp_display']),len(tables['bp_plan_top'])),(22,22,10,20))
        self.assertIsNone(next(r for r in tables['group_summary'] if r['group']=='KEGG')['significant_count'])

    def test_r_failure_does_not_publish_an_empty_run(self):
        before=self.w.load(self.sid)
        with patch.object(engine,'r_call',side_effect=ContractError('固定R版本不符')):
            with self.assertRaises(ContractError):self.w.publish_analysis_plan_a05(self.sid,self.payload())
        self.assertEqual(before['current'],self.w.load(self.sid)['current'])
        self.assertEqual(before['reviews'],self.w.load(self.sid)['reviews'])

    def test_empty_significance_publication_keeps_complete_statistics(self):
        body=self.payload()
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':body['expected_a00'],
            'expected_draft_id':self.draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a05.adjusted_p_max':1e-12}},'author':'隔离测试','note':'严格阈值的正常空结果'})
        result=self.w.publish_analysis_plan_a05(self.sid,self.payload())
        self.assertEqual(result['outcome'],'empty')
        self.assertEqual(len(result['tables']['bp_all']),2)
        self.assertEqual(result['tables']['bp_significant'],[])
        self.assertEqual(len(result['tables']['bp_background']),40)

    def test_failed_r_keeps_full_input_and_log_for_explicit_retry(self):
        with patch.object(engine.subprocess,'run',return_value=Mock(returncode=1,stdout=b'full output',stderr=b'failure detail')):
            with self.assertRaisesRegex(ContractError,'完整输入与诊断'):
                engine.r_call(self.root,'analyze',{'synthetic':'input'})
        attempts=list((self.root/'environments/A05_plan_failures').iterdir())
        self.assertEqual(len(attempts),1)
        self.assertEqual(json.loads((attempts[0]/'input.json').read_text('utf8')),{'synthetic':'input'})
        self.assertEqual((attempts[0]/'R_log.txt').read_text('utf8'),'full outputfailure detail')

    def test_upstream_review_change_during_compute_cannot_publish(self):
        body=self.payload();call=engine.r_call;changed=[]
        def compute(root,mode,value):
            result=call(root,mode,value)
            if not changed:
                m=self.w.load(self.sid);rid=body['expected_a03'];review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
                changed.append(self.w.review(self.sid,rid,'pending','隔离测试','撤回测试上游',review['review_id']))
            return result
        with patch.object(engine,'r_call',side_effect=compute),self.assertRaises(ContractError):
            self.w.publish_analysis_plan_a05(self.sid,body)
        self.assertNotIn('A05',self.w.load(self.sid)['current'])

    def test_publication_is_bound_and_preserves_upstream_reviews_and_history(self):
        before=self.w.load(self.sid);body=self.payload()
        result=self.w.publish_analysis_plan_a05(self.sid,body)
        after=self.w.load(self.sid)
        self.assertEqual(before['reviews'],after['reviews']);self.assertNotIn('A07',after['current'])
        self.assertEqual(result['summary']['analysis_parameter_hash'],self.draft['plan']['parameter_hash'])
        self.assertTrue(plan_a05.info(self.w,self.sid)['completed'])
        with self.assertRaises(ContractError):self.w.publish_analysis_plan_a05(self.sid,self.payload())
        self.assertFalse(self.w.approved(after,result['run_id']))
        from modulea.api.server import App
        from modulea.api.errors import ApiError
        from types import SimpleNamespace
        app=App(Settings(data_root=self.root,runtime_dir=self.root/'rt'))
        with self.assertRaises(ApiError):app.post_continue(SimpleNamespace(),self.sid)
        with self.assertRaisesRegex(ContractError,'报告协议'):
            self.w.begin(self.sid,'A07',{}, {},'不能套用旧报告')
        check=full_workflow(self.root).validators['A05'];run=self.w.run(after,result['run_id'])
        bad=deepcopy(result['tables']);bad['bp_all'][0]['Count']=True
        with self.assertRaises(ContractError):check(run,result['summary'],bad,result['anomalies'],result['outcome'])
        script=verified_file(self.w.location(self.sid),run['inputs']['execution_script']);script.write_bytes(script.read_bytes()+b'\n# tampered')
        with self.assertRaises(ContractError):check(run,result['summary'],result['tables'],result['anomalies'],result['outcome'])

    def test_stale_hidden_unapproved_and_upstream_parameter_change_rejected(self):
        body=self.payload()
        for changes in ({'adjusted_p_max':1},{'expected_a03':'run_'+'0'*32},{'expected_plan_id':'plan_'+'0'*32}):
            with self.assertRaises(ContractError):plan_a05.validate(self.w,self.sid,dict(body,**changes))
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':body['expected_a00'],
            'expected_draft_id':self.draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':15}},'author':'隔离测试','note':'上游改变'})
        self.assertFalse(plan_a05.info(self.w,self.sid)['enabled'])
        self.assertIn('A01门槛',''.join(plan_a05.info(self.w,self.sid)['blockers']))

    def test_new_draft_during_computation_keeps_original_batch_parameters(self):
        body=self.payload();original=self.draft;changed=[];call=engine.r_call
        def compute(root,mode,value):
            if not changed:
                changed.append(self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,
                    'expected_a00':body['expected_a00'],'expected_draft_id':original['plan_id'],
                    'specification':{'mode':'personalized','parameters':{'a05.adjusted_p_max':.000001}},'author':'隔离测试','note':'运行中追加草稿'})['draft'])
            return call(root,mode,value)
        with patch.object(engine,'r_call',side_effect=compute):result=self.w.publish_analysis_plan_a05(self.sid,body)
        self.assertEqual(result['summary']['analysis_parameter_hash'],original['plan']['parameter_hash'])
        self.assertNotEqual(original['plan_id'],changed[0]['plan_id'])

    def test_go_only_source_acquisition_never_requests_kegg(self):
        plan=compile_plan({'mode':'personalized','parameters':{'a05.include_kegg':False}})
        with patch.object(engine,'r_call',return_value=({'annotations':source(plan)['annotations'],'metadata':{'synthetic_fixture':True}},'fixture')), \
             patch.object(engine.legacy,'download',side_effect=AssertionError('GO-only不得访问KEGG')):
            ref=engine.source_snapshot(self.root,plan)
        self.assertEqual(set(engine.read_source(verified_file(self.root,ref),plan)['annotations']),{'BP','CC','MF'})

    def test_interface_imports_without_scientific_site_packages(self):
        program='import sys;sys.path.insert(0,sys.argv[1]);from modulea.api.server import App;from modulea.config import Settings;from pathlib import Path;from modulea.core.plan_a05 import info;print(info(App(Settings(data_root=Path(sys.argv[2]),runtime_dir=Path(sys.argv[2])/"rt")).kernel.workflow(),sys.argv[3])["supported"])'
        p=subprocess.run([sys.executable,'-I','-S','-B','-c',program,str(Path(__file__).resolve().parents[2]/'src'),str(self.root),self.sid],capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('True',p.stdout)


class PlanA05HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='plan_a05_http_');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.w,self.sid,self.draft=prepare(self.root/'data')
        self.settings=Settings(data_root=self.root/'data',runtime_dir=self.root/'rt',science_rscript=RSCRIPT)
        self.server,self.app=create_server(self.settings,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def call(self,method,body=None,token=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        headers={'Content-Type':'application/json'}
        if token:headers['X-ModuleA-Token']=self.app.token
        if origin:headers['Origin']=origin
        try:
            c.request(method,'/api/v1/studies/'+self.sid+'/analysis-plan/a05',json.dumps(body) if body else None,headers)
            r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def payload(self):
        value=plan_a05.info(self.w,self.sid)
        return {k:value[k] for k in plan_a05.FIELDS-{'reason'}}|{'reason':'真实HTTP合成资料验证'}
    def test_security_missing_tools_and_busy_never_submit(self):
        body=self.payload()
        self.assertEqual(self.call('POST',body,False)[0],403)
        self.assertEqual(self.call('POST',body,origin='https://invalid.example')[0],403)
        self.assertEqual(self.call('POST',dict(body,path='override'))[0],422)
        self.assertEqual(self.call('POST',dict(body,expected_plan_id='plan_'+'0'*32))[0],409)
        with patch.object(self.app.tasks,'submit') as submit:
            self.settings.science_rscript=self.root/'missing.exe'
            self.assertFalse(self.call('GET')[1]['enabled']);self.assertEqual(self.call('POST',body)[0],409);submit.assert_not_called()
        self.settings.science_rscript=RSCRIPT
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'task_busy'}):self.assertFalse(self.call('GET')[1]['enabled'])
    def test_fixed_r_path_is_loaded_from_server_configuration(self):
        from modulea.config import load_settings
        with patch('modulea.config._read_local_toml',return_value={'paths':{'science_rscript':str(RSCRIPT)}}),patch.dict(os.environ,{'MODULEA_RSCRIPT':str(RSCRIPT)}):
            value=load_settings(data_root=self.root/'data',runtime_dir=self.root/'test_runtime')
        self.assertEqual(value.science_rscript,RSCRIPT)
        self.assertEqual(list(Settings.__dataclass_fields__)[4],'science_tools_root')

    def test_real_task_subprocess_and_result_readback(self):
        before=self.w.load(self.sid)
        status,value=self.call('POST',self.payload());self.assertEqual(status,202,value)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            task=self.app.tasks.get(value['task']['task_id'])
            if task['state'] not in ('queued','running'):break
            time.sleep(.2)
        self.assertEqual(task['state'],'succeeded',task)
        m=self.w.load(self.sid);result=self.w.result(m,m['current']['A05'])
        self.assertEqual(result['summary']['protocol_version'],engine.VERSION)
        self.assertEqual(m['reviews'],before['reviews']);self.assertNotIn('A07',m['current'])
        self.assertTrue(self.call('GET')[1]['completed']);self.assertEqual(self.call('POST',self.payload())[0],409)


if __name__=='__main__':unittest.main()
