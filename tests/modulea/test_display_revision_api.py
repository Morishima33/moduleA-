"""同批展示修订的真实HTTP边界；仅使用临时合成研究，不生成Word或代签复核。"""
from hashlib import sha256
import http.client
import json
from pathlib import Path
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from modulea.api.server import create_server
from modulea.config import Settings
from storage import verified_file
from tests.modulea import test_plan_report_revision as seed


class DisplayRevisionApiTests(TestCase):
    """复用经生产验证的空交集合成上游，HTTP只隔离子进程启动。"""

    @classmethod
    def setUpClass(cls):
        """一次准备三库、五库和系统核查，之后每项独立复制临时研究。"""
        seed.ReportRevisionWorkflowTests.setUpClass.__func__(cls)

    setUp = seed.ReportRevisionWorkflowTests.setUp

    def body(self):
        """当前指纹来自公开只读入口，不在测试里猜测绑定或填科学参数。"""
        info = self.w.analysis_plan_display_revision_info(self.sid)
        self.assertTrue(info['supported'], info)
        self.assertTrue(info['enabled'], info)
        return {'request_id': 'displayreq_'+uuid4().hex,
                'expected_input_hash': info['expected_input_hash'],
                'author': '明确隔离HTTP测试',
                'note': '仅验证同批展示修订，不是用户或科研复核', 'confirmed': True}

    def server(self):
        """只启动、关闭本测试持有的本机临时服务，不接触现有工作台。"""
        server, app = create_server(Settings(data_root=self.root, runtime_dir=self.root/'http_runtime'), 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def close():
            """退出时关闭自己的监听与线程，避免遗留临时服务。"""
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

        self.addCleanup(close)
        return server, app

    def call(self, server, app, method, path, body=None, *, token=True, origin=None):
        """通过实际HTTP发送JSON或读取原字节，保留状态和响应头供断言。"""
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=60)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-ModuleA-Token'] = app.token
        if origin:
            headers['Origin'] = origin
        target = path if path.startswith('/api/v1/') else '/api/v1'+path
        try:
            connection.request(method, target, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def prefix(self, sid=None):
        """路由只由已创建的合成研究编号构成，不传磁盘路径。"""
        return f'/studies/{sid or self.sid}/analysis-plan/display-revisions'

    def snapshot(self):
        """逐字节记录研究包，检测GET或HTTP预检的意外写入。"""
        home = self.w.location(self.sid)
        return {path.relative_to(home).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in home.rglob('*') if path.is_file()}

    def publish(self, body=None):
        """真正调用公开Workflow生成合成展示附件，不伪造科学结果或登记回执。"""
        before = self.w.load(self.sid)
        record = self.w.publish_analysis_plan_display_revision(self.sid, body or self.body())
        after = self.w.load(self.sid)
        for key in ('current', 'runs', 'reviews'):
            self.assertEqual(after[key], before[key], key)
        self.assertFalse(list(self.w.location(self.sid).rglob('*.docx')))
        self.assertFalse(record['scientific_results_changed'])
        self.assertFalse(record['human_review_written'])
        return record

    def test_get_eligibility_and_module_views_do_not_write_or_queue(self):
        """未生成修订时，反复读取资格和当前页面不能隐式绘图或创建任务。"""
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        with patch.object(app.tasks, '_spawn') as spawn:
            for _ in range(2):
                status, raw, _ = self.call(server, app, 'GET', self.prefix(), token=False)
                self.assertEqual(status, 200, raw)
                info = json.loads(raw)
                self.assertEqual(info['schema_version'], 'ModuleA.display_revision.1')
                self.assertTrue(info['supported'])
                self.assertTrue(info['enabled'])
                self.assertIsNone(info['current'])
                self.assertEqual(info['history'], [])
                self.assertIsInstance(info['expected_input_hash'], str)
            for module in ('A03', 'A07'):
                status, raw, _ = self.call(server, app, 'GET', f'/studies/{self.sid}/modules/{module}')
                self.assertEqual(status, 200, raw)
                self.assertIsNone(json.loads(raw)['display_revision']['current'])
        spawn.assert_not_called()
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_post_rejects_missing_token_and_foreign_origin_without_writes(self):
        """展示生成沿统一令牌与Origin规则，不能因其不改评分而放开写权限。"""
        body = self.body()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        for token, origin in ((False, None), (True, 'https://untrusted.example')):
            status, raw, _ = self.call(server, app, 'POST', self.prefix(), body, token=token, origin=origin)
            self.assertEqual(status, 403, raw)
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_post_requires_exact_five_fields_and_explicit_confirmation(self):
        """浏览器不得注入名单、分数、路径、译文或科学批准；未确认也不能排队。"""
        body = self.body()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        invalid = [body | {'confirmed': False}, body | {'confirmed': 1},
                   body | {'author': ''}, body | {'note': '   '},
                   body | {'request_id': 'displayreq_not_a_stable_id'},
                   body | {'score': -9}, body | {'members': ['HGNC:1']},
                   body | {'path': '../outside.svg'}, body | {'translations': {'GO:1': '任意译文'}},
                   body | {'approved': True}, {key: value for key, value in body.items() if key != 'note'}]
        with patch.object(app.tasks, '_spawn') as spawn:
            for value in invalid:
                with self.subTest(fields=sorted(value), confirmed=value.get('confirmed')):
                    status, raw, _ = self.call(server, app, 'POST', self.prefix(), value)
                    self.assertEqual(status, 422, raw)
        spawn.assert_not_called()
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_stale_source_hash_returns_409_and_does_not_submit(self):
        """旧页面指纹只能刷新，不能用当前来源自动替换后重交。"""
        body = self.body() | {'expected_input_hash': '0'*64}
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        status, raw, _ = self.call(server, app, 'POST', self.prefix(), body)
        self.assertEqual(status, 409, raw)
        self.assertEqual(json.loads(raw)['error']['code'], 'STALE_VERSION')
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_busy_research_disables_get_and_rejects_post_with_409(self):
        """真实任务索引中已有排队任务时，不允许同研究并发第二项写任务。"""
        body = self.body()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        with patch.object(app.tasks, '_spawn') as spawn:
            task, created = app.tasks.submit(self.sid, 'plan_display_revision', body['author'], body)
            self.assertTrue(created)
            status, raw, _ = self.call(server, app, 'GET', self.prefix())
            self.assertEqual(status, 200, raw)
            self.assertFalse(json.loads(raw)['enabled'])
            self.assertTrue(json.loads(raw)['blockers'])
            status, raw, _ = self.call(server, app, 'POST', self.prefix(), body)
            self.assertEqual(status, 409, raw)
        spawn.assert_called_once()
        self.assertEqual([value['task_id'] for value in app.tasks.list()], [task['task_id']])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_trashed_research_remains_read_only_and_returns_423(self):
        """通过原公开回收站管理入口暂停，展示接口不能借旧指纹继续生成。"""
        body = self.body()
        self.w.set_trashed(self.sid, True, '明确合成测试', '验证回收站展示只读')
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        status, raw, _ = self.call(server, app, 'GET', self.prefix())
        self.assertEqual(status, 200, raw)
        self.assertFalse(json.loads(raw)['enabled'])
        status, raw, _ = self.call(server, app, 'POST', self.prefix(), body)
        self.assertEqual(status, 423, raw)
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_explicit_post_queues_original_request_without_generating_in_http(self):
        """受理只排队，完整明确请求原样交worker，HTTP线程不另存任何科学资料。"""
        body = self.body()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        with patch.object(app.tasks, '_spawn') as spawn:
            status, raw, _ = self.call(server, app, 'POST', self.prefix(), body)
        self.assertEqual(status, 202, raw)
        value = json.loads(raw)
        self.assertTrue(value['created'])
        self.assertEqual(value['task']['kind'], 'plan_display_revision')
        queued = app.tasks._raw(value['task']['task_id'])
        self.assertEqual(json.loads(queued['payload']), body)
        self.assertEqual(queued['requested_by'], body['author'])
        spawn.assert_called_once()
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_completed_same_request_returns_200_without_new_task_or_files(self):
        """完成后的同请求重试读取原回执，不能再次绘图或生成新文件。"""
        body = self.body()
        record = self.publish(body)
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        with patch.object(app.tasks, '_spawn') as spawn:
            for _ in range(2):
                status, raw, _ = self.call(server, app, 'POST', self.prefix(), body)
                self.assertEqual(status, 200, raw)
                value = json.loads(raw)
                self.assertEqual(value['revision_id'], record['revision_id'])
                self.assertFalse(value['created'])
                self.assertFalse(value.get('task'))
        spawn.assert_not_called()
        self.assertEqual(app.tasks.list(), [])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)

    def test_current_catalog_downloads_and_module_view_keep_registered_bytes(self):
        """目录遵守前端契约；图像和完整数据按本研究索引下载，GET均无副作用。"""
        record = self.publish()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        status, raw, _ = self.call(server, app, 'GET', self.prefix())
        self.assertEqual(status, 200, raw)
        info = json.loads(raw)
        current = info['current']
        self.assertEqual(current['revision_id'], record['revision_id'])
        self.assertTrue(current['matches_input'])
        self.assertFalse(current['human_review_written'])
        self.assertFalse(current['scientific_results_changed'])
        self.assertEqual(current['source_run_ids'], record['source_run_ids'])
        self.assertEqual(info['history'][0]['revision_id'], record['revision_id'])
        self.assertIsInstance(current['counts'], list)
        for count in current['counts']:
            self.assertIsInstance(count['label_zh'], str)
            self.assertIsInstance(count['text'], str)
        coverage = current['translation_coverage']
        self.assertIsInstance(coverage['required'], int)
        self.assertIsInstance(coverage['verified'], int)
        self.assertEqual(coverage['missing'], [])
        references = record['files']+[record['bundle_file'], record['payload_file']]+record['implementation_files']
        registered = {'/api/v1'+self.prefix()+'/'+record['revision_id']+'/files/'+str(index): ref
                      for index, ref in enumerate(references)}
        self.assertTrue(current['downloads'])
        for file in current['downloads']:
            self.assertTrue(file['url'].startswith('/api/v1'+self.prefix()+'/'+record['revision_id']+'/files/'))
            status, data, headers = self.call(server, app, 'GET', file['url'], token=False)
            self.assertEqual(status, 200, data[:200])
            reference = registered[file['url']]
            self.assertEqual(sha256(data).hexdigest(), reference['sha256'])
            self.assertEqual(len(data), reference['bytes'])
            self.assertIn('Content-Disposition', headers)
            self.assertNotIn('wordprocessingml', headers['Content-Type'])
        self.assertTrue(current['figures'])
        for figure in current['figures']:
            self.assertIn(figure['module_id'], ('A03', 'A04', 'A05', 'A06'))
            self.assertTrue(figure['caption_zh'])
            status, data, headers = self.call(server, app, 'GET', figure['image_url'])
            self.assertEqual(status, 200, data[:200])
            self.assertIn(headers['Content-Type'].split(';')[0], ('image/png', 'image/svg+xml'))
            self.assertTrue(headers['Content-Disposition'].startswith('inline'))
        for table in current['tables']:
            self.assertIsInstance(table['total'], int)
            self.assertGreaterEqual(table['total'], len(table['rows']))
            self.assertTrue(all('key' in column and 'label_zh' in column for column in table['columns']))
        status, raw, _ = self.call(server, app, 'GET', f'/studies/{self.sid}/modules/A03')
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['display_revision']['current']['revision_id'], record['revision_id'])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)
        self.assertEqual(app.tasks.list(), [])

    def test_other_study_unknown_revision_and_unregistered_index_return_404(self):
        """同一修订编号不能跨研究借用，URL也不能越过已登记附件清单。"""
        record = self.publish()
        other = self.w.create({'formula': '另一合成方', 'herbs': '测试药', 'disease': 'COPD',
            'disease_scope': '仅本病', 'operator': '明确隔离测试', 'species': 9606,
            'analysis_purpose': 'workflow_test'}, kind='contract_test')
        server, app = self.server()
        for path in (self.prefix(other)+'/'+record['revision_id']+'/files/0',
                     self.prefix()+'/displayrev_'+uuid4().hex+'/files/0',
                     self.prefix()+'/'+record['revision_id']+'/files/9999',
                     self.prefix()+'/'+record['revision_id']+'/files/not_registered'):
            with self.subTest(path=path):
                status, raw, _ = self.call(server, app, 'GET', path)
                self.assertEqual(status, 404, raw[:200])

    def test_corrupt_registered_attachment_returns_503_without_regeneration(self):
        """损坏原件不能借GET重新生成掩盖，也不能以空文件冒充成功下载。"""
        record = self.publish()
        reference = record['files'][0]
        path = verified_file(self.w.location(self.sid), reference)
        corrupt = path.read_bytes()+b'EXPLICIT_SYNTHETIC_CORRUPTION'
        path.write_bytes(corrupt)
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        with patch.object(app.tasks, '_spawn') as spawn:
            for target in (self.prefix()+'/'+record['revision_id']+'/files/0?inline=1', self.prefix()):
                status, raw, _ = self.call(server, app, 'GET', target)
                self.assertEqual(status, 503, raw[:200])
                self.assertEqual(json.loads(raw)['error']['code'], 'ARCHIVE_UNAVAILABLE')
        spawn.assert_not_called()
        self.assertEqual(path.read_bytes(), corrupt)
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)
        self.assertEqual(app.tasks.list(), [])

    def test_download_rejects_path_queries_and_non_image_inline(self):
        """附件URL不能被查询参数变成任意路径读取，也不能内嵌CSV或源代码。"""
        record = self.publish()
        server, app = self.server()
        before, files = self.w.load(self.sid), self.snapshot()
        references = record['files']+[record['bundle_file'], record['payload_file']]+record['implementation_files']
        non_image = next(index for index, ref in enumerate(references) if Path(ref['path']).suffix not in ('.png', '.svg'))
        base = self.prefix()+'/'+record['revision_id']+'/files/'
        for target in (base+'0?path=../outside.svg', base+'0?inline=0', base+str(non_image)+'?inline=1'):
            with self.subTest(target=target):
                status, raw, _ = self.call(server, app, 'GET', target)
                self.assertEqual(status, 422, raw[:200])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)
        self.assertEqual(app.tasks.list(), [])

    def test_download_does_not_send_bytes_replaced_after_archive_verification(self):
        """在最终校验和实际读取之间替换临时附件，HTTP必须拒绝发送新未核验字节。"""
        from modulea.api import display_revisions as display_api
        record = self.publish()
        reference = record['files'][0]
        server, app = self.server()
        original = display_api.verified_file
        replaced = []

        def replace_after_check(home, ref):
            """先真实核验成功，再模拟另一进程在发送前改写同一文件。"""
            path = original(home, ref)
            if ref == reference and not replaced:
                path.write_bytes(path.read_bytes()+b'EXPLICIT_SYNTHETIC_SWAP_AFTER_VERIFICATION')
                replaced.append(True)
            return path

        with patch.object(display_api, 'verified_file', side_effect=replace_after_check):
            status, raw, _ = self.call(server, app, 'GET', self.prefix()+'/'+record['revision_id']+'/files/0')
        self.assertEqual(replaced, [True])
        if status == 200:
            self.assertEqual(sha256(raw).hexdigest(), reference['sha256'], '不得发送校验后被替换的字节')
            self.assertEqual(len(raw), reference['bytes'])
        else:
            self.assertEqual(status, 503, raw[:200])
            self.assertEqual(json.loads(raw)['error']['code'], 'ARCHIVE_UNAVAILABLE')

    def test_request_binding_tracks_indirect_selection_and_classification_rule_bytes(self):
        """只修改临时源码副本，验证Degree范围与核译分类依赖也进入请求实现指纹。"""
        from modulea.core import display_revisions as revision
        from contracts import fingerprint
        import shutil
        source = Path(revision.__file__).resolve().parents[2]
        temporary_source = Path(self.temp.name)/'isolated_renderer_source'
        dependencies = ('science_modules/a04/selection_flow.py',
                        'science_modules/a04/personalized_selection.py',
                        'science_modules/a04/selection.py', 'science_modules/a05/screening.py')
        for name in set(revision._implementation()) | set(dependencies):
            target = temporary_source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source/name, target)
        with patch.object(revision, '__file__', str(temporary_source/'modulea/core/display_revisions.py')):
            before = fingerprint(revision.binding(self.w, self.w.load(self.sid)))
            for name in dependencies:
                with self.subTest(dependency=name):
                    target = temporary_source/name
                    original = target.read_bytes()
                    try:
                        target.write_bytes(original+b'\n# explicit synthetic dependency byte change\n')
                        after = fingerprint(revision.binding(self.w, self.w.load(self.sid)))
                        self.assertNotEqual(before, after, '实际范围或分类依赖改变后，旧请求必须成为陈旧版本')
                    finally:
                        target.write_bytes(original)

    def test_readonly_http_does_not_import_optional_scientific_dependencies(self):
        """全新进程主动禁止科学绘图库导入，元数据GET仍须正常响应且不写研究。"""
        import os
        import subprocess
        import sys
        code = '''
import http.client
import json
from pathlib import Path
import sys
from threading import Thread

class NoScientificImports:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'PIL', 'docx', 'networkx', 'numpy', 'matplotlib', 'scipy', 'rdkit', 'openpyxl'}:
            raise AssertionError('readonly HTTP imported scientific dependency: '+name)

sys.meta_path.insert(0, NoScientificImports())
from modulea.api.server import create_server
from modulea.config import Settings
root = Path(sys.argv[1])
server, app = create_server(Settings(data_root=root, runtime_dir=root/'stdlib_http_runtime'), 0)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=20)
try:
    connection.request('GET', '/api/v1/studies/'+sys.argv[2]+'/analysis-plan/display-revisions')
    response = connection.getresponse()
    print(json.dumps({'status': response.status, 'info': json.loads(response.read())}))
finally:
    connection.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)
'''
        before, files = self.w.load(self.sid), self.snapshot()
        environment = dict(os.environ, PYTHONUTF8='1')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.root), self.sid],
                                capture_output=True, text=True, encoding='utf-8', env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['status'], 200, value)
        self.assertEqual(value['info']['schema_version'], 'ModuleA.display_revision.1')
        self.assertTrue(value['info']['supported'])
        self.assertEqual(self.w.load(self.sid), before)
        self.assertEqual(self.snapshot(), files)
