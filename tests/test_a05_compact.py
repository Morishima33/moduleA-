"""A05紧凑展示回归：旧图、原统计、分列报告与人工确认边界。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from docx import Document
from unittest.mock import patch
from science_modules.a05 import display, figures, compact_display, compact_figures, compact_flow, compact_report_section
from modulea.core.enrichment_workflow import EnrichmentWorkflow
from tests import test_a05_display as legacy_tests
from storage import file_record

class CompactPresentationTests(unittest.TestCase):
    # 新版只改变版本和表格名称；全部统计和各图表排名与旧版一致。
    def test_rankings_statistics_and_go_image_unchanged(self):
        base,tr=legacy_tests.fake_base(20)
        control={"excluded_ids":["kegg000"],"exclusions_confirmed":True,"layout_confirmed":False}
        _,old=display.build(base,tr,{},control)
        _,new=compact_display.build(base,tr,{},control)
        for k in old:
            if k!="display_metadata":self.assertEqual(old[k],new[k])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            a=figures.draw_go(old,root/"old")
            b=compact_figures.draw_all(new,root/"new")["go"]
            for kind in ("png","svg"):self.assertEqual(a[kind].read_bytes(),b[kind].read_bytes())
        shades=[compact_figures.color_scale(i/10) for i in range(11)]
        rgb=[tuple(int(s[j:j+2],16) for j in (1,3,5)) for s in shades]
        self.assertTrue(all(b>g>r for r,g,b in rgb))
        self.assertTrue(all(sum(rgb[i])>sum(rgb[i+1]) for i in range(10)))
        self.assertEqual(compact_display.metadata(new)["version"],"A05.display.3")

    # Word五张表英文、中文分列，GO ID独立小字号；数值逐格与归档一致。
    def test_separate_columns_and_small_identifier_in_report(self):
        base,tr=legacy_tests.fake_base(20)
        s,t=compact_display.build(base,tr,{},{"excluded_ids":[],"exclusions_confirmed":True,"layout_confirmed":False})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t["display_figures"]=[]
            for group,pair in compact_figures.draw_all(t,root/"figures").items():
                row={"group":group}
                for kind,path in pair.items():
                    row.update({kind+"_"+k:v for k,v in file_record(root,path,"figure").items() if k in ("path","bytes","sha256")})
                t["display_figures"].append(row)
            doc=Document();compact_report_section.add_section(doc,t,root)
            compact_report_section.validate_section(doc,t)
            self.assertEqual([len(x.columns) for x in doc.tables],[3,3,3,4,4])
            self.assertEqual([len(x.rows)-1 for x in doc.tables],[15,15,15,10,10])
            cell=doc.tables[0].rows[1].cells[0]
            self.assertIn("Synthetic",cell.text)
            self.assertNotIn("虚构",cell.text)
            self.assertIn("虚构",doc.tables[0].rows[1].cells[1].text)
            self.assertEqual(cell.paragraphs[0].runs[-1].font.size.pt,7)


    # 第19版专业报告只替换A05，保持A04和A06章节与说明。
    def test_professional_v19_preserves_neighboring_sections(self):
        from science_modules.a07 import compact_enrichment_reports as reports
        base,tr=legacy_tests.fake_base(20)
        s,t=compact_display.build(base,tr,{},{"excluded_ids":[],"exclusions_confirmed":True,"layout_confirmed":True})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t["display_figures"]=[]
            for group,pair in compact_figures.draw_all(t,root/"figures").items():
                row={"group":group}
                for kind,path in pair.items():
                    row.update({kind+"_"+k:v for k,v in file_record(root,path,"figure").items() if k in ("path","bytes","sha256")})
                t["display_figures"].append(row)
            def older(payload,destination,root,revision):
                doc=Document();doc.add_heading("4 PPI网络",1);doc.add_paragraph("已确认A04表图次序")
                doc.add_heading("5 GO与KEGG富集结果",1);doc.add_paragraph("旧A05")
                doc.add_heading("6 分子对接结果",1);doc.add_paragraph("A06原结论边界");doc.save(destination)
            path=root/"v19.docx"
            with patch.object(reports.previous,"build_detailed",side_effect=older),patch.object(reports.previous.legacy,"add_selected_pathway"):
                reports.build_detailed({"a05_display":{"tables":t,"summary":s}},path,root,"synthetic")
            doc=Document(path);compact_report_section.validate_section(doc,t)
            text=[p.text for p in doc.paragraphs]
            self.assertIn("已确认A04表图次序",text)
            self.assertIn("A06原结论边界",text)
            self.assertNotIn("旧A05",text)
            self.assertLess(text.index("已确认A04表图次序"),text.index(compact_report_section.GO_CAPTION))
            self.assertLess(text.index(compact_report_section.KEGG_CAPTION),text.index("6 分子对接结果"))
            self.assertEqual(reports.CONFIG["template_version"],"A07.double_report.19")

class CompactUpgradeTests(legacy_tests.DisplayWorkflowTests):
    # 使用既有虚构R基线；版式升级保留已确认名单，撤销新版式审批而不重算。
    def test_revision_retains_scope_history_and_requires_new_layout(self):
        from science_modules.a05 import display_flow
        display_flow.apply_confirmation(self.w,self.sid,self.payload(ids=["hsa00001"]))
        old=display_flow.apply_confirmation(self.w,self.sid,self.payload("layout",["hsa00001"]))
        self.w.review(self.sid,old["run_id"],"approved","虚构核验人","仅隔离测试")
        m=self.w.load(self.sid);reviews=deepcopy(m["reviews"])
        upgraded=EnrichmentWorkflow(self.root_case,{"A05":compact_flow.validator(self.root_case)})
        new=compact_flow.revise_layout(upgraded,self.sid,old["run_id"])
        meta=compact_display.metadata(new["tables"])
        self.assertEqual(meta["excluded_ids"],["hsa00001"])
        self.assertTrue(meta["exclusions_confirmed"])
        self.assertFalse(meta["layout_confirmed"])
        self.assertEqual(upgraded.result(upgraded.load(self.sid),old["run_id"]),old)
        self.assertEqual(upgraded.load(self.sid)["reviews"],reviews)
        self.assertFalse(upgraded.approved(upgraded.load(self.sid),new["run_id"]))
        for g in ("bp","cc","mf","kegg"):self.assertEqual(old["tables"][g+"_significant"],new["tables"][g+"_significant"])
        self.w=upgraded
        final=compact_flow.apply_confirmation(upgraded,self.sid,self.payload("layout",["hsa00001"]))
        self.assertTrue(compact_display.metadata(final["tables"])["layout_confirmed"])
        self.assertFalse(upgraded.approved(upgraded.load(self.sid),final["run_id"]))

if __name__=="__main__":unittest.main()
