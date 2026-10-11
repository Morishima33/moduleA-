"""A05展示规则与人工确认自测：虚构研究，禁止写入实际研究目录。"""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contracts import ContractError
from modulea.core.enrichment_workflow import EnrichmentWorkflow
from science_modules.a05 import display, display_flow, flow
from storage import new_id, verified_file
from tests.a05_fixture import seed


# 数值只用于测试排名和空结果；明确不是任何病例计算结果。
def fake_base(n=30):
    tables={}
    translations={}
    for g in ("bp","cc","mf","kegg"):
        rows=[]
        for i in range(n):
            tid=g+str(i).zfill(3)
            row={"ID":tid,"Description":"Synthetic "+tid,"Count":i+1,"p.adjust":(i+1)*.0001,"RichFactor":.02*(i+1)}
            rows.append(row)
            translations[tid]={"english":row["Description"],"zh":"虚构条目"+tid,"source":"synthetic fixture"}
        tables[g+"_significant"]=rows
    return {"tables":tables,"summary":{"handoff_blocked":False}},translations


class DisplaySelectionTests(unittest.TestCase):
    def test_full_significant_pool_independent_rankings_and_exact_quotas(self):
        base,translations=fake_base()
        summary,t=display.build(base,translations,{},{"base_run":"test","excluded_ids":[],"exclusions_confirmed":True,"layout_confirmed":True})
        for g in ("bp","cc","mf"):
            self.assertEqual(len(t[g+"_graph8"]),8)
            self.assertEqual(len(t[g+"_top15"]),15)
        self.assertEqual(t["kegg_graph15"][0]["ID"],"kegg000")
        self.assertEqual(t["kegg_count_top10"][0]["ID"],"kegg029")
        self.assertEqual(t["kegg_p_top10"][0]["ID"],"kegg000")
        self.assertFalse(summary["handoff_blocked"])
        self.assertEqual(t["kegg_significant"],base["tables"]["kegg_significant"])

    def test_exclusion_only_display_p_values_and_full_tables_preserved(self):
        base,translations=fake_base()
        before=deepcopy(base)
        _,t=display.build(base,translations,{},{"excluded_ids":["kegg000","kegg001"],"exclusions_confirmed":True,"layout_confirmed":False})
        self.assertEqual(t["kegg_graph15"][0]["ID"],"kegg002")
        self.assertEqual(t["kegg_significant"],before["tables"]["kegg_significant"])
        self.assertEqual(base,before)
        self.assertEqual([r["ID"] for r in t["kegg_excluded"]],["kegg000","kegg001"])
        with self.assertRaises(ContractError):
            display.build(base,translations,{},{"excluded_ids":["other-study"]})

    def test_empty_short_and_missing_translation(self):
        base,translations=fake_base(0)
        _,t=display.build(base,translations,{},{"excluded_ids":[]})
        self.assertEqual(t["kegg_graph15"],[])
        base,translations=fake_base(1)
        translations.pop("bp000")
        s,t=display.build(base,translations,{},{"excluded_ids":[],"exclusions_confirmed":True,"layout_confirmed":True})
        self.assertEqual(len(t["cc_top15"]),1)
        self.assertTrue(s["handoff_blocked"])
        self.assertEqual(display.metadata(t)["missing_translations"],["bp000"])

    def test_ties_use_ids_and_count_secondary_p(self):
        base,translations=fake_base()
        for r in base["tables"]["kegg_significant"]:r["p.adjust"]=.001
        base["tables"]["kegg_significant"].reverse()
        _,t=display.build(base,translations,{},{"excluded_ids":[]})
        self.assertEqual([r["ID"] for r in t["kegg_p_top10"]],[f"kegg{i:03d}" for i in range(10)])


