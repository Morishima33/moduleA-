"""新排版只改变Excel样式，原始数值、NA、CSV及第一版实现保持。"""
from copy import deepcopy
from pathlib import Path
import unittest

from openpyxl import load_workbook
from science_modules.a06 import system_exports as first,system_exports_v2 as second
from tests.modulea import test_system_exports as fixture


class SystemExportsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.source=fixture.SystemExportsTests('runTest');self.source.setUp()
        self.addCleanup(self.source.doCleanups)

    def test_explicit_second_version_layout_and_raw_values_remain_identical(self):
        f=self.source;before=deepcopy((f.run,f.result,f.packet))
        old=first.export(f.view(),f.home/'first')
        view=second.build_view(f.run,f.result,f.packet);new=second.export(view,f.home/'second')
        self.assertEqual(view['schema_version'],'A06.system_exports.2');self.assertEqual(first.VERSION,'A06.system_exports.1')
        self.assertEqual((f.run,f.result,f.packet),before)
        self.assertEqual(Path(old['csv']).read_bytes(),Path(new['csv']).read_bytes())
        book=load_workbook(new['xlsx']);matrix=book['完整评分矩阵'];detail=book['原始评分与异常']
        self.assertEqual(matrix.cell(2,3).value,-8.123456789);self.assertEqual(matrix.cell(2,4).value,'NA')
        self.assertIn('A4:D4',str(matrix.merged_cells));self.assertIn('A5:D5',str(matrix.merged_cells))
        self.assertGreaterEqual(detail.column_dimensions['A'].width,48)
        self.assertGreaterEqual(detail.column_dimensions['L'].width,64)
        self.assertGreaterEqual(matrix.row_dimensions[4].height,32)
        self.assertEqual(matrix.freeze_panes,'C2');self.assertEqual(detail.freeze_panes,'D2')
        self.assertFalse(any(cell.data_type=='f' for sheet in book for row in sheet for cell in row));book.close()
        self.assertTrue(second.validate_files(view,new))

    def test_long_names_and_reasons_get_wrapped_without_altering_text(self):
        f=self.source;f.packet['compounds'][0]['name']='原始名称保留'*30
        f.pairs[1]['reason_zh']='身份和结构资料缺失，保持原始原因。'*25
        view=second.build_view(f.run,f.result,f.packet);files=second.export(view,f.home/'wrapped')
        book=load_workbook(files['xlsx']);matrix=book['完整评分矩阵'];detail=book['原始评分与异常']
        self.assertEqual(matrix.cell(2,2).value,f.packet['compounds'][0]['name'])
        self.assertEqual(detail.cell(3,12).value,f.pairs[1]['reason_zh'])
        self.assertTrue(detail.cell(3,12).alignment.wrap_text);self.assertGreater(detail.row_dimensions[3].height,60)
        self.assertGreater(matrix.row_dimensions[2].height,30);book.close()


if __name__=='__main__':unittest.main()
