"""修订版资格及评分进入既有报告和导出时保留原值。"""
from copy import deepcopy
import unittest

from science_modules.a06 import system_exports_paths, system_exports_v2
from tests.modulea import test_system_exports as fixture


class RepairedDeliveryTests(unittest.TestCase):
    def test_repaired_score_uses_same_matrix_as_previous_protocol(self):
        source = fixture.SystemExportsTests('runTest')
        source.setUp()
        self.addCleanup(source.doCleanups)
        old = system_exports_v2.build_view(source.run, source.result, source.packet)
        run = deepcopy(source.run)
        run['config']['version'] = 'A06.system_scoring_paths.1'
        view = system_exports_paths.build_view(run, source.result, source.packet)
        self.assertEqual(view['science_version'], 'A06.system_scoring_paths.1')
        self.assertEqual(dict(view, science_version=old['science_version']), old)
