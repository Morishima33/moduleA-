"""第二版补救实际HTTP集成；合成研究与临时端口，科学worker始终禁止启动。"""
from copy import deepcopy
import unittest
from unittest.mock import patch

from modulea.core import system_receptor_rescue as first
from modulea.core import system_receptor_rescue_v2 as second
from modulea.tasks import manager, resource_runner, worker
from modulea.tasks.system_receptor_rescue_v2 import run as v2_handler
from storage import new_id
from tests.modulea import test_system_receptor_rescue_http as original


class ReceptorRescueV2HttpTests(unittest.TestCase):
    """复用原HTTP真实队列和SHA检查夹具，不切换生产kernel或旧路由。"""
    close = original.SystemReceptorRescueHttpTests.close
    snapshot = original.SystemReceptorRescueHttpTests.snapshot
    call = original.SystemReceptorRescueHttpTests.call
    tearDown = original.SystemReceptorRescueHttpTests.tearDown

    @classmethod
    def setUpClass(cls):
        """只建立一次正常上游批准链；每项测试复制到自己的临时研究。"""
        original.SystemReceptorRescueHttpTests.setUpClass.__func__(cls)

    def setUp(self):
        """原kernel保持第一版；独立第二版API通过函数预检和既有队列运行。"""
        original.SystemReceptorRescueHttpTests.setUp(self)
        self.first_body = deepcopy(self.body)
        self.first_path = self.path
        self.path += '-v2'
        self.scientific = first.SystemReceptorRescueWorkflow(self.root, self.seed.w.validators)
        # 科学替身的合成产物也必须落本项复制后的临时研究，不写共享种子。
        home_patch = patch.object(self.seed, 'home', self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        value = second.info(self.w, self.sid)
        self.body = {key: value[key] for key in ('expected_preparation_run_id', 'expected_scoring_run_id', 'expected_input_hash')}
        self.body.update(request_id=new_id('rescue'), author='第二轮 HTTP 执行人 ',
                         note='明确采用第二轮流程\n原评分逐项保留。', confirmed=True)
        self.seed.science.compute.side_effect = self.seed.compute
        self.seed.science.configuration.reset_mock()
        self.seed.science.compute.reset_mock()

    def first_result(self, *, interrupted=False):
        """仅通过公开Workflow追加合成第一轮状态，科学依赖由原夹具替身替代。"""
        if interrupted:
            self.seed.science.compute.side_effect = RuntimeError('合成第一轮中断')
            with self.assertRaises(RuntimeError):
                self.scientific.execute_analysis_plan_receptor_rescue(self.sid, self.first_body,
                    tools=self.settings.science_tools_root, repair_packages=self.settings.science_repair_packages)
            result = None
        else:
            result = self.scientific.execute_analysis_plan_receptor_rescue(self.sid, self.first_body,
                tools=self.settings.science_tools_root, repair_packages=self.settings.science_repair_packages)
        self.before = self.snapshot()
        return result

    def assert_no_task(self):
        """所有拒绝分支既不登记任务，也不调用隔离子进程启动器。"""
        self.assertEqual(self.app.tasks.list(self.sid), [])
        self.spawn.assert_not_called()

    def test_get_v2_uses_original_baseline_schema_without_science_or_kernel_switch(self):
        """新资格读取直接绑定原路径评分，旧GET仍保留第一版协议。"""
        self.assertIsInstance(self.app.kernel.workflow(), second.SystemReceptorRescueV2Workflow)
        for _ in range(2):
            status, value = self.call('GET', self.path, token=False)
            self.assertEqual(status, 200, value)
            self.assertEqual(value['schema_version'], 'A06.system_rescue.2')
            self.assertTrue(value['enabled'], value)
            self.assertFalse(value['busy'])
            self.assertEqual(value['state'], 'ready')
            for key in ('expected_preparation_run_id', 'expected_scoring_run_id', 'expected_input_hash'):
                self.assertEqual(value[key], self.body[key])
        status, old = self.call('GET', self.first_path)
        self.assertEqual(status, 200, old)
        self.assertEqual(old['schema_version'], 'A06.system_rescue.1')
        self.seed.science.configuration.assert_not_called()
        self.seed.science.compute.assert_not_called()
        self.assert_no_task()

    def test_post_queues_exact_original_seven_fields_in_v2_heavy_task(self):
        """队列完整保留人名、换行和版本字段；新旧handler及资源预算分别登记。"""
        self.assertIn('plan_system_receptor_rescue_v2', manager.KINDS)
        self.assertNotIn('plan_system_receptor_rescue_v2', resource_runner.LIGHTWEIGHT)
        self.assertIs(worker.HANDLERS['plan_system_receptor_rescue_v2'], v2_handler)
        self.assertIn('plan_system_receptor_rescue', worker.HANDLERS)
        status, value = self.call('POST', self.path + '/execute', self.body,
                                  origin=f'http://127.0.0.1:{self.server.server_port}')
        self.assertEqual(status, 202, value)
        self.assertTrue(value['created'])
        self.assertEqual(value['task']['kind'], 'plan_system_receptor_rescue_v2')
        queued = self.app.tasks._raw(value['task']['task_id'])
        import json
        self.assertEqual(json.loads(queued['payload']), self.body)
        self.assertEqual(queued['requested_by'], self.body['author'])
        self.assertEqual(queued['state'], 'queued')
        self.assertEqual(len(self.app.tasks.list(self.sid)), 1)
        self.spawn.assert_called_once()
        self.seed.science.configuration.assert_not_called()
        self.seed.science.compute.assert_not_called()

    def test_get_and_post_reject_all_unknown_queries_including_blank_values(self):
        """空值查询串也必须在来源核验或排队前拒绝。"""
        for method, target in (('GET', self.path), ('POST', self.path + '/execute')):
            for query in ('?unexpected=1', '?request_id=other', '?unexpected=', '?unexpected'):
                with self.subTest(method=method, query=query):
                    status, value = self.call(method, target + query, self.body if method == 'POST' else None)
                    self.assertEqual(status, 422, value)
                    self.assertEqual(value['error']['code'], 'VALIDATION_FAILED')
        self.assert_no_task()

    def test_strict_seven_fields_confirmation_and_missing_keys_never_queue(self):
        """旧请求约束仍适用，第二版不接受模型路径、对象、工具或阈值覆盖。"""
        requests = [self.body | change for change in ({'confirmed': False}, {'confirmed': 1}, {'path': 'outside'},
            {'official_source_packages': []}, {'passed': True}, {'seed': 2}, {'target_id': 'HGNC:123'})]
        requests.extend({key: value for key, value in self.body.items() if key != missing} for missing in self.body)
        for request in requests:
            with self.subTest(keys=set(request)):
                status, value = self.call('POST', self.path + '/execute', request)
                self.assertEqual(status, 422, value)
                self.assertEqual(value['error']['code'], 'VALIDATION_FAILED')
        self.assert_no_task()

    def test_new_route_keeps_token_origin_and_host_protection(self):
        """安全拒绝发生在正文与队列处理之前，不能因新路由漏掉原保护。"""
        for headers, code in (({'token': False}, 'BAD_TOKEN'), ({'token': 'wrong'}, 'BAD_TOKEN'),
                              ({'origin': 'https://untrusted.example'}, 'FORBIDDEN_ORIGIN'),
                              ({'host': 'untrusted.example'}, 'FORBIDDEN_ORIGIN')):
            with self.subTest(headers=headers):
                status, value = self.call('POST', self.path + '/execute', self.body, **headers)
                self.assertEqual(status, 403, value)
                self.assertEqual(value['error']['code'], code)
        self.assert_no_task()

    def test_stale_hash_preparation_or_scoring_never_queue(self):
        """格式合法的过期版本按409拒绝，不从当前指针隐式更换来源。"""
        for change in ({'expected_input_hash': '0' * 64}, {'expected_preparation_run_id': new_id('run')},
                       {'expected_scoring_run_id': new_id('run')}):
            with self.subTest(change=change):
                status, value = self.call('POST', self.path + '/execute', self.body | change)
                self.assertEqual(status, 409, value)
                self.assertEqual(value['error']['code'], 'STALE_VERSION')
        self.assert_no_task()

    def test_busy_current_research_disables_get_and_refuses_second_queue_entry(self):
        """真实任务索引由第一版任务占用时，第二版仍受同研究单任务关口保护。"""
        queued, _ = self.app.tasks.submit(self.sid, 'plan_system_receptor_rescue', self.first_body['author'], self.first_body)
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertTrue(value['busy'])
        self.assertFalse(value['enabled'])
        status, value = self.call('POST', self.path + '/execute', self.body)
        self.assertEqual(status, 409, value)
        self.assertEqual(value['error']['code'], 'GATE_BLOCKED')
        self.assertEqual([task['task_id'] for task in self.app.tasks.list(self.sid)], [queued['task_id']])
        self.spawn.assert_called_once()

    def test_unfinished_first_returns_original_schema_and_same_explicit_request(self):
        """第一轮中断的GET2仍提供原请求；不能把原请求号送进第二版队列。"""
        self.first_result(interrupted=True)
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertEqual(value['schema_version'], 'A06.system_rescue.1')
        self.assertEqual(value['state'], 'incomplete')
        self.assertEqual(value['request'], self.first_body)
        self.assertEqual(value['current_run_id'], self.w.load(self.sid)['current']['A06'])
        status, value = self.call('POST', self.path + '/execute', self.first_body)
        self.assertEqual(status, 422, value)
        self.assert_no_task()

    def test_completed_first_enables_explicit_second_bound_to_that_result(self):
        """第一轮完整归档后才显示第二版，原评分与所有人工记录继续保留。"""
        result = self.first_result()
        before = self.w.load(self.sid)
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertEqual(value['schema_version'], 'A06.system_rescue.2')
        self.assertTrue(value['enabled'], value)
        self.assertEqual(value['expected_scoring_run_id'], result['run_id'])
        request = {key: value[key] for key in ('expected_preparation_run_id', 'expected_scoring_run_id', 'expected_input_hash')} | {
            'request_id': new_id('rescue'), 'author': '明确第二轮', 'note': '第一轮后补救剩余对象', 'confirmed': True}
        status, submitted = self.call('POST', self.path + '/execute', request)
        self.assertEqual(status, 202, submitted)
        self.assertEqual(submitted['task']['kind'], 'plan_system_receptor_rescue_v2')
        self.assertEqual(self.w.load(self.sid), before)

    def test_trashed_research_get_is_blocked_and_post_is_423(self):
        """沿公开回收站操作变为只读后，新接口不可借旧指纹排队。"""
        self.w.set_trashed(self.sid, True, '合成第二轮HTTP', '核对回收站只读')
        self.before = self.snapshot()
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertFalse(value['enabled'])
        self.assertEqual(value['state'], 'blocked')
        status, value = self.call('POST', self.path + '/execute', self.body)
        self.assertEqual(status, 423, value)
        self.assertEqual(value['error']['code'], 'TRASHED_READONLY')
        self.assert_no_task()

    def test_rejected_preparation_disables_and_blocks_without_new_review_or_task(self):
        """真实原准备批准撤回为退回后，旧第二轮指纹不再有效。"""
        m = self.w.load(self.sid)
        prep_id = m['current']['A06_PREP']
        review = self.w.latest_review(m, self.w.run(m, prep_id)['artifact_id'])
        self.w.review(self.sid, prep_id, 'rejected', '合成独立复核', '明确退回原准备', expected_review=review['review_id'])
        self.before = self.snapshot()
        status, value = self.call('GET', self.path)
        self.assertEqual(status, 200, value)
        self.assertFalse(value['enabled'])
        status, value = self.call('POST', self.path + '/execute', self.body)
        self.assertEqual(status, 409, value)
        self.assert_no_task()


if __name__ == '__main__':
    unittest.main()
