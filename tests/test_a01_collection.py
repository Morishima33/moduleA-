"""三库新协议验收：完整性门控、真实问题决定及A02版本保护。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contracts import ContractError
from science_modules.a01 import collection_flow as flow
from science_modules.a01.uploads import stage
from test_source_uploads import fixture, package


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.w, self.sid, self.a00 = fixture(self.root)
        self.w.validators["A01"] = flow.validator(self.root, self.w.validators["A01"])
        self.before = self.w.load(self.sid)["current"]["A02"]
        for db in ("TCMSP", "HERB", "BATMAN"):
            self.upload(db)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, db, gene="A"):
        m = self.w.load(self.sid)
        stage(self.w, self.sid, self.a00, m["current"].get("A01", ""), (m.get("current_component_uploads") or {}).get("sha256", ""),
              {"database": db, "format": "source_zip", "name": db + ".zip", "data": package(db, gene)}, self.root / "temp")

    def process(self, decision=None):
        m = self.w.load(self.sid)
        return flow.process(self.w, self.sid, self.a00, m["current"].get("A01", ""), m["current_component_uploads"]["sha256"], "test", decision)

    def decision(self, **extra):
        return dict(confirmed=True, reviewer="test", note="已逐项核对合成原件", confirm_coverage=True, omit_unresolved=False, **extra)

    def test_uploaded_without_completeness_blocks_but_never_changes_a02(self):
        r = self.process()
        self.assertTrue(r["summary"]["handoff_blocked"])
        self.assertEqual(r["summary"]["完整性待核项数"], 3)
        with self.assertRaises(ContractError):
            self.w.review(self.sid, r["run_id"], "approved", "test", "不能跳过")
        self.assertEqual(self.w.load(self.sid)["current"]["A02"], self.before)

    def test_explicit_confirmation_keeps_independent_review_and_history(self):
        first = self.process()
        r = self.process(self.decision())
        self.assertFalse(r["summary"]["handoff_blocked"])
        self.assertFalse(self.w.approved(self.w.load(self.sid), r["run_id"]))
        self.assertEqual(self.w.result(self.w.load(self.sid), first["run_id"])["summary"]["完整性待核项数"], 3)
        self.assertEqual(self.w.load(self.sid)["current"]["A02"], self.before)

    def test_unknown_relation_requires_separate_explicit_omission(self):
        self.upload("HERB", "UNKNOWN")
        self.process()
        r = self.process(self.decision())
        self.assertTrue(r["summary"]["handoff_blocked"])
        p = self.decision()
        p.update(confirm_coverage=False, omit_unresolved=True)
        r = self.process(p)
        self.assertFalse(r["summary"]["handoff_blocked"])
        self.assertEqual(r["summary"]["明确暂不采用身份组数"], 1)
        self.assertEqual(len(r["tables"]["identity_issues"]), 1)

    def test_source_replacement_invalidates_prior_decision(self):
        self.process()
        self.upload("HERB")
        with self.assertRaises(ContractError):
            self.process(self.decision())

    def test_new_a01_invalidates_dependent_intersection_but_keeps_a02_approved(self):
        self.process()
        result = self.process(self.decision())
        self.w.review(self.sid, result['run_id'], 'approved', 'test', '合成核验')
        self.w.review(self.sid, self.before, 'approved', 'test', '合成疾病侧核验')
        run = self.w.begin(self.sid, 'A03', {}, {}, '合成旧交集')
        self.w.finish(self.sid, run['run_id'], {'交集数':1}, {})
        self.assertTrue(self.w.active(self.w.load(self.sid), run['run_id']))
        self.process()
        after = self.w.load(self.sid)
        self.assertFalse(self.w.active(after, run['run_id']))
        self.assertEqual(after['current']['A02'], self.before)
        self.assertTrue(self.w.approved(after, self.before))

    def test_partial_download_records_failure_without_single_library_result(self):
        # 已有原件不删除；模拟明确重取失败，不生成A01。
        m = self.w.load(self.sid)
        with patch('science_modules.a01.acquisition.acquire', side_effect=ValueError('network failed')):
            result = flow.acquire_sources(self.w, self.sid, self.a00, '', m['current_component_uploads']['sha256'], self.w.location(self.sid)/'raw/A01_acquisition/fetch_test', ['HERB'])
        self.assertEqual(result[0]['status'], 'failed')
        self.assertNotIn('A01', self.w.load(self.sid)['current'])
        self.assertEqual(self.w.load(self.sid)['current']['A02'], self.before)

    def test_new_policy_never_uses_legacy_single_source_when_acquisition_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            w,sid,a00=fixture(Path(d))
            original=w.result
            def result(m,rid):
                r=original(m,rid)
                if rid==a00:
                    from copy import deepcopy
                    r=deepcopy(r);r['summary']['component_source_profile']=flow.VERSION
                return r
            with patch.object(w,'result',side_effect=result),patch.object(flow,'acquire_sources',return_value=[{'status':'failed'}]),patch('science_modules.a01.uploads.run_components') as legacy:
                with self.assertRaises(ContractError):flow.run_components(w,sid,a00,'','test')
                legacy.assert_not_called()
                self.assertNotIn('A01',w.load(sid)['current'])

    def test_new_collection_review_never_requires_resigning_a02(self):
        from modulea.api.views import Views
        self.process();r=self.process(self.decision());m=self.w.load(self.sid)
        m['workflow_profile']='A00.preupload.2'
        info=Views(None,None)._review_info(self.w,m,'A01',{'can_review':True,'handoff_blocked':False,'code':'review'},r,None,False)
        self.assertIsNone(info['batch_with'])


if __name__ == '__main__':
    unittest.main()
