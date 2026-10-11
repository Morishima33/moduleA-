"""冰蓝/莓果红配色与报告同源图件测试；合成评分只留隔离目录。"""
from copy import deepcopy
from pathlib import Path
from io import BytesIO
import unittest,tempfile
from docx import Document
from PIL import Image
from contracts import ContractError
from science_modules.a06.matrix_palette import VERSION,PALETTE,color
from science_modules.a06.matrix_exports import export_heatmap,heatmap_svg,layout
from science_modules.a06.matrix_report_section import replace_section,validate_section
from science_modules.a06.matrix_display import matrix_view
from tests.modulea.test_docking_matrix import MatrixTests,ReviewTests

class PaletteTests(MatrixTests):
 def setUp(self):
  super().setUp();self.config['version']=VERSION
 def test_endpoints_full_range_and_legacy(self):
  self.assertEqual(color(-10,-10,-5),'#B7326B');self.assertEqual(color(-5,-10,-5),'#A7D5E5');self.assertEqual(color(-7,-7,-7),'#AF84A8')
  matrix=self.view();self.assertEqual(matrix['palette'],PALETTE);self.assertEqual(matrix['heatmap']['cells'][0][0]['color'],'#A7D5E5');self.assertIn('kcal/mol',matrix['heatmap_svg'])
  self.assertIn(f'{matrix["score_range"][0]:.4g}',matrix['heatmap_svg'])
 def test_png_svg_report_same_batch(self):
  m=self.view();paths=export_heatmap(m,self.root/'exports');self.assertEqual(paths['svg'].read_text(encoding='utf-8'),m['heatmap_svg'])
  image=Image.open(paths['png']);g=layout(m);cell=m['heatmap']['cells'][0][0];expected=tuple(int(cell['color'][i:i+2],16) for i in (1,3,5));self.assertEqual(image.getpixel(((g['left']+5)*3,(g['top']+5)*3)),expected)
  doc=Document();doc.add_heading('5 GO与KEGG富集结果',level=1);doc.add_heading('6 分子对接结果',level=1);doc.add_paragraph('OLD HEATMAP');doc.add_heading('7 待进一步核验的研究线索',level=1);replace_section(doc,m,paths['png']);buf=BytesIO();doc.save(buf);buf.seek(0);loaded=Document(buf);validate_section(loaded,m);self.assertEqual(len(loaded.tables[0].rows),16);self.assertEqual(len(loaded.tables[0].columns),16);self.assertNotIn('OLD HEATMAP',[p.text for p in loaded.paragraphs]);self.assertEqual(len(loaded.inline_shapes),1)
  self.assertEqual(loaded.sections[1].page_width>loaded.sections[1].page_height,True);self.assertEqual(loaded.sections[-1].page_width<loaded.sections[-1].page_height,True)
 def test_report_wrapper_keeps_structure_setup_and_explanation(self):
  from science_modules.a07 import matrix_reports
  from unittest.mock import patch
  m=self.view();paths=export_heatmap(m,self.root/'export_report');destination=self.root/'professional.docx'
  setup={k:'隔离参数' for k in ['靶点基因','PDB ID','蛋白链','共晶参考配体','搜索盒中心坐标','搜索盒尺寸','重对接RMSD（Å）','质控状态']}
  def old(payload,destination,root,revision):
   doc=Document();doc.add_heading('5 GO与KEGG富集结果',1);doc.add_paragraph('已确认A05');doc.add_heading('6 分子对接结果',1);doc.add_paragraph('旧图与旧矩阵');doc.add_paragraph('单位：kcal/mol。当前批次主要结果解释。');doc.add_heading('7 待进一步核验的研究线索',1);doc.add_paragraph('保留结论边界');doc.save(destination)
  with patch.object(matrix_reports.previous,'build_detailed',side_effect=old):matrix_reports.build_detailed({'a06_matrix':m,'_a06_matrix_png':str(paths['png']),'receptor_setup':[setup]},destination,self.root,'isolated')
  doc=Document(destination);validate_section(doc,m);text=[p.text for p in doc.paragraphs]
  self.assertIn('已确认A05',text);self.assertIn('保留结论边界',text);self.assertIn('单位：kcal/mol。当前批次主要结果解释。',text);self.assertNotIn('旧图与旧矩阵',text)
  self.assertTrue(any(t.rows[0].cells[0].text=='靶点基因' for t in doc.tables))
 def test_waiting_all_na_constant_and_tampered_color(self):
  waiting=matrix_view(self.config,self.cs,self.ts);self.assertIsNone(waiting['heatmap_svg'])
  with self.assertRaises(ContractError):export_heatmap(waiting,self.root/'blocked')
  p=deepcopy(self.packet)
  for r in p['pairs']:r.update(state='NA',score=None,reason_zh='虚构失败')
  m=self.view(p);self.assertEqual(m['score_range'],[None,None]);self.assertIn('全部为NA',m['heatmap_svg']);self.assertIn('NA',m['heatmap_svg'])
  for r in p['pairs']:r.update(state='completed',score=-7)
  m=self.view(p);self.assertEqual(m['heatmap']['cells'][0][0]['color'],'#AF84A8');self.assertNotIn('fill="url(#scores)"',m['heatmap_svg'])
  m['heatmap']['cells'][0][0]['color']='#FFFFFF'
  with self.assertRaises(ContractError):heatmap_svg(m)
 # 旧蓝端点断言由父类对旧版本单独验证，不应用到新版本。
 def test_NA_retained_and_color_direction(self):
  p=deepcopy(self.packet);p['pairs'][0].update(state='NA',score=None,reason_zh='合成资料无法准备');m=self.view(p);self.assertEqual(m['heatmap']['cells'][0][0]['color'],'#DCE1E5');self.assertIsNone(m['heatmap']['cells'][0][0]['score'])

class DisplayRecordTests(ReviewTests):
 def test_save_display_does_not_change_approval_and_blocks_scope_change(self):
  self.data['compounds'][1]['identity_prechecked']=True;draft=self.f.save_docking_review(self.sid,self.data)
  req=self.request(draft['review_id']);req['selected']=['C1','C2'];r=self.f.save_selection(self.sid,req);self.f.review(self.sid,r['run_id'],'approved','隔离复核','虚构资料')
  from science_modules.a06.plan_adapter import source_context
  from modulea.core.docking_review import review_context
  before=self.f.load(self.sid);c=source_context(self.f,self.sid,before);request={'expected_source':c['source_key'],'expected_display_id':None,'config':dict(self.data['display'],version=VERSION)}
  saved=self.f.save_matrix_display(self.sid,request);after=self.f.load(self.sid)
  for k in ('current','runs','reviews'):self.assertEqual(before[k],after[k])
  self.assertEqual(review_context(self.f,after)['matrix']['palette'],PALETTE)
  with self.assertRaises(ContractError):self.f.save_matrix_display(self.sid,request)
  request['expected_display_id']=saved['display_id'];request['config']['heatmap_compounds']=['C2']
  with self.assertRaises(ContractError):self.f.save_matrix_display(self.sid,request)

if __name__=='__main__':unittest.main()
