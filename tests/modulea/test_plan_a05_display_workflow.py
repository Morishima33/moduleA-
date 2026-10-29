"""真实固定R只生成一次合成基线；每个展示测试复制隔离原件，展示阶段禁止再运行R。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from modulea.core import plan_a05_display as view
from modulea.core.kernel import full_workflow
from science_modules.a05 import plan_contract
from science_modules.a05.display import english
from storage import verified_file
from tests.modulea.test_plan_a05 import prepare,RSCRIPT
from tests.modulea import test_plan_creation_http as creation_http


class PlanA05DisplayWorkflowTests(unittest.TestCase):
    call=creation_http.PlanCreationHttpTests.call
    close=creation_http.PlanCreationHttpTests.close
    @classmethod
    def setUpClass(cls):
        """用真实R和原生产发布入口建立合成统计，后续不以模拟值代替科学基线。"""
        if not RSCRIPT.is_file():raise unittest.SkipTest('本机未配置固定Rscript，实际R基线测试未执行')
        cls.env=patch.dict(os.environ,{'MODULEA_RSCRIPT':str(RSCRIPT)});cls.env.start();cls.addClassCleanup(cls.env.stop)
        cls.seed=tempfile.TemporaryDirectory(prefix='a05_display_r_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.seed_root=Path(cls.seed.name);w,cls.sid,cls.draft=prepare(cls.seed_root)
        value=plan_contract.info(w,cls.sid)
        payload={key:value[key] for key in plan_contract.FIELDS-{'reason'}}|{'reason':'合成A05展示真实R基线'}
        w.publish_analysis_plan_a05(cls.sid,payload)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='a05_display_workflow_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);shutil.copytree(self.seed_root,self.root,dirs_exist_ok=True)
        self.w=full_workflow(self.root)
        self.no_r=patch('science_modules.a05.plan_flow.r_call',side_effect=AssertionError('展示阶段不能重算R'))
        self.no_r.start();self.addCleanup(self.no_r.stop)

    def body(self,**extra):
        """只携带当前服务端预期值和明确登记依据，不从客户端注入参数。"""
        value=view.info(self.w,self.sid)
        return dict({key:value[key] for key in ('expected_a05','expected_display_id','expected_input_hash')},
                    request_id='a05displayreq_'+uuid4().hex,author='隔离展示测试',note='只验证本批展示，不批准科学结果',confirmed=True,**extra)

    def create(self):
        return self.w.prepare_analysis_plan_a05_display(self.sid,self.body())

    def complete_decision(self):
        """合成未知通路留因暂缓；核译标签显式声明只是测试，不冒充正式中文名称。"""
        current=view.info(self.w,self.sid)['current'];source=json.loads(verified_file(self.w.location(self.sid),current['source']).read_text('utf8'))
        result=self.w.result(self.w.load(self.sid),current['a05_run_id'])
        rows={row['ID']:row for group in ('bp','cc','mf','kegg') for row in result['tables'][group+'_significant']}
        uncertain=[{'ID':key,'decision':'defer','reason':'合成分类待补，展示暂不纳入，原统计不改'} for key,value in source['assessments'].items() if value['classification_status']=='uncertain']
        translations=[{'ID':key,'english':english(row),'zh':'合成核译测试 '+key,'reason':'明确测试标签，非正式科学核译'} for key,row in rows.items()]
        return self.body(excluded_ids=[],uncertain_decisions=uncertain,translations=translations)

    def test_prepare_archives_sources_figures_and_never_changes_statistics(self):
        before=self.w.load(self.sid);rid=before['current']['A05'];original=deepcopy(self.w.result(before,rid))
        made=self.create();after=self.w.load(self.sid)
        self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews'])
        self.assertEqual(self.w.result(after,rid),original);self.assertEqual(len(made['figures']),8)
        value=view.info(self.w,self.sid);self.assertEqual(value['current']['display_id'],made['display_id'])
        self.assertFalse(value['current']['presentation']['ready_for_display'])
        self.assertFalse(value['current']['presentation']['scientific_approval'])
        self.assertEqual(len(after[view.REQUESTS]),1);self.assertEqual(len(after[view.INDEX]),1)

    def test_explicit_translations_and_deferral_generate_new_immutable_display(self):
        first=self.create();before=self.w.load(self.sid);request=self.complete_decision()
        second=self.w.confirm_analysis_plan_a05_display(self.sid,request);after=self.w.load(self.sid)
        self.assertNotEqual(first['display_id'],second['display_id']);self.assertEqual(len(after[view.INDEX]),2)
        p=second['presentation'];self.assertTrue(p['ready_for_display']);self.assertFalse(p['scientific_approval'])
        self.assertEqual(p['excluded_ids'],[]);self.assertTrue(p['deferred_ids'])
        self.assertEqual(before['current'],after['current']);self.assertEqual(before['reviews'],after['reviews'])
        svg=next(ref for ref in second['figures'] if ref['path'].endswith('KEGG_plan.svg'))
        text=verified_file(self.w.location(self.sid),svg).read_text('utf8')
        self.assertIn('本图因展示决定暂不列项',text);self.assertNotIn('本类无符合方案阈值的显著条目',text)
        previous=view.read_record(self.w,after,after[view.INDEX][0]);self.assertFalse(previous['presentation']['decisions_confirmed'])

    def test_exact_worker_retry_is_idempotent_and_changed_request_is_rejected(self):
        body=self.body();first=self.w.prepare_analysis_plan_a05_display(self.sid,body)
        self.assertEqual(self.w.prepare_analysis_plan_a05_display(self.sid,body),first)
        self.assertEqual(len(self.w.load(self.sid)[view.INDEX]),1)
        with self.assertRaises(ContractError):self.w.prepare_analysis_plan_a05_display(self.sid,dict(body,note='其他内容'))

    def test_source_corruption_and_old_input_decision_cannot_publish(self):
        self.create();old=self.complete_decision();self.w.confirm_analysis_plan_a05_display(self.sid,old)
        with self.assertRaises(ContractError):self.w.confirm_analysis_plan_a05_display(self.sid,old|{'request_id':'a05displayreq_'+uuid4().hex})
        current=view.info(self.w,self.sid)['current'];path=verified_file(self.w.location(self.sid),current['source_files'][0]);path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ContractError):view.info(self.w,self.sid)

    def test_new_draft_does_not_reinterpret_bound_statistical_parameters(self):
        value=view.info(self.w,self.sid);m=self.w.load(self.sid)
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':self.draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a05.go_table_top':25}},
            'author':'隔离展示测试','note':'仅后续批次新草稿'})
        current=view.info(self.w,self.sid);self.assertEqual(current['plan_id'],value['plan_id'])
        self.assertEqual(current['parameters']['go_table_top'],15)
        self.assertEqual(current['expected_input_hash'],value['expected_input_hash']);self.create()

    def test_review_change_blocks_new_display(self):
        old=self.body();m=self.w.load(self.sid);rid=m['current']['A03'];review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','隔离展示测试','撤回合成上游批准',review['review_id'])
        self.assertFalse(view.info(self.w,self.sid)['enabled'])
        with self.assertRaises(ContractError):self.w.prepare_analysis_plan_a05_display(self.sid,old)

    def start_http(self):
        """实际HTTP及独立worker使用不存在的Rscript，证明展示无需重算R。"""
        import threading
        from modulea.api.server import create_server
        from modulea.config import Settings
        self.settings=Settings(data_root=self.root,runtime_dir=self.root/'rt',science_rscript=self.root/'forbidden_Rscript.exe')
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.path=f'/studies/{self.sid}/analysis-plan/a05-display'

    def test_actual_http_worker_display_and_download_trace_without_r(self):
        import time,http.client,csv,io
        self.start_http();before=self.w.load(self.sid);body=self.body()
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value);self.assertIsNone(value['current'])
        status,value=self.call('POST',self.path+'/prepare',body);self.assertEqual(status,202,value)
        tid=value['task']['task_id'];deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            task=self.app.tasks.get(tid)
            if task['state'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',self.app.tasks.log(tid))
        status,value=self.call('GET',self.path);self.assertEqual(status,200,value)
        self.assertIsNotNone(value['current']);self.assertEqual(len(value['current']['downloads']),8)
        status,module=self.call('GET',f'/studies/{self.sid}/modules/A05');self.assertEqual(status,200,module)
        self.assertEqual(module['plan_a05_display']['current']['display_id'],value['current']['display_id'])
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=15)
        connection.request('GET',value['current']['downloads'][0]['url']);response=connection.getresponse();raw=response.read();connection.close()
        self.assertEqual(response.status,200);self.assertTrue(raw.startswith((b'\x89PNG',b'<svg')))
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['a05_display_records']),1)
        self.assertTrue(any(ref['role']=='a05_display_implementation' for ref in trace['files']))
        from modulea.core.trace_export import trace_csv
        rows=list(csv.DictReader(io.StringIO(trace_csv(trace).decode('utf-8-sig'))))
        self.assertTrue(any(row['table_name'].startswith('display.') for row in rows))
        self.assertTrue(any(row['table_name']=='kegg_significant' for row in rows))
        after=self.w.load(self.sid);self.assertEqual(after['current'],before['current']);self.assertEqual(after['reviews'],before['reviews'])

    def test_http_token_origin_fields_stale_trash_and_busy_are_enforced(self):
        self.start_http();body=self.body()
        self.assertEqual(self.call('POST',self.path+'/prepare',body,False)[0],403)
        self.assertEqual(self.call('POST',self.path+'/prepare',body,True,'https://untrusted.example')[0],403)
        for change in ({'confirmed':False},{'path':'injected'},{'approved':True}):
            with self.subTest(change=change):self.assertEqual(self.call('POST',self.path+'/prepare',body|change)[0],422)
        self.assertEqual(self.call('POST',self.path+'/prepare',body|{'expected_input_hash':'old'})[0],409)
        with patch.object(self.app.tasks,'active_for',return_value={'task_id':'synthetic_active'}):
            self.assertEqual(self.call('POST',self.path+'/prepare',body)[0],409)
        self.w.set_trashed(self.sid,True,'隔离展示测试','只读保护')
        self.assertEqual(self.call('POST',self.path+'/prepare',body)[0],423)
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def test_incomplete_new_a05_remains_readable_without_claiming_display(self):
        """新统计已begin但未finish时，网页仍可读取任务，不能把它当完整统计。"""
        self.start_http();m=self.w.load(self.sid);old=self.w.run(m,m['current']['A05'])
        pending=self.w.begin(self.sid,'A05',deepcopy(old['inputs']),deepcopy(old['config']),'合成未完成统计读取测试')
        status,value=self.call('GET',self.path)
        self.assertEqual(status,200,value);self.assertFalse(value['supported']);self.assertIsNone(value['current'])
        self.assertIsNone(self.app.views.module(self.sid,'A05')['plan_a05_display'])
        status,value=self.call('GET',f'/studies/{self.sid}/modules/A05')
        self.assertEqual(status,200,value);self.assertIsNone(value['plan_a05_display'])
        self.assertEqual(self.w.load(self.sid)['current']['A05'],pending['run_id'])
