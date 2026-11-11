"""受体补救的实际HTTP契约；临时合成研究、原任务队列，不启动科学worker。"""
from hashlib import sha256
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from modulea.api.server import create_server
from modulea.config import Settings
from modulea.core.kernel import Kernel
from storage import new_id
from tests.modulea import test_system_receptor_rescue_core as fixture
from tests.modulea import test_plan_creation_http as http_fixture


class SystemReceptorRescueHttpTests(unittest.TestCase):
    close = http_fixture.PlanCreationHttpTests.close

    @classmethod
    def setUpClass(cls):
        """一次建立正常批准链合成研究；逐测试复制，不读实际研究或运行Vina。"""
        cls.seed = fixture.SystemReceptorRescueCoreTests('test_other_versions_keep_original_active_branch')
        cls.seed.setUp()
        cls.addClassCleanup(cls.seed.doCleanups)
        cls.sid = cls.seed.sid

    def setUp(self):
        """每项测试持有独立临时端口和runtime；子进程启动始终被隔离。"""
        self.temp = tempfile.TemporaryDirectory(prefix='receptor_rescue_http_')
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.root = folder / 'data'
        shutil.copytree(self.seed.root, self.root)
        tools, repair = folder / 'tools', folder / 'repair'
        tools.mkdir()
        repair.mkdir()
        self.settings = Settings(data_root=self.root, runtime_dir=folder / 'runtime',
                                 science_tools_root=tools, science_repair_packages=repair)
        self.w = Kernel(self.settings).workflow()
        self.home = self.w.location(self.sid)
        self.before = self.snapshot()
        self.server, self.app = create_server(self.settings, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        spawn_patch = patch.object(self.app.tasks, '_spawn')
        self.spawn = spawn_patch.start()
        self.addCleanup(spawn_patch.stop)
        self.path = f'/studies/{self.sid}/analysis-plan/receptor-rescue'
        value = self.w.analysis_plan_receptor_rescue_info(self.sid)
        self.body = {key: value[key] for key in ('expected_preparation_run_id', 'expected_scoring_run_id',
                                                'expected_input_hash')}
        self.body.update(request_id=new_id('rescue'), author='合成 HTTP 执行人 ',
                         note='明确本批原受体补救\n保持原说明。', confirmed=True)

    def tearDown(self):
        """读取和HTTP排队不得改写研究索引、源结果或任何归档字节。"""
        self.assertEqual(self.snapshot(), self.before)

    def snapshot(self):
        """逐文件记录合成研究SHA，runtime队列独立于研究事实。"""
        return {path.relative_to(self.home).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in self.home.rglob('*') if path.is_file()}

    def call(self, method, path, body=None, *, token=True, origin=None, host=None):
        """通过实际本机HTTP验证路由、安全保护、状态码和JSON原始字段。"""
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-ModuleA-Token'] = self.app.token if token is True else token
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            connection.request(method, '/api/v1' + path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_get_eligibility_is_read_only_and_does_not_load_scientific_tools(self):
        """无令牌读取资格保持原身份和指纹，不计算、准备、排队或签署复核。"""
        self.seed.science.configuration.reset_mock()
        self.seed.science.compute.reset_mock()
        for _ in range(2):
            status, value = self.call('GET', self.path, token=False)
            self.assertEqual(status, 200, value)
            self.assertTrue(value['enabled'], value)
            self.assertFalse(value['busy'])
            self.assertEqual(value['state'], 'ready')
            self.assertEqual(value['schema_version'], 'A06.system_rescue.1')
            for key in ('expected_preparation_run_id', 'expected_scoring_run_id', 'expected_input_hash'):
                self.assertEqual(value[key], self.body[key])
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()
        self.seed.science.configuration.assert_not_called()
        self.seed.science.compute.assert_not_called()

    def test_post_queues_exact_seven_field_request_without_running_science(self):
        """明确提交只写原队列；Unicode、空白和换行原样交worker，不添加隐式参数。"""
        self.seed.science.configuration.reset_mock()
        self.seed.science.compute.reset_mock()
        origin = f'http://127.0.0.1:{self.server.server_port}'
        status, value = self.call('POST', self.path + '/execute', self.body, origin=origin)
        self.assertEqual(status, 202, value)
        self.assertTrue(value['created'])
        self.assertEqual(value['task']['kind'], 'plan_system_receptor_rescue')
        queued = self.app.tasks._raw(value['task']['task_id'])
        self.assertEqual(json.loads(queued['payload']), self.body)
        self.assertEqual(queued['requested_by'], self.body['author'])
        self.assertEqual(queued['study_id'], self.sid)
        self.assertEqual(queued['state'], 'queued')
        self.assertEqual(len(self.app.tasks.list(self.sid)), 1)
        self.spawn.assert_called_once()
        self.seed.science.configuration.assert_not_called()
        self.seed.science.compute.assert_not_called()

    def test_missing_or_extra_fields_and_unconfirmed_request_never_queue(self):
        """所有七字段必需；路径、科学参数、对象及通过标记不能进入队列。"""
        requests = [dict(self.body, **change) for change in (
            {'confirmed': False}, {'confirmed': 1}, {'tools_root': 'outside'}, {'passed': True},
            {'repair_packages': 'outside'}, {'parameters': {}}, {'receptors': []}, {'author': '  '})]
        requests.extend({key: value for key, value in self.body.items() if key != missing} for missing in self.body)
        for body in requests:
            with self.subTest(fields=set(body)):
                status, value = self.call('POST', self.path + '/execute', body)
                self.assertEqual(status, 422, value)
                self.assertEqual(value['error']['code'], 'VALIDATION_FAILED')
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()

    def test_get_rejects_unknown_query_including_blank_values(self):
        """查询字段无论是否带值，都不能偷偷改变只读资格入口。"""
        for query in ('?unexpected=1', '?request_id=value', '?unexpected=', '?unexpected'):
            status, value = self.call('GET', self.path + query)
            self.assertEqual(status, 422, (query, value))
            self.assertEqual(value['error']['code'], 'VALIDATION_FAILED')
        self.assertEqual(self.app.tasks.list(self.sid), [])

    def test_post_rejects_unknown_query_including_blank_values(self):
        """POST不把额外查询串当作合法七字段请求的旁路参数。"""
        for query in ('?unexpected=1', '?request_id=value', '?unexpected=', '?unexpected'):
            status, value = self.call('POST', self.path + '/execute' + query, self.body)
            self.assertEqual(status, 422, (query, value))
            self.assertEqual(value['error']['code'], 'VALIDATION_FAILED')
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()

    def test_existing_task_blocks_get_and_post_without_second_queue_entry(self):
        """使用真实任务索引核对单研究占用；相同请求也不能并发启动第二worker。"""
        original, created = self.app.tasks.submit(self.sid, 'plan_system_receptor_rescue', self.body['author'], self.body)
        self.assertTrue(created)
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertTrue(value['busy'])
        self.assertFalse(value['enabled'])
        self.assertIn('请等待当前研究任务结束', value['blockers'])
        status, value = self.call('POST', self.path + '/execute', self.body)
        self.assertEqual(status, 409, value)
        self.assertEqual(value['error']['code'], 'GATE_BLOCKED')
        self.assertEqual([row['task_id'] for row in self.app.tasks.list(self.sid)], [original['task_id']])
        self.spawn.assert_called_once()

    def test_missing_server_tools_or_repair_packages_disable_and_block_submission(self):
        """服务器配置未齐时明确阻塞，不从客户端字段补路径或降级启动。"""
        for key in ('science_tools_root', 'science_repair_packages'):
            with self.subTest(setting=key), patch.object(self.settings, key, None):
                status, value = self.call('GET', self.path)
                self.assertEqual(status, 200, value)
                self.assertFalse(value['enabled'])
                self.assertTrue(any('未配置' in reason for reason in value['blockers']))
                status, value = self.call('POST', self.path + '/execute', self.body)
                self.assertEqual(status, 409, value)
                self.assertEqual(value['error']['code'], 'GATE_BLOCKED')
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()

    def test_standard_token_origin_and_host_protection_precede_submission(self):
        """原本机安全关口同样覆盖新POST，不读取正文后放宽令牌或来源。"""
        for headers, code in (({'token': False}, 'BAD_TOKEN'), ({'token': 'wrong-token'}, 'BAD_TOKEN'),
                              ({'origin': 'https://untrusted.example'}, 'FORBIDDEN_ORIGIN'),
                              ({'host': 'untrusted.example'}, 'FORBIDDEN_ORIGIN')):
            with self.subTest(headers=headers):
                status, value = self.call('POST', self.path + '/execute', self.body, **headers)
                self.assertEqual(status, 403, value)
                self.assertEqual(value['error']['code'], code)
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()

    def test_stale_preparation_scoring_and_source_hash_never_queue(self):
        """格式合法但已经不对应当前来源的请求按过期409拒绝。"""
        for change in ({'expected_input_hash': '0' * 64}, {'expected_preparation_run_id': new_id('run')},
                       {'expected_scoring_run_id': new_id('run')}):
            with self.subTest(change=change):
                status, value = self.call('POST', self.path + '/execute', dict(self.body, **change))
                self.assertEqual(status, 409, value)
                self.assertEqual(value['error']['code'], 'STALE_VERSION')
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
