"""第二轮代码复查的缺陷复现：真实工具可用性、任务状态竞争和可选追溯材料。"""
from pathlib import Path
from copy import deepcopy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from contracts import ContractError
from storage import file_record, write_json
from modulea.api import plan_scoring_view, analysis_reference_preparation_view, trace_actions
from modulea.api.errors import ApiError


class FollowupReviewTests(unittest.TestCase):
    def setUp(self):
        """HTTP能力测试只模拟已通过科学资格的返回值，不创建研究或执行器。"""
        self.temp = tempfile.TemporaryDirectory(prefix='followup_review_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = Mock()
        self.workflow.analysis_plan_a06_scoring_info.return_value = {
            'supported': True, 'enabled': True, 'execution_available': True, 'blockers': [], 'reason_zh': '测试资格'}
        self.workflow.analysis_plan_a06_scoring_readiness.return_value = {
            'supported': True, 'scoring_allowed': True, 'execution_available': True, 'blockers': [], 'reason_zh': '测试资格'}
        self.workflow.validate_analysis_plan_a06_scoring.return_value = {'repeated': False}
        self.tasks = Mock(); self.tasks.active_for.return_value = None
        self.app = SimpleNamespace(kernel=SimpleNamespace(workflow=lambda: self.workflow), tasks=self.tasks,
                                   settings=SimpleNamespace(science_tools_root=self.root))
        self.req = SimpleNamespace(json=lambda: {'operator': '隔离测试'})

    def test_configured_directory_without_vina_disables_execution(self):
        value = plan_scoring_view.info(self.app, self.req, 'study_test')
        self.assertFalse(value['enabled'])
        self.assertFalse(value['execution_available'])
        self.assertTrue(value['blockers'])

    def test_missing_vina_cannot_submit_background_task(self):
        self.tasks.submit.side_effect = AssertionError('缺工具不得创建注定失败的任务')
        with self.assertRaises(ApiError) as error:
            plan_scoring_view.submit(self.app, self.req, 'study_test')
        self.assertEqual(error.exception.code, 'GATE_BLOCKED')
        self.tasks.submit.assert_not_called()

    def test_scoring_readiness_uses_same_real_tool_gate(self):
        value = analysis_reference_preparation_view.scoring_readiness(self.app, self.req, 'study_test')
        self.assertFalse(value['scoring_allowed'])
        self.assertFalse(value['execution_available'])

    def test_finishing_task_does_not_produce_false_missing_config_reason(self):
        """同一响应只读一次任务状态，避免任务刚结束时说明与条件不一致。"""
        self.tasks.active_for.side_effect = [{'state': 'running'}, None]
        value = plan_scoring_view.info(self.app, self.req, 'study_test')
        self.assertFalse(value['enabled'])
        self.assertIn('后台任务', value['reason_zh'])
        self.tasks.active_for.assert_called_once()

    def test_optional_review_packet_failure_keeps_trace_summary_available(self):
        workflow = Mock()
        workflow.analysis_plan_a06_review_packet.side_effect = ContractError('复核包校验失败')
        app = SimpleNamespace(kernel=SimpleNamespace(read_workflow=lambda: workflow))
        payload = {'trace_version': 'trace-test', 'workflow_profile': None, 'current': {},
                   'modules': [], 'plans': [], 'file_count': 0}
        with patch.object(trace_actions, 'build_trace', return_value=payload):
            value = trace_actions.trace_summary(app, SimpleNamespace(), 'study_test')
        self.assertFalse(value['a06_review_packet_available'])
        self.assertTrue(value['read_only'])

    def pair_fixture(self):
        """纯合成解析样本，不启动程序，仅复现Python布尔值与数字相等的边界。"""
        from science_modules.a06.plan_score_pair import arguments
        line = list(' ' * 78)
        line[0:6] = 'ATOM  '; line[6:11] = f'{1:5d}'
        for start in (30, 38, 46): line[start:start+8] = f'{0:8.3f}'
        line[77] = 'C'
        atom = ''.join(line)
        ligand, receptor, binary = (self.root / name for name in ('ligand.pdbqt', 'receptor.pdbqt', 'vina.exe'))
        ligand.write_text(atom + '\n', encoding='ascii'); receptor.write_text(atom + '\n', encoding='ascii')
        binary.write_bytes(b'pure-parser-fixture-never-executed')
        folder = self.root / 'pair'; folder.mkdir()
        pose = folder / 'poses.pdbqt'
        pose.write_text('MODEL 1\nREMARK VINA RESULT: 1.0 0 0\n' + atom + '\nENDMDL\n', encoding='ascii')
        config = {'vina_parameters': {'scoring':'vina','exhaustiveness':4,'num_modes':3,'energy_range_kcal_mol':2,'seed':7},
                  'cpu_per_pair':1, 'timeout_seconds':1800}
        box = {'center':[0,0,0], 'size':[10,10,10]}
        lref, rref = file_record(self.root, ligand, 'prepared_ligand'), file_record(self.root, receptor, 'receptor')
        command = {'configuration':config, 'ligand':lref, 'receptor':rref, 'box':box,
                   'executable':file_record(self.root,binary,'scoring_vina'),
                   'arguments':arguments(binary,receptor,ligand,box,pose,config)}
        write_json(folder / 'command.json', command)
        for name in ('stdout.txt','stderr.txt'): (folder/name).write_text('',encoding='utf-8')
        value = {'started_at':'fixture','finished_at':'fixture','state':'completed','score':1.0,'returncode':0,
                 'mode_count':1,'top_mode':1,'failure_kind':None,'reason_zh':'',
                 'files':[file_record(self.root,folder/name,'scoring_'+Path(name).stem) for name in ('command.json','stdout.txt','stderr.txt')]}
        value['pose'] = file_record(self.root,pose,'scoring_pose'); value['files'].append(value['pose'])
        return folder, binary, lref, rref, box, config, value

    def test_numeric_execution_fields_reject_booleans(self):
        from science_modules.a06.plan_score_pair import validate
        folder, binary, ligand, receptor, box, config, valid = self.pair_fixture()
        path = folder / 'execution.json'
        write_json(path, valid)
        validate(self.root, file_record(self.root,path,'scoring_execution'),binary,ligand,receptor,box,config)
        for key, bad in (('score',True),('mode_count',True),('top_mode',True),('returncode',False)):
            value = deepcopy(valid); value[key] = bad; write_json(path,value,replace=True)
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate(self.root,file_record(self.root,path,'scoring_execution'),binary,ligand,receptor,box,config)

    def test_missing_command_index_is_a_contract_error(self):
        from science_modules.a06.plan_score_pair import validate
        folder, binary, ligand, receptor, box, config, value = self.pair_fixture()
        value['files'] = [ref for ref in value['files'] if not ref['path'].endswith('/command.json')]
        path=folder/'execution.json'; write_json(path,value)
        with self.assertRaises(ContractError):
            validate(self.root,file_record(self.root,path,'scoring_execution'),binary,ligand,receptor,box,config)
