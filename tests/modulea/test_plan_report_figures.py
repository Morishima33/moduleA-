"""新报告图件边界：真实空交集分离，完整NA行列保留，标记只读原始评分。"""
from pathlib import Path
import tempfile,unittest
from xml.etree import ElementTree as ET
from science_modules.a07 import plan_figures as figures
from science_modules.a07.plan_facts import docking
from contracts import ContractError


class PlanReportFiguresTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plan_report_figures_');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_actual_zero_overlap_has_separate_circles(self):
        paths=figures.venn({'仅方剂靶点数':2,'交集靶点数':0,'仅疾病靶点数':3},self.root)
        svg=ET.parse(paths['svg']).getroot();circles=svg.findall('{http://www.w3.org/2000/svg}circle')
        self.assertEqual(len(circles),2)
        self.assertGreater(float(circles[1].get('cx'))-float(circles[0].get('cx')),sum(float(row.get('r')) for row in circles))
        self.assertIn('交集为空',paths['svg'].read_text('utf8'))

    def test_complete_na_rows_columns_and_raw_threshold_marks_survive_blocks(self):
        compounds=[{'compound_id':f'C{i}'} for i in range(25)];receptors=[{'target_id':f'R{i}','symbol':f'GENE{i}'} for i in range(9)]
        rows=[{'compound_id':c['compound_id'],'target_id':r['target_id'],'state':'NA','score':None,'reason_zh':'明确合成缺失图件测试'} for c in compounds for r in receptors]
        rows[0].update(state='completed',score=-7.9999,quality='探索');rows[1].update(state='completed',score=-8.0001,quality='严格')
        facts=docking({'study_id':'explicit_synthetic','run_id':'explicit_synthetic','compounds':compounds,'receptors':receptors,'pairs':rows},{})
        outputs=figures.heatmaps(facts,self.root);self.assertEqual(len(outputs),4)
        labels=[]
        for paths,_ in outputs:
            svg=ET.parse(paths['svg']).getroot();width=float(svg.get('width'));height=float(svg.get('height'))
            text=svg.findall('{http://www.w3.org/2000/svg}text');labels.extend(row.text for row in text)
            self.assertTrue(all(0<=float(row.get('x'))<=width and 0<=float(row.get('y'))<=height for row in text))
        self.assertEqual(labels.count('NA'),223);self.assertEqual(labels.count('-8.00'),1);self.assertEqual(labels.count('-8.00**'),1)
        self.assertIn('成分25',labels);self.assertIn('GENE8',labels)

    def test_one_cell_all_na_has_no_zero_or_fake_score_color(self):
        facts=docking({'compounds':[{'compound_id':'C'}],'receptors':[{'target_id':'R'}],
            'pairs':[{'compound_id':'C','target_id':'R','state':'NA','score':None,'reason_zh':'明确合成无可用结构'}]}, {})
        outputs=figures.heatmaps(facts,self.root);text=outputs[0][0]['svg'].read_text('utf8')
        self.assertIn('本批无可用评分',text);self.assertIn('>NA<',text);self.assertNotIn('>0.00<',text)

    def test_network_includes_actual_isolate_and_rejects_extra_edge(self):
        result={'tables':{'mapping':[{'target_id':key,'symbol':key} for key in ('GENE_A','GENE_B','GENE_C')],
            'edges':[{'source':'GENE_A','target':'GENE_B'}]}}
        paths=figures.ppi(result,self.root);svg=ET.parse(paths['svg']).getroot()
        self.assertEqual(len(svg.findall('{http://www.w3.org/2000/svg}circle')),3)
        self.assertEqual(len(svg.findall('{http://www.w3.org/2000/svg}line')),1)
        self.assertIn('GENE_C',paths['svg'].read_text('utf8'))
        result['tables']['edges'].append({'source':'GENE_A','target':'unknown'})
        with self.assertRaises(ContractError):figures.ppi(result,self.root/'forbidden')

    def test_tall_narrow_complete_matrix_fits_report_page_height(self):
        """最后仅一受体列时不放大成超页高图片，全NA行仍完整保留。"""
        from docx import Document
        from docx.shared import Cm
        from storage import file_record
        from science_modules.a07.plan_documents import figure
        compounds=[{'compound_id':f'C{i}'} for i in range(25)]
        facts=docking({'compounds':compounds,'receptors':[{'target_id':'R'}],
            'pairs':[{'compound_id':row['compound_id'],'target_id':'R','state':'NA','score':None,'reason_zh':'合成NA版式测试'} for row in compounds]}, {})
        paths,_=figures.heatmaps(facts,self.root)[0];document=Document()
        figure(document,self.root,{'record':file_record(self.root,paths['png'],'figure'),'caption':'合成完整矩阵图'})
        shape=document.inline_shapes[0];self.assertLessEqual(shape.height,Cm(20)+10)
        self.assertLess(shape.width,Cm(15.8))

    def test_small_na_matrix_is_readable_without_full_page_pixel_enlargement(self):
        """两组NA矩阵居中保持原图密度，不把短图放大成整页巨字。"""
        from docx import Document
        from docx.shared import Cm
        from storage import file_record
        from science_modules.a07.plan_documents import figure
        facts=docking({'compounds':[{'compound_id':'C1'},{'compound_id':'C2'}],'receptors':[{'target_id':'R'}],
            'pairs':[{'compound_id':cid,'target_id':'R','state':'NA','score':None,'reason_zh':'合成NA'} for cid in ('C1','C2')]},{})
        paths,_=figures.heatmaps(facts,self.root)[0];document=Document()
        figure(document,self.root,{'module':'A06','record':file_record(self.root,paths['png'],'figure'),'caption':'合成小矩阵'})
        shape=document.inline_shapes[0];self.assertLessEqual(shape.width,Cm(10));self.assertLessEqual(shape.height,Cm(10))
