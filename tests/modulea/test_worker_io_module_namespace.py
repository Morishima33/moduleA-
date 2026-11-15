"""完整工厂及旧FunctionType模块字典兼容；只读临时根，不执行报告或科学计算。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import storage
from modulea.core import bounded_evidence
from modulea.core.kernel import full_workflow
from modulea.core.worker_io import WorkerIO


class WorkerModuleNamespaceTests(unittest.TestCase):
    def test_vars_module_keeps_original_names_and_bound_io(self):
        """旧报告通过vars(module)构造函数全局字典，不能只拿到代理内部字段。"""
        adapter=WorkerIO()
        self.addCleanup(adapter.close)
        original=dict(vars(storage))
        namespace=dict(vars(adapter.value(storage)))
        self.assertEqual(set(namespace),set(original))
        self.assertIs(namespace['verified_file'],bounded_evidence.verified_file)
        self.assertIs(namespace['file_record'],bounded_evidence.file_record)
        self.assertEqual(vars(storage),original)

    def test_complete_production_factory_keeps_legacy_report_globals(self):
        """构造真实全部生产validator，覆盖旧报告的多层FunctionType绑定。"""
        from science_modules.a07 import compact_enrichment_reports as legacy
        original=dict(vars(legacy))
        adapter=WorkerIO()
        self.addCleanup(adapter.close)
        with TemporaryDirectory() as temp:
            root=Path(temp)
            workflow=adapter.wrap(adapter.bind(full_workflow)(root))
            self.assertEqual(workflow.root,root)
            self.assertTrue({'A01','A02','A03','A04','A05','A06','A07'}<=set(workflow.validators))
            self.assertFalse(any(root.iterdir()))
        self.assertEqual(vars(legacy),original)


if __name__=='__main__':unittest.main()
