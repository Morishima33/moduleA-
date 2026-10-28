"""新方案评分隔离验收：真实Vina、非默认参数、NA/失败、版本失效及独立复算。"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from contracts import ContractError
from storage import file_record, read_json, verified_file, write_json
from modulea.api.server import App
from modulea.api.errors import ApiError
from science_modules.analysis_protocol import compile_plan
from science_modules.a06 import plan_scoring as engine
from science_modules.a06.plan_scoring_results import validator
from science_modules.a06.plan_score_pair import top_pose
import tests.modulea.test_reviewable_preparation as fixture

TOOLS = Path(r'D:\codex-重大专项\moduleA\environment\a06_runtime_v1')


@unittest.skipUnless(TOOLS.is_dir(), '只读固定Vina科学环境不存在')
class PlanScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """合成上游/蛋白/口袋，真实Meeko和Vina；明确测试批准不代表真实研究。"""
        cls.base = fixture.ReviewablePreparationTests
        def custom_plan(specification):
            spec = deepcopy(specification)
            spec['parameters'].update({'a06.exhaustiveness': 4, 'a06.num_modes': 3,
                                       'a06.energy_range': 2, 'a06.seed': 7})
            return compile_plan(spec)
        with patch('modulea.core.analysis_plans.compile_plan', side_effect=custom_plan):
            cls.base.setUpClass()
        cls.addClassCleanup(cls.base.doClassCleanups)
        cls.w = cls.base.base.workflow
        cls.sid, cls.home = cls.base.sid, cls.base.home
        cls.prep = cls.w.publish_analysis_plan_a06_reviewable(cls.sid, {
            'expected_preparation_run_id': cls.base.source['run_id'],
            'expected_input_id': cls.base.base.input_record['input_id'],
            'request_id': 'reviewprep_' + uuid4().hex, 'reviewer': '隔离测试',
            'note': '仅对合成资料进行测试复核', 'confirmed': True})
        cls.review = cls.w.review(cls.sid, cls.prep['run_id'], 'approved', '合成测试复核者', '合成准备用于技术验收')
        cls.manifest_bytes = (cls.home / 'manifest.json').read_bytes()
        cls.manifest = cls.w.load(cls.sid)
        cls.settings = cls.base.base.base.settings
        cls.settings.science_python, cls.settings.science_tools_root = sys.executable, TOOLS

    def setUp(self):
        self.w = type(self.w)(self.w.root, self.w.validators)
        self.body = {'request_id': 'scoreq_' + uuid4().hex, 'expected_preparation_run_id': self.prep['run_id'],
                     'expected_preparation_review_id': self.review['review_id'],
                     'expected_input_id': self.base.base.input_record['input_id'], 'expected_a06_run_id': None,
                     'operator': '隔离测试执行者', 'note': '仅测试真实Vina技术链路', 'confirmed': True}
        self.addCleanup((self.home / 'manifest.json').write_bytes, self.manifest_bytes)

    def run_scoring(self):
        return engine.run(self.w, self.sid, self.body, TOOLS, lambda _: None)

    def test_actual_vina_nondefault_parameters_complete_matrix_and_export(self):
        result = self.run_scoring()
        self.assertEqual(result['outcome'], 'success', result['summary'])
        self.assertEqual((result['summary']['scored_pairs'], result['summary']['failed_pairs'], result['summary']['na_pairs']), (1, 0, 3))
        self.assertEqual(result['summary']['exploratory_scored_pairs'], 1)
        self.assertEqual(self.w.load(self.sid)['reviews'], self.manifest['reviews'])
        self.assertFalse(self.w.approved(self.w.load(self.sid), result['run_id']))
        row = result['tables']['plan_scoring_pairs'][0]
        self.assertEqual(row['state'], 'completed')
        packet = read_json(verified_file(self.home, result['tables']['scoring_packet'][0]))
        actual = read_json(verified_file(self.home, packet['pairs'][0]['execution']))
        command = read_json(verified_file(self.home, next(f for f in actual['files'] if f['path'].endswith('/command.json'))))
        args = command['arguments']
        for flag, value in (('--exhaustiveness', '4'), ('--num_modes', '3'), ('--energy_range', '2.0'), ('--seed', '7'), ('--cpu', '1')):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIsInstance(row['score'], float)
        from docking_redocking import _poses
        self.assertEqual(row['score'], _poses(verified_file(self.home, actual['pose']).read_text('ascii'))[0]['score_kcal_mol'])
        self.assertTrue(all(r['score'] is None and r['execution_path'] is None for r in result['tables']['plan_scoring_pairs'][1:]))
        app = App(self.settings)
        response = app.export_analysis_a06_scoring(SimpleNamespace(), self.sid)
        self.assertEqual(response[0], 'file')
        self.assertEqual(response[1].read_text('utf-8-sig').count('\n'), 5)
        view = app.views.module(self.sid, 'A06')
        self.assertEqual(view['state']['code'], 'review')

    def test_invalid_requests_and_old_windows_are_rejected_without_write(self):
        for body in (None, dict(self.body, seed=2), dict(self.body, confirmed=False), dict(self.body, operator=''),
                     dict(self.body, expected_preparation_run_id=self.base.source['run_id']),
                     dict(self.body, expected_preparation_review_id='review_' + uuid4().hex),
                     dict(self.body, expected_a06_run_id='run_' + uuid4().hex)):
            with self.subTest(body=body), self.assertRaises(ContractError):
                self.w.validate_analysis_plan_a06_scoring(self.sid, body)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), self.manifest_bytes)

    def test_no_approval_or_withdrawal_cannot_execute(self):
        self.w.review(self.sid, self.prep['run_id'], 'pending', '合成测试', '撤回准备', self.review['review_id'])
        self.assertFalse(self.w.analysis_plan_a06_scoring_info(self.sid)['enabled'])
        with self.assertRaises(ContractError):
            self.w.validate_analysis_plan_a06_scoring(self.sid, self.body)

    def test_same_request_does_not_repeat_actual_scoring(self):
        result = self.run_scoring()
        before = (self.home / 'manifest.json').read_bytes()
        with patch.object(engine, 'execute', side_effect=AssertionError('不得重复评分')):
            self.assertEqual(self.run_scoring(), result)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), before)
        self.body['note'] = '同编号改内容'
        with self.assertRaises(ContractError):
            self.w.validate_analysis_plan_a06_scoring(self.sid, self.body)

    def test_missing_tools_does_not_create_run(self):
        with self.assertRaises(ContractError):
            engine.run(self.w, self.sid, self.body, self.home / 'missing_tools', lambda _: None)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), self.manifest_bytes)

    def test_actual_worker_missing_tools_fails_without_fabricated_result(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from modulea.tasks.worker import run_a06_plan_scoring
        task = {'task_id': 'task_' + uuid4().hex, 'study_id': self.sid, 'payload': json.dumps(self.body)}
        manager = SimpleNamespace(update=lambda *a, **k: None)
        with patch.object(self.settings, 'science_tools_root', self.home / 'missing_fixed_tools'), \
             redirect_stdout(StringIO()), self.assertRaises(ValueError):
            run_a06_plan_scoring(self.settings, task, manager)
        self.assertEqual((self.home / 'manifest.json').read_bytes(), self.manifest_bytes)

    def test_process_failure_is_archived_failed_not_zero(self):
        actual_run = subprocess.run
        def fail(arguments, *args, **kwargs):
            if '--version' in arguments:
                return actual_run(arguments, *args, **kwargs)
            return subprocess.CompletedProcess(arguments, 1, 'synthetic failure test', 'synthetic tool error')
        with patch('subprocess.run', side_effect=fail):
            result = self.run_scoring()
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual((result['summary']['scored_pairs'], result['summary']['failed_pairs'], result['summary']['na_pairs']), (0, 1, 3))
        self.assertTrue(all(row['score'] is None for row in result['tables']['plan_scoring_pairs']))
        with self.assertRaises(ContractError):
            self.w.review(self.sid, result['run_id'], 'approved', '合成测试', '不能批准失败')
        with self.assertRaises(ContractError):
            self.w.validate_analysis_plan_a06_scoring(self.sid, self.body)

    def test_approval_withdrawn_during_execution_preserves_unpublished_files(self):
        actual_execute = engine.execute
        def withdraw(*args, **kwargs):
            value = actual_execute(*args, **kwargs)
            self.w.review(self.sid, self.prep['run_id'], 'pending', '合成测试', '计算期间撤回', self.review['review_id'])
            return value
        with patch.object(engine, 'execute', side_effect=withdraw), self.assertRaises(ContractError):
            self.run_scoring()
        manifest = self.w.load(self.sid)
        rid = manifest['current']['A06']
        self.assertIsNone(manifest['runs'][rid]['result_file'])
        self.assertTrue((self.home / 'runs/A06' / rid / 'plan_scoring/failure.json').is_file())
        self.assertTrue(list((self.home / 'runs/A06' / rid).rglob('poses.pdbqt')))

    def test_independent_validation_rejects_forged_score_and_csv(self):
        result = self.run_scoring()
        run = self.w.run(self.w.load(self.sid), result['run_id'])
        packet_ref = result['tables']['scoring_packet'][0]
        packet_path = verified_file(self.home, packet_ref)
        original = packet_path.read_bytes()
        self.addCleanup(packet_path.write_bytes, original)
        packet = json.loads(original)
        packet['pairs'][0]['score'] -= 10
        write_json(packet_path, packet, replace=True)
        tables = deepcopy(result['tables'])
        tables['scoring_packet'] = [file_record(self.home, packet_path, packet_ref['role'])]
        from science_modules.a06.plan_scoring_results import table_rows
        tables['plan_scoring_pairs'] = table_rows(packet['pairs'])
        with self.assertRaises(ContractError):
            self.w.validators['A06'](run, result['summary'], tables, [], 'success')
        packet_path.write_bytes(original)
        packet = json.loads(original)
        csv_path = verified_file(self.home, packet['matrix_csv'])
        csv_original = csv_path.read_bytes(); self.addCleanup(csv_path.write_bytes, csv_original)
        csv_path.write_bytes(csv_original + b'forged,row\n')
        old_csv = packet['matrix_csv']
        packet['matrix_csv'] = file_record(self.home, csv_path, old_csv['role'])
        packet['files'] = [packet['matrix_csv'] if ref == old_csv else ref for ref in packet['files']]
        write_json(packet_path, packet, replace=True)
        tables = deepcopy(result['tables'])
        tables['scoring_packet'] = [file_record(self.home, packet_path, packet_ref['role'])]
        with self.assertRaises(ContractError):
            self.w.validators['A06'](run, result['summary'], tables, [], 'success')

    def test_invalid_pose_geometry_identity_and_nan_never_become_scores(self):
        compound = self.base.base.source['compounds'][0]
        ref = next(f for f in compound['files'] if f['role'] == 'prepared_ligand')
        ligand = verified_file(self.home, ref).read_text('ascii')
        atoms = [line for line in ligand.splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
        config = self.w.validate_analysis_plan_a06_scoring(self.sid, self.body)['configuration']
        def output(lines, score='-1.25'):
            return 'MODEL 1\nREMARK VINA RESULT: ' + score + ' 0 0\n' + '\n'.join(lines) + '\nENDMDL\n'
        box = {'center': [0, 0, 0], 'size': [100, 100, 100]}
        valid = output(atoms)
        self.assertEqual(top_pose(ligand, valid, box, config)['score'], -1.25)
        outside = atoms[0][:30] + f'{9999:8.3f}' + atoms[0][38:]
        bad = [output(atoms, 'nan'), output(atoms + atoms[:1]), output([outside] + atoms[1:]),
               output([atoms[0][:77] + 'X'] + atoms[1:])]
        for text in bad:
            with self.subTest(text=text[:80]), self.assertRaises(ContractError):
                top_pose(ligand, text, box, config)

    def test_timeout_preserves_partial_logs_and_null_scores(self):
        actual_run = subprocess.run
        def timeout(arguments, *args, **kwargs):
            if '--version' in arguments:
                return actual_run(arguments, *args, **kwargs)
            raise subprocess.TimeoutExpired(arguments, 1800, output=b'partial timeout test log', stderr=b'timeout')
        with patch('subprocess.run', side_effect=timeout):
            result = self.run_scoring()
        self.assertEqual(result['outcome'], 'failed')
        packet = read_json(verified_file(self.home, result['tables']['scoring_packet'][0]))
        value = read_json(verified_file(self.home, packet['pairs'][0]['execution']))
        self.assertEqual(value['failure_kind'], 'timeout')
        self.assertIsNone(value['score'])
        stdout = next(ref for ref in value['files'] if ref['path'].endswith('/stdout.txt'))
        self.assertIn(b'partial timeout test log', verified_file(self.home, stdout).read_bytes())

    def test_archived_pose_tampering_rejects_read_and_export(self):
        result = self.run_scoring()
        packet = read_json(verified_file(self.home, result['tables']['scoring_packet'][0]))
        value = read_json(verified_file(self.home, packet['pairs'][0]['execution']))
        path = verified_file(self.home, value['pose'])
        before = path.read_bytes(); self.addCleanup(path.write_bytes, before)
        path.write_bytes(before + b'\ncorrupt')
        with self.assertRaises(ContractError):
            self.w.result(self.w.load(self.sid), result['run_id'])
        with self.assertRaises(ApiError):
            App(self.settings).export_analysis_a06_scoring(SimpleNamespace(), self.sid)

    def test_api_standard_library_only_and_unconfigured_tool_gate(self):
        script = """import json,sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from modulea.config import Settings
