"""A05专业报告集成与三库HGNC适配回归；仅合成资料和隔离文件。"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from docx import Document
from contracts import ContractError
from storage import file_record
from science_modules.a05 import display,flow,figures,report_section
from science_modules.a07 import enrichment_reports
from tests.test_a05_display import fake_base

class MappingBindingTests(unittest.TestCase):
    def test_parent_a02_mapping_fallback_rejects_other_snapshot_without_mutating_a01(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/"hgnc.tsv";path.write_text("hgnc_id\tsymbol\tentrez_id\nHGNC:1\tTEST1\t1\n",encoding="utf-8")
            rec=file_record(root,path,"mapping_source")
            runs={"a03":{"parent_runs":{"A01":"a01","A02":"a02"}},"a01":{"run_id":"a01","inputs":{"candidate_data":[]}},"a02":{"inputs":{"mapping_file":rec}}}
            summary={"mapping_snapshot":rec["sha256"]};before=deepcopy(runs)
            w=Mock();w.run.side_effect=lambda m,r:runs[r];w.result.return_value={"summary":summary};w.location.return_value=root
            self.assertEqual(flow.mapping_record(w,{"study_id":"synthetic"},"a03"),rec)
            self.assertEqual(runs,before)
            summary["mapping_snapshot"]="foreign"
            with self.assertRaisesRegex(ContractError,"快照不一致"):flow.mapping_record(w,{"study_id":"synthetic"},"a03")
            runs["a02"]["inputs"]={}
            with self.assertRaisesRegex(ContractError,"未绑定"):flow.mapping_record(w,{"study_id":"synthetic"},"a03")

class ProfessionalReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        base,tr=fake_base(20)
        for g in ("bp","cc","mf","kegg"):
            for r in base["tables"][g+"_significant"]:r["gene_symbols"]="TEST1/TEST2"
        s,t=display.build(base,tr,{},{"base_run":"synthetic","exclusions_confirmed":True,"layout_confirmed":True,"excluded_ids":["kegg000"]})
        t["display_figures"]=[]
        for group,pair in figures.draw_all(t,self.root/"figures").items():
            row={"group":group}
            for kind,path in pair.items():row.update({kind+"_"+k:v for k,v in file_record(self.root,path,"figure").items() if k in ("path","bytes","sha256")})
            t["display_figures"].append(row)
        self.result={"tables":t,"summary":s}
    def tearDown(self):self.temp.cleanup()
    def test_preview_tables_graphs_bilingual_and_exact_order_match_archive(self):
        target=self.root/"preview.docx";report_section.preview(self.result,self.root,target)
        doc=Document(target);report_section.validate_section(doc,self.result["tables"])
        self.assertEqual([len(t.rows)-1 for t in doc.tables],[15,15,15,10,10])
        self.assertEqual(len(doc.inline_shapes),2)
        self.assertTrue(all("虚构条目" in t.rows[1].cells[0].text for t in doc.tables))
        self.assertTrue(all(t.rows[0]._tr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}trPr/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader") is not None for t in doc.tables))
    def test_professional_replacement_preserves_a04_a06_chapters_and_captions(self):
        def old(payload,destination,root,revision):
            d=Document();d.add_heading("4 PPI网络",1);d.add_paragraph("已确认A04原文")
            d.add_heading("5 GO与KEGG富集结果",1);d.add_paragraph("旧A05");d.add_table(1,1).cell(0,0).text="旧富集表"
            d.add_heading("6 分子对接结果",1);d.add_paragraph("A06原文与结论边界");d.save(destination)
        target=self.root/"professional.docx"
        with patch.object(enrichment_reports.previous,"build_detailed",side_effect=old),patch.object(enrichment_reports.previous.legacy,"add_selected_pathway"):
            enrichment_reports.build_detailed({"a05_display":self.result},target,self.root,"synthetic")
        d=Document(target);report_section.validate_section(d,self.result["tables"])
        text=[p.text for p in d.paragraphs]
        self.assertIn("已确认A04原文",text);self.assertIn("A06原文与结论边界",text);self.assertNotIn("旧A05",text)
        self.assertLess(text.index("已确认A04原文"),text.index(report_section.GO_CAPTION))
        self.assertLess(text.index(report_section.KEGG_CAPTION),text.index("6 分子对接结果"))
    def test_actual_archived_images_copied_only_into_new_report_directory(self):
        names=("05_GO富集三分类柱状图","06_KEGG富集气泡图")
        paths={name:{kind:self.root/"new"/(name+"."+kind) for kind in ("png","svg")} for name in names}
        (self.root/"new").mkdir()
        for pair in paths.values():
            for path in pair.values():path.write_bytes(b"temporary generated")
        before={str(p):p.read_bytes() for p in (self.root/"figures").iterdir()}
        with patch.object(enrichment_reports.previous,"generate_report_figures",return_value=paths):
            enrichment_reports.generate_report_figures(self.root/"new",{"a05_display":self.result,"_a05_home":str(self.root)})
        for group,name in zip(("go","kegg"),names):
            record=next(x for x in self.result["tables"]["display_figures"] if x["group"]==group)
            self.assertEqual(paths[name]["png"].read_bytes(),(self.root/record["png_path"]).read_bytes())
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.root/"figures").iterdir()})
    def test_reject_edited_word_and_unconfirmed_scope(self):
        target=self.root/"preview.docx";report_section.preview(self.result,self.root,target)
        d=Document(target);d.tables[0].rows[1].cells[0].text="wrong"
        with self.assertRaises(ContractError):report_section.validate_section(d,self.result["tables"])
        w=Mock();bad=deepcopy(self.result);bad["tables"]["display_metadata"][0]["layout_confirmed"]=False;w.result.return_value=bad
        with self.assertRaisesRegex(ContractError,"请先确认"):enrichment_reports.assemble_payload(w,{},{"A05":"synthetic"})

if __name__=="__main__":unittest.main(verbosity=2)
