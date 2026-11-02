"""生产全NA系统准备的派生导出及人工暂停/回收站保护；无外部请求或评分。"""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import verified_file
from modulea.core.kernel import full_workflow
from science_modules.a06 import plan_preparation_v2 as prep,system_exports_v2 as science
from tests.modulea import test_system_preparation as upstream
from tests.modulea.plan_report_nonempty_fixture import unavailable_sources


class SystemExportsPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        upstream.SystemPreparationTests.setUpClass.__func__(cls)
        w=full_workflow(cls.base)
        with patch.object(prep,'connect',side_effect=unavailable_sources):
            cls.prepared=w.execute_analysis_plan_system_stage(cls.sid,{
                'batch_id':cls.batch_id,'stage':'A06_PREP','expected_current_run_id':None},tools=cls.tools)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_exports_na_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.base,self.root);self.w=full_workflow(self.root)
        self.before=self.w.load(self.sid);info=self.w.analysis_plan_system_exports_info(self.sid)
        self.body={key:info[key] for key in ('expected_module','expected_run_id','expected_input_hash')}|{
            'request_id':'sysexportreq_'+uuid4().hex,'author':'明确合成全NA导出','note':'缺结构保持NA，不运行Vina','confirmed':True}

    def test_all_na_preparation_exports_actual_na_without_starting_score_or_reviews(self):
        record=self.w.export_analysis_plan_system_results(self.sid,self.body)
        self.assertEqual(record['source_module'],'A06_PREP')
        from openpyxl import load_workbook
        path=verified_file(self.w.location(self.sid),record['formats']['xlsx'])
        book=load_workbook(path,data_only=True);matrix=book['完整评分矩阵']
        self.assertEqual([matrix.cell(row,3).value for row in (2,3)],['NA','NA']);book.close()
        after=self.w.load(self.sid)
        for key in ('runs','current','reviews'):self.assertEqual(after.get(key),self.before.get(key))
        self.assertNotIn('A06',after['current'])

    def test_hold_during_export_keeps_files_and_diagnostics_without_publication(self):
        original=science.export
        def pause(*args):
            files=original(*args)
            self.w.review(self.sid,self.prepared['run_id'],'pending','明确合成测试','生成期间暂存')
            return files
        with patch.object(science,'export',side_effect=pause),self.assertRaises(ContractError):
            self.w.export_analysis_plan_system_results(self.sid,self.body)
        m=self.w.load(self.sid);self.assertNotIn('analysis_plan_system_export_records',m)
        self.assertEqual(len(m['analysis_plan_system_export_failures']),1)
        self.assertEqual(len(list((self.w.location(self.sid)/'decisions/analysis_plans/system_exports').rglob('*.xlsx'))),1)


if __name__=='__main__':unittest.main()