from modulea.core.kernel import Kernel
w=Kernel(Settings(data_root=Path(sys.argv[2]))).workflow()
assert w.analysis_plan_a06_scoring_info(sys.argv[3])['enabled']
assert not w.validate_analysis_plan_a06_scoring(sys.argv[3],json.loads(sys.argv[4]))['repeated']
assert not any(n in sys.modules for n in ('rdkit','numpy','meeko','docx'))
print('standard_library_only_passed')"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script, str(Path(__file__).resolve().parents[2] / 'src'),
                                 str(self.w.root), self.sid, json.dumps(self.body)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with patch.object(self.settings, 'science_tools_root', None):
            value = App(self.settings).get_analysis_a06_scoring(SimpleNamespace(), self.sid)
            self.assertFalse(value['enabled'])

    def test_old_scoring_and_report_cannot_bypass_new_protocol(self):
        with self.assertRaises(ContractError):
            self.w.begin(self.sid, 'A06', {}, {}, '禁止旧评分')
        result = self.run_scoring()
        self.w.review(self.sid, result['run_id'], 'approved', '合成测试', '仅批准测试评分')
        with self.assertRaises(ContractError):
            self.w.begin(self.sid, 'A07', {}, {}, '尚未接通的新报告')

    def test_independent_validator_rejects_boolean_summary_count(self):
        """True不能冒充成功数1；真实构型和其他字段保持，专门核对汇总数据类型。"""
        result = self.run_scoring()
        run = self.w.run(self.w.load(self.sid), result['run_id'])
        malformed = deepcopy(result['summary'])
        malformed['scored_pairs'] = True
        with self.assertRaises(ContractError):
            self.w.validators['A06'](run, malformed, result['tables'], [], 'success')

    def test_missing_vina_gates_module_and_post_without_creating_task(self):
        """使用真实有效准备检查模块页、资格接口与POST共同阻断，不只测试一个入口。"""
        with patch.object(self.settings, 'science_tools_root', self.home / 'missing_vina'):
            app = App(self.settings)
            view = app.views.module(self.sid, 'A06_PREP')
            self.assertFalse(view['plan_scoring']['enabled'])
            self.assertFalse(view['scoring_readiness']['scoring_allowed'])
            self.assertIn('工具文件不存在', view['plan_scoring']['reason_zh'])
            with patch.object(app.tasks, 'submit', side_effect=AssertionError('不得提交缺工具任务')) as submit:
                with self.assertRaises(ApiError) as error:
                    app.post_analysis_a06_scoring(SimpleNamespace(json=lambda: self.body), self.sid)
                self.assertEqual(error.exception.code, 'GATE_BLOCKED')
                submit.assert_not_called()
