"""报告补表回归，使用临时文档；不修改真实研究或历史报告。"""
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from docx import Document
from contracts import ContractError
from science_modules.a07.reports import top_rows,add_a03_table,CONFIG,run_reports
from workflow import Workflow

class ReportTableTests(unittest.TestCase):
    def test_boundary_ties_and_archived_ranks(self):
        ranking=[{"compound_id":str(i),"name":"成分"+str(i),"herbs":"测试药","main_rank":i if i<10 else 10,"intersection_count":30-i if i<10 else 20,"mixed_degree":31-i} for i in range(1,13)]
        rows=top_rows(ranking)
        self.assertEqual(len(rows),12);self.assertEqual([r["名次"] for r in rows[-3:]],[10,10,10])
    def test_table_placement_and_chapter_order(self):
        d=Document();d.add_heading("4 交集、成分与PPI网络",level=1);d.add_paragraph("图1 方剂靶点与疾病靶点韦恩图。");d.add_paragraph("PPI结果");d.add_heading("5 GO与KEGG富集結果",level=1)
        rank=[{"compound_id":"c","name":"成分","herbs":"药味","main_rank":1,"intersection_count":5,"mixed_degree":6}]
        add_a03_table(d,rank,"run_test")
        xml=d._element.xml
        self.assertLess(xml.index("图1 方剂"),xml.index("表 A03 01"));self.assertLess(xml.index("混合Degree"),xml.index("PPI结果"))
        self.assertEqual([p.text for p in d.paragraphs if p.style.name=="Heading 1"],["4 交集、成分与PPI网络","5 GO与KEGG富集結果"])
        self.assertEqual([c.text for c in d.tables[0].rows[1].cells],["1","成分","药味","5","6"])
    def test_empty_result_and_ambiguous_anchor(self):
        d=Document();d.add_paragraph("图1 方剂靶点与疾病靶点韦恩图。");add_a03_table(d,[],"empty");self.assertFalse(d.tables);self.assertIn("不生成虚构排名",d.paragraphs[-1].text)
        d=Document()
        with self.assertRaises(ContractError):add_a03_table(d,[],"empty")
    def test_new_version_is_separate_and_stale_upstream_cannot_publish(self):
        import report_flow_pathway as old
        self.assertNotEqual(CONFIG["template_version"],old.CONFIG["template_version"])
        with tempfile.TemporaryDirectory() as root:
            w=Workflow(Path(root));sid=w.create({"formula":"合成方","herbs":"测试药","disease":"测试病","disease_scope":"仅虚构测试","operator":"test","species":9606},kind="contract_test")
            with patch('science_modules.a07.reports.report_heatmap_record',return_value=None),patch('science_modules.a07.reports.report_pathway_record',return_value=None):
                with self.assertRaises(ContractError):run_reports(w,sid,"","上游未完成不能生成")
            self.assertNotIn("A07",w.load(sid)["current"])

    def test_validator_checks_actual_word_cells_against_bound_a03(self):
        from storage import file_record, write_json
        from science_modules.a07.reports import validator
        ranking=[{"compound_id":"c","name":"成分","herbs":"药味","main_rank":1,"intersection_count":5,"mixed_degree":6}]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/"studies"/"test";home.mkdir(parents=True)
            source=home/"runs"/"A03"/"run_source"/"result.json";source.parent.mkdir(parents=True)
            write_json(source,{"tables":{"ranking":ranking}})
            doc=Document();doc.add_paragraph("图1 方剂靶点与疾病靶点韦恩图。");add_a03_table(doc,ranking,"run_source")
            word=home/"detailed.docx";doc.save(word)
            run={"study_id":"test","config":CONFIG,"parent_runs":{"A03":"run_source"},"inputs":{"a03_ranking_source":file_record(home,source,"result")}}
            tables={"a03_top10":top_rows(ranking),"report_files":[file_record(home,word,"detailed_report")]}
            with patch('science_modules.a07.reports.legacy.validator',return_value=lambda *args:None):
                check=validator(root);check(run,{},tables,[],"success")
                doc.tables[0].rows[1].cells[3].text="999";doc.save(word)
                tables["report_files"]=[file_record(home,word,"detailed_report")]
                with self.assertRaises(ContractError):check(run,{},tables,[],"success")

    def test_full_new_report_contract_publishes_unapproved_version(self):
        from storage import file_record
        from science_modules.a07.reports import validator, build_detailed
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);w=Workflow(root);sid=w.create({"formula":"合成方","herbs":"测试药","disease":"测试病","disease_scope":"测试范围","operator":"test","species":9606},kind="contract_test")
            m=w.load(sid);w.review(sid,m["current"]["A00"],"approved","test","仅合成测试")
            rank=[{"compound_id":"c","name":"成分","herbs":"药味","main_rank":1,"intersection_count":5,"mixed_degree":6}]
            for mid in ("A01","A02","A03","A03_SELECT","A04","A05","A06_PREP","A06"):
                run=w.begin(sid,mid,{}, {},"合成测试")
                w.finish(sid,run["run_id"],{}, {"ranking":rank} if mid=="A03" else {})
                w.review(sid,run["run_id"],"approved","test","仅合成测试")
            m=w.load(sid)
            payload={"analysis_purpose":"workflow_test","parent_runs":m["current"],"a01_databases":["TCMSP","HERB","BATMAN"],"a02_databases":["GeneCards","OMIM","TTD","PharmGKB","OTP"],"a03_tables":{"ranking":rank},"a03_top10":top_rows(rank),"selection_run":m["current"]["A03_SELECT"],"key_counts":[],"conclusion_draft":"合成流程测试，不能据此认定治疗有效", "research_leads":[],"limitations":[],"heatmap_png":None,"receptor_setup_sources":[]}
            def figures(folder,payload):
                folder.mkdir(parents=True);data={}
                for name in ("01_方剂疾病靶点韦恩图","02_药味成分交集靶点网络图","03_PPI完整网络图","04_PPI第一轮主候选网络图","05_GO富集三分类柱状图","06_KEGG富集气泡图"):
                    data[name]={}
                    for kind in ("svg","png"):
                        path=folder/(name+"."+kind);path.write_bytes(b"synthetic test only");data[name][kind]=path
                return data
            def old_builder(payload,path,*args):
                d=Document();d.add_heading("3 数据来源与方法",level=1);d.add_paragraph("成分与方剂靶点：旧描述");d.add_paragraph("疾病靶点：旧描述");d.add_heading("4 交集、成分与PPI网络",level=1);d.add_paragraph("图1 方剂靶点与疾病靶点韦恩图。");d.add_paragraph("PPI结果");d.save(path)
            def concise(payload,path,*args):Document().save(path)
            w.validators["A07"]=validator(root)
            with patch('science_modules.a07.reports.report_heatmap_record',return_value=None),patch('science_modules.a07.reports.report_pathway_record',return_value=None),patch('science_modules.a07.reports.assemble_payload',return_value=payload),patch('science_modules.a07.reports.generate_report_figures',side_effect=figures),patch('science_modules.a07.reports.attach_report_pathway',return_value=[]),patch('science_modules.a07.reports.legacy.build_detailed',side_effect=old_builder),patch('science_modules.a07.reports.build_concise',side_effect=concise):
                result=run_reports(w,sid,"","合成发布验证")
            self.assertEqual(result["tables"]["a03_top10"],top_rows(rank));self.assertFalse(w.approved(w.load(sid),result["run_id"]))
            detail=next(r for r in result["tables"]["report_files"] if r["role"]=="detailed_report")
            text="".join(p.text for p in Document(root/"studies"/sid/detail["path"]).paragraphs)
            self.assertIn("BATMAN-TCM",text);self.assertIn("Open Targets Platform",text)
