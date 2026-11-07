"""本机服务交付的隔离HTTP回归：只启动短时临时监听，不访问或停止真实工作台。"""
from contextlib import ExitStack
from datetime import datetime
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from modulea.api.server import API_CSP, create_server
from modulea.config import Settings


class ServiceDeliveryHttpTests(TestCase):
    """只用最小虚构源码、静态文件和独立运行目录，不建立研究或科学结果。"""

    def setUp(self):
        """准备能计算启动签名的临时工程，数据目录仅放不可变测试标记。"""
        self.temp = TemporaryDirectory(prefix='service_delivery_http_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root/'project'
        self.static = self.project/'frontend'
        self.data = self.root/'data'
        self.runtime = self.root/'runtime'
        for name in ('src/modulea/entry.py', 'src/science_modules/a/model.py', 'src/legacy.py'):
            path = self.project/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# explicit synthetic service source\n', encoding='utf-8')
        (self.static/'assets').mkdir(parents=True)
        (self.static/'index.html').write_text(
            '<!doctype html><html><head><link rel="stylesheet" href="/assets/app.css"></head>'
            '<body><script type="module" src="/assets/app.js"></script></body></html>', encoding='utf-8')
        (self.static/'assets/app.js').write_text('globalThis.syntheticService = true;\n', encoding='utf-8')
        (self.static/'assets/app.css').write_text('body { margin: 0; }\n', encoding='utf-8')
        self.data.mkdir()
        (self.data/'readonly_probe.bin').write_bytes(b'EXPLICIT_SYNTHETIC_DATA_MUST_STAY_UNCHANGED')
        self.settings = Settings(project_root=self.project, data_root=self.data,
                                 runtime_dir=self.runtime, static_dir=self.static)

    def server(self, settings=None, port=0):
        """启动并最终关闭自己持有的临时服务，模拟CLI退出后的socket清理。"""
        server, app = create_server(settings or self.settings, port)

        def serve():
            """有界测试只运行本实例；shutdown后在原线程关闭本监听。"""
            try:
                server.serve_forever(poll_interval=.02)
            finally:
                server.server_close()

        thread = Thread(target=serve, daemon=True)
        handle = SimpleNamespace(server=server, app=app, thread=thread)

        def close():
            """清理只作用于测试持有的server对象，不按PID结束任何进程。"""
            if thread.is_alive():
                server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        handle.close = close
        thread.start()
        self.addCleanup(close)
        return handle

    def call(self, handle, method, path, body=None, *, token=False, origin=None, host=None):
        """实际HTTP请求保留原响应头；只连接本测试已经创建的随机端口。"""
        connection = http.client.HTTPConnection('127.0.0.1', handle.server.server_port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-ModuleA-Token'] = handle.app.token
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        try:
            connection.request(method, path, None if method == 'GET' else json.dumps(body), headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw), dict(response.getheaders())
        finally:
            connection.close()

    def health(self, handle):
        """健康读取不带操作令牌，也不调用研究或科学接口。"""
        status, value, headers = self.call(handle, 'GET', '/api/v1/health')
        self.assertEqual(status, 200, value)
        return value, headers

    def data_snapshot(self, folder=None):
        """逐字节比较临时数据根，服务管理不能改研究或测试标记。"""
        folder = folder or self.data
        return {path.relative_to(folder).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in folder.rglob('*') if path.is_file()}

    def stop_body(self, handle):
        """从目标实例本身取得不可猜测的实例编号，再明确提出停止。"""
        value, _ = self.health(handle)
        return {'instance_id': value['instance_id'], 'confirmed': True}

    def test_health_is_fast_read_only_tokenless_and_has_canonical_identity(self):
        """健康检查不创建Workflow、研究视图或任务，且保留原HTTP安全头。"""
        handle = self.server()
        before = self.data_snapshot()
        with ExitStack() as stack:
            for name in ('workflow', 'read_workflow', 'display_workflow'):
                stack.enter_context(patch.object(handle.app.kernel, name, side_effect=AssertionError('health must not load Workflow')))
            for name in ('_snapshot', '_manifest', 'study_cards', 'study', 'module'):
                stack.enter_context(patch.object(handle.app.views, name, side_effect=AssertionError('health must not load study views')))
            for name in ('submit', '_spawn', 'list'):
                stack.enter_context(patch.object(handle.app.tasks, name, side_effect=AssertionError('health must not access tasks')))
            started = time.monotonic()
            for _ in range(3):
                value, headers = self.health(handle)
            self.assertLess(time.monotonic()-started, 3.0, '轻量健康检查不能等待科学视图或长任务')
        self.assertEqual(value['schema_version'], 'ModuleA.local_service.1')
        self.assertRegex(value['instance_id'], r'^service_[0-9a-f]{32}$')
        self.assertEqual(value['pid'], os.getpid())
        self.assertEqual(value['port'], handle.server.server_port)
        self.assertIsNotNone(datetime.fromisoformat(value['started_at']).utcoffset())
        for key in ('project_root', 'data_root', 'runtime_dir', 'static_dir'):
            self.assertEqual(value[key], str(Path(getattr(self.settings, key)).resolve()))
        self.assertRegex(value['code_signature'], r'^[0-9a-f]{64}$')
        self.assertIs(value['scientific_validation_performed'], False)
        self.assertNotIn('token', value)
        self.assertNotIn(handle.app.token, json.dumps(value))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Content-Security-Policy'], API_CSP)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.data_snapshot(), before)
        self.assertEqual(handle.app.tasks.list(), [])

    def test_health_retains_strict_host_validation(self):
        """即使免令牌读取健康信息，也不能接受其它Host进行DNS重绑定。"""
        handle = self.server()
        status, value, _ = self.call(handle, 'GET', '/api/v1/health', host='untrusted.example')
        self.assertEqual(status, 403, value)
        status, value, _ = self.call(handle, 'GET', '/api/v1/health', host=f'localhost:{handle.server.server_port}')
        self.assertEqual(status, 200, value)

    def test_startup_signature_stays_fixed_while_frontend_is_rechecked(self):
        """运行中只动态检查前端；源码修改不能被健康响应冒充已经重新加载。"""
        handle = self.server()
        initial, _ = self.health(handle)
        self.assertTrue(initial['frontend']['ready'])
        self.assertEqual(initial['frontend']['index_sha256'], sha256((self.static/'index.html').read_bytes()).hexdigest())
        (self.project/'src/modulea/entry.py').write_text('# explicitly changed synthetic source\n', encoding='utf-8')
        (self.static/'assets/app.js').write_text('globalThis.syntheticService = "changed";\n', encoding='utf-8')
        with patch('modulea.service_identity.implementation_signature', side_effect=AssertionError('health must not rescan startup source')):
            changed, _ = self.health(handle)
        self.assertEqual(changed['code_signature'], initial['code_signature'])
        self.assertEqual(changed['instance_id'], initial['instance_id'])
        self.assertEqual(changed['started_at'], initial['started_at'])
        asset = next(row for row in changed['frontend']['assets'] if row['path'] == 'assets/app.js')
        self.assertEqual(asset['sha256'], sha256((self.static/'assets/app.js').read_bytes()).hexdigest())
        self.assertEqual(asset['bytes'], (self.static/'assets/app.js').stat().st_size)
        (self.static/'assets/app.css').unlink()
        missing, _ = self.health(handle)
        self.assertEqual(missing['code_signature'], initial['code_signature'])
        self.assertFalse(missing['frontend']['ready'])
        self.assertTrue(missing['frontend']['errors_zh'])
        self.assertIn('assets/app.css', ' '.join(missing['frontend']['errors_zh']))

    def test_missing_frontend_is_reported_without_breaking_health(self):
        """服务仍能说明身份，但未配置或缺入口时明确标为前端未就绪。"""
        for static in (None, self.project/'missing_frontend'):
            with self.subTest(static=static):
                settings = Settings(project_root=self.project, data_root=self.data,
                                    runtime_dir=self.root/('runtime_none' if static is None else 'runtime_missing'), static_dir=static)
                handle = self.server(settings)
                value, _ = self.health(handle)
                self.assertFalse(value['frontend']['ready'])
                self.assertTrue(value['frontend']['errors_zh'])
                self.assertIsNone(value['frontend']['index_sha256'])

    def test_restart_changes_instance_even_on_same_port_and_process(self):
        """实例编号区分重启，不能把相同PID/端口当作同一个已核对服务。"""
        first = self.server()
        initial, _ = self.health(first)
        port = first.server.server_port
        first.close()
        second = self.server(port=port)
        restarted, _ = self.health(second)
        self.assertNotEqual(restarted['instance_id'], initial['instance_id'])
        self.assertNotEqual(restarted['started_at'], initial['started_at'])
        self.assertEqual(restarted['pid'], initial['pid'])
        self.assertEqual(restarted['port'], initial['port'])
        self.assertEqual(restarted['code_signature'], initial['code_signature'])

    def test_stop_requires_token_origin_and_exact_confirmed_instance_fields(self):
        """非法停止请求不能影响监听、任务或数据，PID和路径不能替代实例身份。"""
        handle = self.server()
        body = self.stop_body(handle)
        before = self.data_snapshot()
        status, value, _ = self.call(handle, 'GET', '/api/v1/service/stop')
        self.assertEqual(status, 404, value)
        for token, origin in ((False, None), (True, 'https://untrusted.example')):
            status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', body, token=token, origin=origin)
            self.assertEqual(status, 403, value)
        # 非对象JSON沿原Request规则返回400；对象缺字段或确认无效由新端点返回422。
        status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', None, token=True)
        self.assertEqual(status, 400, value)
        invalid = [{}, {'confirmed': True}, {'instance_id': body['instance_id']},
                   body | {'confirmed': False}, body | {'confirmed': 1}, body | {'confirmed': 'true'},
                   body | {'pid': os.getpid()}, body | {'data_root': str(self.data)}, body | {'confirmed': None},
                   {'service_id': body['instance_id'], 'confirmed': True}]
        for value in invalid:
            with self.subTest(value=value):
                status, result, _ = self.call(handle, 'POST', '/api/v1/service/stop', value, token=True)
                self.assertEqual(status, 422, result)
        status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop',
                                    body | {'instance_id': 'service_'+uuid4().hex}, token=True)
        self.assertEqual(status, 409, value)
        current, _ = self.health(handle)
        self.assertEqual(current['instance_id'], body['instance_id'])
        self.assertTrue(handle.thread.is_alive())
        self.assertEqual(handle.app.tasks.list(), [])
        self.assertEqual(self.data_snapshot(), before)

    def test_any_active_runtime_task_blocks_stop_without_changing_tasks(self):
        """另一数据根共享runtime的排队/运行任务同样阻断，不能停服务或取消任务。"""
        first = self.server()
        other_data = self.root/'other_data'
        other_data.mkdir()
        second_settings = Settings(project_root=self.project, data_root=other_data,
                                   runtime_dir=self.runtime, static_dir=self.static)
        second = self.server(second_settings)
        body = self.stop_body(first)
        before = self.data_snapshot()
        with patch.object(second.app.tasks, '_spawn') as spawn:
            task, created = second.app.tasks.submit('study_'+uuid4().hex, 'continue', '明确合成忙碌测试', {'synthetic': True})
        self.assertTrue(created)
        spawn.assert_called_once()
        for state in ('queued', 'running'):
            with self.subTest(state=state):
                second.app.tasks.update(task['task_id'], state=state, pid=os.getpid() if state == 'running' else None)
                expected = second.app.tasks._raw(task['task_id'])
                with patch.object(first.app.tasks, 'cancel', side_effect=AssertionError('stop must not cancel tasks')):
                    status, value, _ = self.call(first, 'POST', '/api/v1/service/stop', body, token=True)
                self.assertEqual(status, 409, value)
                self.assertEqual(second.app.tasks._raw(task['task_id']), expected)
                self.health(first)
                self.health(second)
        self.assertEqual(self.data_snapshot(), before)

    def test_stop_shuts_down_only_the_own_listener_without_killing_processes(self):
        """明确停止只关闭对应server，另一个临时实例继续响应且进程本身仍在。"""
        first = self.server()
        second_data = self.root/'second_data'
        second_data.mkdir()
        second = self.server(Settings(project_root=self.project, data_root=second_data,
                                      runtime_dir=self.root/'second_runtime', static_dir=self.static))
        body = self.stop_body(first)
        other, _ = self.health(second)
        before = self.data_snapshot()
        with patch('os.kill', side_effect=AssertionError('stop must not kill processes')), \
                patch('subprocess.Popen', side_effect=AssertionError('stop must not launch process management commands')), \
                patch.object(first.app.tasks, 'cancel', side_effect=AssertionError('stop must not cancel workers')):
            status, value, headers = self.call(first, 'POST', '/api/v1/service/stop', body, token=True)
            self.assertEqual(status, 202, value)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            first.thread.join(timeout=3)
            self.assertFalse(first.thread.is_alive(), '停止成功后serve_forever必须退出')
            with self.assertRaises(OSError):
                with socket.create_connection(('127.0.0.1', first.server.server_port), timeout=.3):
                    pass
            remaining, _ = self.health(second)
        self.assertEqual(remaining['instance_id'], other['instance_id'])
        self.assertTrue(second.thread.is_alive())
        self.assertEqual(self.data_snapshot(), before)
        self.assertEqual(first.app.tasks.list(), [])
        self.assertEqual(second.app.tasks.list(), [])

    def test_inflight_writes_block_stop_but_normal_posts_remain_parallel(self):
        """两个纯测试HTTP写请求能同时进入；它们未完成前停止409，结束后可正常停止。"""
        handle = self.server()
        body = self.stop_body(handle)
        before = self.data_snapshot()
        entered = {'first': Event(), 'second': Event()}
        release = Event()
        original = handle.app.dispatch
        results = []
        errors = []

        def held_write(method, path, request):
            """只拦截测试专用路径，不创建研究或替代生产科学校验。"""
            name = path.removeprefix('/api/v1/test-held-')
            if method == 'POST' and name in entered:
                entered[name].set()
                if not release.wait(timeout=5):
                    raise TimeoutError('explicit synthetic held write timed out')
                return {'synthetic_write_finished': name}
            return original(method, path, request)

        def call_write(name):
            """收集线程的HTTP结果，避免后台异常被误当作并发测试通过。"""
            try:
                results.append(self.call(handle, 'POST', '/api/v1/test-held-'+name, {}, token=True))
            except Exception as error:
                errors.append(error)

        threads = [Thread(target=call_write, args=(name,), daemon=True) for name in entered]
        with patch.object(handle.app, 'dispatch', side_effect=held_write):
            try:
                for thread in threads:
                    thread.start()
                for name, event in entered.items():
                    self.assertTrue(event.wait(timeout=2), '正常POST不能被全局串行锁挡住：'+name)
                status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', body, token=True)
                self.assertEqual(status, 409, value)
                self.health(handle)
                self.assertTrue(handle.thread.is_alive())
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=3)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result[0] == 200 for result in results), results)
        status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', body, token=True)
        self.assertEqual(status, 202, value)
        handle.thread.join(timeout=3)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(self.data_snapshot(), before)
        self.assertEqual(handle.app.tasks.list(), [])

    def test_accepted_stop_blocks_new_writes_while_health_remains_readable(self):
        """接受停止后到socket关闭前，新写请求503；健康仍能说明正在关闭。"""
        handle = self.server()
        body = self.stop_body(handle)
        before = self.data_snapshot()
        release = Event()
        original_shutdown = handle.app._shutdown_callback

        def delayed_shutdown():
            """仅延长测试自身的关闭窗口，最后仍调用该实例原关闭回调。"""
            release.wait(timeout=3)
            original_shutdown()

        with patch.object(handle.app, '_shutdown_callback', side_effect=delayed_shutdown):
            try:
                status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', body, token=True)
                self.assertEqual(status, 202, value)
                status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', body, token=True)
                self.assertEqual(status, 202, value)
                self.assertEqual(value['instance_id'], body['instance_id'])
                for changed, token, expected in ((body, False, 403),
                        (body | {'instance_id': 'service_'+uuid4().hex}, True, 409),
                        (body | {'confirmed': False}, True, 422)):
                    status, value, _ = self.call(handle, 'POST', '/api/v1/service/stop', changed, token=token)
                    self.assertEqual(status, expected, value)
                with patch.object(handle.app.kernel, 'workflow', side_effect=AssertionError('closing service must reject before Workflow')):
                    status, value, _ = self.call(handle, 'POST', '/api/v1/studies', {}, token=True)
                self.assertEqual(status, 503, value)
                self.assertEqual(value['error']['code'], 'SERVICE_STOPPING')
                health, _ = self.health(handle)
                self.assertTrue(health['stopping'])
                self.assertTrue(handle.thread.is_alive())
            finally:
                release.set()
                handle.thread.join(timeout=3)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(self.data_snapshot(), before)
        self.assertEqual(handle.app.tasks.list(), [])

    def test_health_works_in_fresh_process_without_third_party_imports(self):
        """新进程禁止科学和其它第三方导入后，轻量健康路由仍须正常提供身份。"""
        import subprocess
        import sys
        code = '''
import http.client
import importlib.abc
import json
from pathlib import Path
import sys
from threading import Thread

source = Path(sys.argv[1]).resolve()
local_modules = {path.stem for path in source.glob('*.py')} | {path.name for path in source.iterdir() if path.is_dir()}

class StdlibOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.split('.')[0]
        if top not in sys.stdlib_module_names and top not in local_modules:
            raise AssertionError('health imported non-stdlib module: '+name)

sys.meta_path.insert(0, StdlibOnly())
from modulea.api.server import create_server
from modulea.config import Settings
project, data, runtime, static = map(Path, sys.argv[2:])
server, app = create_server(Settings(project_root=project, data_root=data, runtime_dir=runtime, static_dir=static), 0)
thread = Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
thread.start()
connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
try:
    connection.request('GET', '/api/v1/health')
    response = connection.getresponse()
    print(json.dumps({'status': response.status, 'health': json.loads(response.read())}))
finally:
    connection.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
'''
        before = self.data_snapshot()
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parents[2]/'src'), str(self.project), str(self.data),
                                 str(self.root/'fresh_runtime'), str(self.static)], capture_output=True,
                                text=True, encoding='utf-8', env=environment, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['status'], 200, value)
        self.assertIs(value['health']['scientific_validation_performed'], False)
        self.assertTrue(value['health']['frontend']['ready'])
        self.assertEqual(self.data_snapshot(), before)

    def test_client_refuses_to_stop_listener_for_a_different_data_root(self):
        """客户端先比较可信本地配置，目录不一致时不得向旧实例发送停止POST。"""
        from modulea.service_control import probe_service, stop_service
        handle = self.server()
        initial, _ = self.health(handle)
        wrong_data = self.root/'wrong_data_root'
        wrong_data.mkdir()
        wrong = Settings(project_root=self.project, data_root=wrong_data,
                         runtime_dir=self.runtime, static_dir=self.static)
        original = handle.app.dispatch
        writes = []

        def record(method, path, request):
            """记录真实HTTP方法，不替代任何身份比较或接口响应。"""
            if method == 'POST':
                writes.append(path)
            return original(method, path, request)

        before = self.data_snapshot()
        with patch.object(handle.app, 'dispatch', side_effect=record):
            status = probe_service(wrong, handle.server.server_port)
            result = stop_service(wrong, handle.server.server_port, confirmed=True, timeout=1)
        self.assertEqual(status['state'], 'mismatch', status)
        self.assertFalse(status['ready'])
        self.assertEqual(result['state'], 'mismatch', result)
        self.assertEqual(writes, [])
        current, _ = self.health(handle)
        self.assertEqual(current['instance_id'], initial['instance_id'])
        self.assertTrue(handle.thread.is_alive())
        self.assertEqual(self.data_snapshot(), before)

    def test_client_probes_and_explicitly_stops_the_matched_instance(self):
        """状态客户端沿真实健康/令牌/停止流程工作，未确认时不发送停止请求。"""
        from modulea.service_control import probe_service, stop_service
        handle = self.server()
        initial = probe_service(self.settings, handle.server.server_port)
        self.assertEqual(initial['state'], 'running', initial)
        self.assertTrue(initial['ready'])
        before = self.data_snapshot()
        confirmation = stop_service(self.settings, handle.server.server_port, confirmed=False, timeout=1)
        self.assertEqual(confirmation['state'], 'confirmation_required', confirmation)
        still_running, _ = self.health(handle)
        self.assertEqual(still_running['instance_id'], initial['actual']['instance_id'])
        stopped = stop_service(self.settings, handle.server.server_port, confirmed=True, timeout=3)
        self.assertEqual(stopped['state'], 'stopped', stopped)
        handle.thread.join(timeout=3)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(self.data_snapshot(), before)
        self.assertEqual(handle.app.tasks.list(), [])

    def test_create_server_rejects_runtime_inside_study_before_creating_any_files(self):
        """构造入口必须先拒绝研究包内的runtime，不能先创建SQLite或研究子目录。"""
        forbidden_runtime = self.data/'studies/study_x/runtime'
        settings = Settings(project_root=self.project, data_root=self.data,
                            runtime_dir=forbidden_runtime, static_dir=self.static)
        before = set(self.data.rglob('*'))
        original = self.data_snapshot()
        server = None
        rejected = None
        try:
            try:
                server, _ = create_server(settings, 0)
            except ValueError as error:
                rejected = error
        finally:
            # 构造成功也从不启动serve_forever；只释放本测试刚创建的监听socket。
            if server is not None:
                server.server_close()
        created = sorted(path.relative_to(self.data).as_posix() for path in set(self.data.rglob('*'))-before)
        self.assertEqual(created, [], '拒绝配置之前已经向研究目录写入：'+', '.join(created))
        self.assertIsNotNone(rejected, 'create_server必须拒绝data_root/studies内部的runtime')
        self.assertEqual(self.data_snapshot(), original)
        self.assertFalse((forbidden_runtime/'tasks.sqlite').exists())
