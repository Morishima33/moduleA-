"""真实合成HTTP核对同页读取等值、单次快照及原件边界；不操作真实研究。"""
import json,threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError

from modulea.config import Settings
from modulea.api.server import create_server
from modulea.api.views import Views
from modulea.devtools.demo_data import build


class WorkspaceReadTests(TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.data=self.root/'data';self.sid=build(self.data)
        self.server,self.app=create_server(Settings(data_root=self.data,runtime_dir=self.root/'runtime'),0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}/api/v1'

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)

    def get(self,path):
        with urlopen(self.base+path,timeout=30) as response:return json.load(response)

    def test_workspace_equals_original_views_and_builds_snapshot_once(self):
        study=self.app.views.study(self.sid);module=self.app.views.module(self.sid,'A07')
        home=self.data/'studies'/self.sid;manifest=(home/'manifest.json').read_bytes()
        original=Views._snapshot;calls=[]
        def snapshot(views,study_id):
            calls.append(study_id);return original(views,study_id)
        with patch.object(Views,'_snapshot',snapshot):
            try:actual=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
            except HTTPError as error:self.fail(f'同页读取应返回200，实际HTTP {error.code}')
        self.assertEqual(actual,{'study':study,'module':module,'module_error':None})
        self.assertEqual(calls,[self.sid],'同请求只运行一次原Workflow快照')
        self.assertEqual((home/'manifest.json').read_bytes(),manifest)
        self.assertEqual(self.app.tasks.list(self.sid),[])

    def target(self):
        """返回已由合成公开流程登记的A07附件，用于损坏/退出复验检查。"""
        home=self.data/'studies'/self.sid
        manifest=self.app.kernel.read_workflow().load(self.sid)
        result=json.loads((home/manifest['runs'][manifest['current']['A07']]['result_file']['path']).read_text('utf-8'))
        return home/result['files'][-1]['path']

    def test_default_module_and_historical_run_match_original_selection(self):
        study=self.app.views.study(self.sid)
        selected=(study.get('next_step') or {}).get('module_id') or study['nav'][0]['modules'][0]['module_id']
        self.assertEqual(self.get(f'/studies/{self.sid}/workspace')['module'],self.app.views.module(self.sid,selected))
        workflow=self.app.kernel.workflow();manifest=workflow.load(self.sid);rid=manifest['current']['A07']
        # 仅合成研究将本结果留作历史，不生成新的科学结果或批准。
        manifest['current']['A07']=None;workflow.save(manifest)
        expected=self.app.views.module(self.sid,'A07',rid)
        actual=self.get(f'/studies/{self.sid}/workspace?module_id=A07&run_id={rid}')
        self.assertEqual(actual['module'],expected);self.assertTrue(actual['module']['historical'])
        self.assertFalse(actual['module']['review']['can_review'])

    def test_module_and_historical_errors_preserve_valid_study_framework(self):
        expected=self.app.views.study(self.sid)
        for query in ('module_id=UNKNOWN','module_id=A07&run_id=run_not_present'):
            with self.subTest(query=query):
                value=self.get(f'/studies/{self.sid}/workspace?{query}')
                self.assertEqual(value['study'],expected);self.assertIsNone(value['module'])
                self.assertEqual(value['module_error']['status'],404)

    def test_missing_study_is_still_whole_response_not_found(self):
        with self.assertRaises(HTTPError) as failure:self.get('/studies/study_'+'e'*32+'/workspace?module_id=A07')
        self.assertEqual(failure.exception.code,404)
        self.assertNotIn('study',json.load(failure.exception))

    def test_unknown_repeated_and_blank_queries_are_rejected(self):
        for query in ('unknown=1','module_id=A06&module_id=A07','run_id=','module_id=','module_id=A07&run_id=x&run_id=y'):
            with self.subTest(query=query):
                with self.assertRaises(HTTPError) as failure:self.get(f'/studies/{self.sid}/workspace?{query}')
                self.assertEqual(failure.exception.code,422)

    def test_damaged_archive_keeps_framework_warning_and_no_module_actions(self):
        self.target().write_bytes(b'corrupted synthetic archive')
        value=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertFalse(value['study']['archive_ok']);self.assertIsNone(value['module'])
        self.assertEqual(value['module_error']['status'],503)

    def test_tampering_before_scope_exit_blocks_entire_response(self):
        import os
        from modulea.core.checkpoint_json_read import CheckpointReadEvidence
        original=CheckpointReadEvidence.finish;target=self.target()
        def finish(evidence):
            stamp=target.stat();raw=target.read_bytes();target.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            os.utime(target,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            return original(evidence)
        with patch.object(CheckpointReadEvidence,'finish',finish):
            with self.assertRaises(HTTPError) as failure:self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertEqual(failure.exception.code,503)
        body=json.load(failure.exception);self.assertNotIn('study',body);self.assertNotIn('module',body)

    def test_manifest_change_at_exit_blocks_both_parts(self):
        from modulea.core.checkpoint_json_read import CheckpointReadEvidence
        original=CheckpointReadEvidence.finish;path=self.data/'studies'/self.sid/'manifest.json'
        def finish(evidence):
            path.write_bytes(path.read_bytes()+b'\n')
            return original(evidence)
        with patch.object(CheckpointReadEvidence,'finish',finish):
            with self.assertRaises(HTTPError) as failure:self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertEqual(failure.exception.code,409)
        self.assertNotIn('study',json.load(failure.exception))

    def test_independent_requests_rebuild_and_do_not_share_response_containers(self):
        original=Views._snapshot;calls=[]
        def snapshot(views,study_id):
            calls.append(study_id);return original(views,study_id)
        with patch.object(Views,'_snapshot',snapshot):
            first=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
            first['study']['nav'].clear()
            second=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertEqual(calls,[self.sid,self.sid]);self.assertTrue(second['study']['nav'])
        self.target().write_bytes(b'corrupt before next request')
        third=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertFalse(third['study']['archive_ok']);self.assertIsNone(third['module'])

    def test_trashed_study_keeps_original_views_and_no_review_actions(self):
        workflow=self.app.kernel.workflow();manifest=workflow.load(self.sid)
        manifest['trashed']=True;workflow.save(manifest)
        expected={'study':self.app.views.study(self.sid),'module':self.app.views.module(self.sid,'A07'),'module_error':None}
        actual=self.get(f'/studies/{self.sid}/workspace?module_id=A07')
        self.assertEqual(actual,expected);self.assertTrue(actual['study']['study']['trashed'])
        self.assertFalse(actual['module']['review']['can_review'])

    def test_bad_historical_archive_does_not_hide_valid_current_study(self):
        target=self.target();workflow=self.app.kernel.workflow();manifest=workflow.load(self.sid)
        rid=manifest['current']['A07'];manifest['current']['A07']=None;workflow.save(manifest)
        expected=self.app.views.study(self.sid);self.assertTrue(expected['archive_ok'])
        target.write_bytes(b'corrupt only historical artifact')
        try:actual=self.get(f'/studies/{self.sid}/workspace?module_id=A07&run_id={rid}')
        except HTTPError as error:self.fail(f'历史模块错误不能隐藏有效研究框架，实际HTTP {error.code}')
        self.assertEqual(actual['study'],expected);self.assertIsNone(actual['module'])
        self.assertEqual(actual['module_error']['status'],503)


class WorkspaceScopeGuardTests(TestCase):
    def test_snapshot_copies_only_inside_owned_root_thread_and_lifetime(self):
        """只检查私有快照生命周期；科学等值与HTTP另由上方完整虚构研究验证。"""
        from types import SimpleNamespace
        from contextvars import copy_context
        from concurrent.futures import ThreadPoolExecutor
        from modulea.api.workspace import _PageViews
        from modulea.core.checkpoint_json_read import json_evidence_scope
        with TemporaryDirectory() as folder:
            root=Path(folder)/'one';other=Path(folder)/'two';sid='study_'+'a'*32
            for location in (root,other):
                home=location/'studies'/sid;home.mkdir(parents=True)
                (home/'manifest.json').write_text('{}',encoding='utf-8')
            workflow=object();counter=[]
            def snapshot(views,study_id):
                counter.append(1);return workflow,{'items':[1]},None
            kernel=SimpleNamespace(settings=SimpleNamespace(data_root=root))
            with patch.object(Views,'_snapshot',snapshot):
                with json_evidence_scope(root,sid) as evidence:
                    views=_PageViews(kernel,None,sid,evidence)
                    first=views._snapshot(sid);first[1]['items'].append(2)
                    second=views._snapshot(sid)
                    self.assertIs(first[0],workflow);self.assertEqual(second[1],{'items':[1]})
                    self.assertEqual(len(counter),1)
                    copied=copy_context()
                    with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(copied.run,views._snapshot,sid).result()
                    self.assertEqual(len(counter),2)
                    wrong=_PageViews(SimpleNamespace(settings=SimpleNamespace(data_root=other)),None,sid,evidence)
                    wrong._snapshot(sid);wrong._snapshot(sid)
                    self.assertEqual(len(counter),4,'其他数据根不能使用当前范围快照')
                views._snapshot(sid)
                self.assertEqual(len(counter),5,'退出后不能继续复用已保存快照')