# 完整发布在真实R合成基线之上执行，检查确认持久化与历史不变。
class DisplayWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        legacy,sid=seed(cls.root)
        m=legacy.load(sid)
        cls.base=flow.run_enrichment(legacy,sid,m["current"]["A03"],"","合成统计基线")
        cls.sid=sid

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        import shutil
        self.temp_case=tempfile.TemporaryDirectory()
        self.root_case=Path(self.temp_case.name)/"data"
        shutil.copytree(self.root,self.root_case)
        self.w=EnrichmentWorkflow(self.root_case,{"A05":display_flow.validator(self.root_case)})
        self.sid=self.__class__.sid
        translations={r["ID"]:{"english":display.english(r),"zh":"虚构核译","source":"synthetic fixture"} for g in ("bp","cc","mf","kegg") for r in self.base["tables"][g+"_significant"]}
        with patch.object(display_flow,"translation_snapshot",return_value=translations):
            self.preview=display_flow.prepare(self.w,self.sid,self.base["run_id"],{"hsa00001":{"reason_zh":"虚构排除建议","evidence_url":"https://www.kegg.jp/pathway/hsa00001"}})

    def tearDown(self):self.temp_case.cleanup()

    def payload(self,action="exclusions",ids=None):
        m=self.w.load(self.sid);rid=m["current"]["A05"];r=self.w.result(m,rid);meta=display.metadata(r["tables"])
        latest,_=self.w.display_decision(m,m["current"]["A03"],meta["base_run"])
        return {"expected_a03":m["current"]["A03"],"expected_a05":rid,"expected_decision_id":latest["decision_id"] if latest else None,"action":action,"excluded_ids":[] if ids is None else ids,"reviewer":"虚构核验人","note":"仅自测确认","confirmed":True,"decision_id":new_id("decision")}

    def test_explicit_scope_then_layout_preserves_history_no_auto_approval(self):
        previous=deepcopy(self.preview)
        scope=display_flow.apply_confirmation(self.w,self.sid,self.payload())
        self.assertTrue(scope["summary"]["handoff_blocked"])
        self.assertTrue(scope["summary"]["display_exclusions_confirmed"])
        final=display_flow.apply_confirmation(self.w,self.sid,self.payload("layout"))
        self.assertFalse(final["summary"]["handoff_blocked"])
        m=self.w.load(self.sid)
        self.assertFalse(self.w.approved(m,final["run_id"]))
        self.assertNotIn("A06",m["current"])
        self.assertEqual(self.w.result(m,previous["run_id"]),previous)
        for record in final["files"]:verified_file(self.w.location(self.sid),record)

    def test_zero_exclusion_requires_explicit_identity_and_scope(self):
        for key,value in (("confirmed",False),("reviewer",""),("note",""),("excluded_ids",["alien-study"]),("expected_a05","run_other")):
            p=self.payload();p[key]=value
            with self.assertRaises(ContractError):self.w.validate_display_confirmation(self.sid,p)
        with self.assertRaises(ContractError):self.w.validate_display_confirmation(self.sid,self.payload("layout"))

    def test_failure_retry_reuses_saved_decision_and_no_false_applied(self):
        p=self.payload()
        with patch("science_modules.a05.figures.draw_all",side_effect=RuntimeError("模拟绘图失败")):
            with self.assertRaises(RuntimeError):display_flow.apply_confirmation(self.w,self.sid,p)
        m=self.w.load(self.sid)
        self.assertEqual(m["current"]["A05"],p["expected_a05"])
        self.assertEqual(len(m["enrichment_display_decisions"]),1)
        result=display_flow.apply_confirmation(self.w,self.sid,p)
        again=display_flow.apply_confirmation(self.w,self.sid,p)
        self.assertEqual(again["run_id"],result["run_id"])
        self.assertEqual(len(self.w.load(self.sid)["enrichment_display_decisions"]),1)

    def test_scope_change_revokes_layout_and_approval(self):
        display_flow.apply_confirmation(self.w,self.sid,self.payload())
        final=display_flow.apply_confirmation(self.w,self.sid,self.payload("layout"))
        self.w.review(self.sid,final["run_id"],"approved","虚构核验人","仅测试审批")
        new=display_flow.apply_confirmation(self.w,self.sid,self.payload(ids=["hsa00001"]))
        self.assertFalse(new["summary"]["display_layout_confirmed"])
        self.assertTrue(new["summary"]["handoff_blocked"])
        self.assertEqual(new["tables"]["kegg_graph15"],[])
        self.assertFalse(self.w.approved(self.w.load(self.sid),new["run_id"]))


if __name__=="__main__":unittest.main()
