"""隔离Workflow发布验证：原准备、资格及人工复核保持，修订前后均走规范。"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from contracts import ContractError
from storage import file_record, new_id, verified_file
from modulea.core.analysis_plans import AnalysisPlanWorkflow
from modulea.core.kernel import full_workflow
from modulea.core import system_decisions
from science_modules.a06 import plan_preparation_v2 as legacy, receptor_cli_paths
from tests.modulea import test_system_decisions as upstream
from tests.modulea.preparation_object_fixture import ObjectSources


class SystemQualificationPathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(AnalysisPlanWorkflow, 'start_analysis_plan_system_batch',
                          AnalysisPlanWorkflow.start_analysis_plan_recoverable_system_batch):
            upstream.SystemDecisionTests.setUpClass.__func__(cls)
        w = full_workflow(cls.base)
        for stage in ('A04_SELECTION', 'A06_INPUT'):
            w.execute_analysis_plan_system_decision(cls.sid, {'batch_id': cls.batch_id, 'stage': stage,
                                                              'expected_decision_id': None})
        cls.tools = Path(os.environ.get('MODULEA_A06_TOOLS', 'D:/codex-重大专项/moduleA/environment/a06_runtime_v1'))

    def test_public_repair_publishes_new_qualified_result_and_preserves_old(self):
        root = Path(tempfile.mkdtemp(prefix='path_publication_')) / 'data'
        shutil.copytree(self.base, root)
        w = full_workflow(root)
        m = w.load(self.sid)
        home = w.location(self.sid)
        fixed = system_decisions.current(w, m, self.batch_id, 'A06_INPUT')[1]['payload']
        fixture = ObjectSources(fixed)

        def old_attempt(home, source, row, spec, number, folder, tools, progress, **kwargs):
            evidence = fixture.attempt(home, source, row, spec, number, folder, tools, progress, **kwargs)
            target = folder / 'receptors' / (row['symbol'] + '_input.pdb')
            target.parent.mkdir()
            target.write_bytes(verified_file(home, evidence['predicted_pocket']['input_pdb']).read_bytes())
            evidence['files'].append(file_record(home, target, 'quality_evidence'))
            evidence.pop('receptor')
            evidence.update(receptor_ready=False, error_zh='[WinError 267] 目录名称无效。')
            return evidence

        with patch.object(legacy, 'connect', side_effect=fixture.connect), \
                patch.object(legacy, 'attempt', side_effect=old_attempt):
            prep = w.execute_analysis_plan_system_stage(self.sid, {'batch_id': self.batch_id, 'stage': 'A06_PREP',
                'expected_current_run_id': None}, tools=self.tools)
        qualified = w.qualify_analysis_plan_system_preparation(self.sid, {
            'batch_id': self.batch_id, 'expected_preparation_run_id': prep['run_id']})
        before = w.load(self.sid)
        source = before['runs'][qualified['run_id']]
        self.assertEqual(qualified['summary']['ready_pairs'], 0)
        body = {'batch_id': self.batch_id, 'expected_preparation_run_id': qualified['run_id'],
                'expected_result_sha256': source['result_file']['sha256'], 'request_id': new_id('receptorpathrepair')}

        def cli(arguments, **kwargs):
            if 'meeko.cli.mk_prepare_receptor' not in arguments:
                return original_run(arguments, **kwargs)
            input_text = Path(arguments[4]).read_text('ascii')
            lines = [line[:70] + ' 0.000 C' for line in input_text.splitlines() if line.startswith('ATOM')]
            Path(arguments[6] + '.pdbqt').write_text('\n'.join(lines) + '\n', 'ascii')
            return subprocess.CompletedProcess(arguments, 0, 'synthetic Meeko', '')

        original_run = subprocess.run
        with patch.object(receptor_cli_paths.subprocess, 'run', side_effect=cli) as launch:
            with self.assertRaises(ContractError):
                w.repair_analysis_plan_system_receptor_paths(self.sid, dict(body, expected_result_sha256='bad'), tools=self.tools)
            launch.assert_not_called()
            repaired = w.repair_analysis_plan_system_receptor_paths(self.sid, body, tools=self.tools)
            meeko_calls = sum('meeko.cli.mk_prepare_receptor' in call.args[0] for call in launch.call_args_list)
            self.assertEqual(meeko_calls, repaired['summary']['path_repair_attempts'])
            self.assertEqual(w.repair_analysis_plan_system_receptor_paths(self.sid, body, tools=self.tools), repaired)
            self.assertEqual(sum('meeko.cli.mk_prepare_receptor' in c.args[0] for c in launch.call_args_list), meeko_calls)
        after = w.load(self.sid)
        run = w.run(after, repaired['run_id'])
        self.assertEqual(run['config']['version'], 'A06.system_qualification_paths.1')
        self.assertEqual(after['runs'][qualified['run_id']], source)
        self.assertEqual(after['reviews'], before['reviews'])
        self.assertEqual(repaired['summary']['pair_count'], qualified['summary']['pair_count'])
        self.assertGreater(repaired['summary']['ready_pairs'], 0)
        self.assertTrue(w.active(after, repaired['run_id']))
        self.assertFalse(w.approved(after, repaired['run_id']))
        self.assertEqual(after['current'].get('A06'), before['current'].get('A06'))
        with self.assertRaises(ContractError):
            w.validators['A06_PREP'](run, dict(repaired['summary'], ready_pairs=-1),
                                     repaired['tables'], [], 'success')
        scored = w.score_analysis_plan_system_preparation(self.sid, {'batch_id': self.batch_id,
            'expected_preparation_run_id': repaired['run_id'], 'expected_scoring_run_id': None}, tools=self.tools)
        final = w.load(self.sid)
        scored_run = w.run(final, scored['run_id'])
        self.assertEqual(scored_run['config']['version'], 'A06.system_scoring_paths.1')
        self.assertEqual(scored_run['parent_runs'], {'A06_PREP': repaired['run_id']})
        self.assertEqual(scored['summary']['pair_count'], repaired['summary']['pair_count'])
        self.assertGreater(scored['summary']['scored_pairs'], 0)
        self.assertEqual(final['reviews'], before['reviews'])
        self.assertTrue(w.active(final, scored['run_id']))


if __name__ == '__main__':
    unittest.main()
