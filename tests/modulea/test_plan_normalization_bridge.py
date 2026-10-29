"""新版三库至疾病标准化真实衔接：保留A01参数与多源结果，旧入口继续按原规则。"""
from pathlib import Path
import hashlib,json,tempfile,threading,time,unittest
from types import SimpleNamespace
from contracts import ContractError
from disease import run_disease
from modulea.core import normalization_bridge as bridge
from science_modules.a02 import plan_normalization as science
from tests.modulea.plan_report_fixture import prepare
from tests.modulea import test_plan_creation_http as http_fixture


class PlanNormalizationBridgeTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_disease_normalization_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.w,self.sid,self.draft,_=prepare(self.root,stop_before_normalization=True)
        m=self.w.load(self.sid);r=self.w.result(m,m['current']['A02'])
        decisions=[dict(scope_id=row['scope_id'],scope='direct',reviewer='明确合成测试复核',note='全部为合成本病直接来源') for row in r['tables']['scope_groups']]
        run_disease(self.w,self.sid,m['current']['A00'],r['run_id'],[],'明确合成范围决定',scope_change=decisions)
        self.settings=SimpleNamespace(runtime_dir=self.root/'runtime')

    def body(self,action='preview',**extra):
        """只用原接口当前绑定，不向服务端提供名单或科学参数。"""
        return dict(bridge.bindings(self.w.load(self.sid)),action=action,**extra)

    def test_public_bridge_preserves_a01_and_only_publishes_disease(self):
        before=self.w.load(self.sid);rid=before['current']['A01'];old=self.w.result(before,rid)
        _,preview=bridge.execute(self.settings,self.w,self.sid,self.body())
        projected=next(row for row in preview['modules'] if row['module']=='A01');self.assertEqual(projected['summary'],old['summary'])
        message,made=bridge.execute(self.settings,self.w,self.sid,self.body('publish',stamp=preview['stamp'],reviewer='明确合成测试复核',
            note='明确合成疾病标准化',confirmed=True,accept_omit=False,accept_source_exception=False))
        after=self.w.load(self.sid);self.assertIn('A01原结果',message)
        self.assertEqual(made['A01'],old);self.assertEqual(after['current']['A01'],rid);self.assertEqual(after['runs'][rid],before['runs'][rid])
        self.assertEqual(after['reviews'],before['reviews']);self.assertNotEqual(after['current']['A02'],before['current']['A02'])
        self.assertFalse(self.w.approved(after,after['current']['A02']));self.assertNotIn('A03',after['current'])

    def test_withdrawn_a01_and_changed_mapping_cannot_reuse_old_result(self):
        m=self.w.load(self.sid);rid=m['current']['A01'];review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试复核','撤回测试批准',review['review_id'])
        current=self.w.load(self.sid);result=self.w.result(current,current['current']['A02'])
        self.assertFalse(bridge.context(self.w,current,result,self.settings)['enabled'])
        with self.assertRaises(ContractError):bridge.execute(self.settings,self.w,self.sid,self.body())
        self.assertEqual(self.w.load(self.sid),current)

    def test_changed_mapping_snapshot_requires_new_a01_publication(self):
        path=self.root/'references/hgnc_complete_set_20260913.tsv';content=path.read_bytes()+b'\n';path.write_bytes(content)
        meta=self.root/'references/hgnc_complete_set_20260913.json';data=json.loads(meta.read_text('utf8'))
        data.update(sha256=hashlib.sha256(content).hexdigest(),bytes=len(content));meta.write_text(json.dumps(data),encoding='utf8')
        before=self.w.load(self.sid)
        with self.assertRaisesRegex(ContractError,'重新发布A01'):science.preview(self.w,self.sid)
        self.assertEqual(self.w.load(self.sid),before)

    def test_actual_http_worker_preview_publish_and_no_a01_replacement(self):
        """复现原来真实任务会报字段错误的入口，验证两项独立worker实际完成。"""
        from modulea.api.server import create_server
        from modulea.config import Settings
        self.server,self.app=create_server(Settings(data_root=self.root,runtime_dir=self.root/'http_rt'),0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        path=f'/studies/{self.sid}/modules/A02/actions/normalization';before=self.w.load(self.sid)
        def submit(body):
            """等待实际终态，不把受理当科学发布成功。"""
            status,value=self.call('POST',path,body);self.assertEqual(status,202,value);tid=value['task']['task_id']
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                task=self.app.tasks.get(tid)
                if task['state'] not in ('queued','running'):break
                time.sleep(.1)
            self.assertEqual(task['state'],'succeeded',self.app.tasks.log(tid))
        submit(self.body());status,value=self.call('GET',f'/studies/{self.sid}/modules/A02');self.assertEqual(status,200,value)
        preview=value['normalization']['preview'];self.assertIsNotNone(preview)
        submit(self.body('publish',stamp=preview['stamp'],reviewer='明确合成测试复核',note='实际HTTP原入口',confirmed=True,accept_omit=False,accept_source_exception=False))
        after=self.w.load(self.sid);self.assertEqual(after['reviews'],before['reviews']);self.assertEqual(after['current']['A01'],before['current']['A01'])
        self.assertIn('标准化基因数',self.w.result(after,after['current']['A02'])['summary'])
