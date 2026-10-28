"""新版建档的隔离集成测试：同批初始方案、资料缺口、明确确认、重试及旧流程隔离。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, Mock
from uuid import uuid4

from contracts import ContractError
from storage import read_json, verified_file, write_json
from modulea.api.errors import ApiError
from modulea.api.server import App
from modulea.config import Settings
from modulea.core.plan_creation import PlanCreation, context
from modulea.core.study_creation import CreationConflict
from modulea.preflight import REFERENCE_FILES
from tests.modulea.test_study_creation import official_fixture


class PlanCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plan_creation_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(data_root=self.root/'data', runtime_dir=self.root/'runtime')
        self.app = App(self.settings)
        self.service = self.app.plan_creation
        self.verify = patch('modulea.core.plan_creation.verify_mesh_identity', side_effect=official_fixture).start()
        self.addCleanup(patch.stopall)
        self.body = {'intake': {'formula':'合成方','herbs':'合成药','disease':'合成病',
                     'mesh_term':'Synthetic Disease','mesh_id':'D123456','operator':'隔离测试', 'analysis_purpose':'workflow_test'},
                     'specification': {'mode':'personalized','parameters':{'a06.component_count':2,'a06.receptor_count':2,'a01.ob_min':15}}}

    def prepare(self):
        """预检不生成研究，确认体只绑定不可变预检凭证。"""
        value = self.service.preflight(self.body)
        return value, {'request_id':'plancreate_'+uuid4().hex, 'preflight_id':value['preflight_id'],
                       'expected_input_hash':value['input_hash'], 'confirmed':True}

    def test_preflight_and_personalized_create_preserve_plan_without_reviews_or_tasks(self):
        preview, body = self.prepare()
        self.assertFalse(self.settings.studies_dir.exists())
        self.assertTrue(preview['can_create'])
        self.assertFalse(preview['materials']['references_verified'])
        self.assertTrue(all(row['status']=='not_provided' for row in preview['materials']['research_sources']))
        value = self.service.create(body)
        w = self.app.kernel.workflow(); m = w.load(value['study_id'])
        self.assertEqual(set(m['current']), {'A00'})
        self.assertEqual(m['reviews'], [])
        self.assertEqual(self.app.tasks.list(), [])
        self.assertEqual(len(m['analysis_plan_records']), 1)
        initial = read_json(verified_file(w.location(value['study_id']),m['initial_analysis_plan']))
        self.assertEqual(initial['plan']['parameter_hash'],preview['plan']['parameter_hash'])
        self.assertEqual(initial['plan']['parameters']['a06.component_count'],2)
        self.assertEqual(initial['plan']['parameters']['a01.ob_min'],15)
        self.assertIn(m['initial_analysis_plan'],w.result(m,value['run_id'])['files'])
        self.assertEqual(w.analysis_plan_info(value['study_id'])['draft'],initial)
        self.assertFalse(value['execution_available'])

    def test_standard_plan_defaults_and_unknown_overrides(self):
        self.body['specification']={'mode':'standard'}
        preview, body=self.prepare(); value=self.service.create(body)
        self.assertEqual(value['mode'],'standard')
        self.assertEqual(preview['plan']['parameters']['a06.component_count'],15)
        self.assertEqual(preview['plan']['parameters']['a06.receptor_count'],15)
        self.body['specification']['parameters']={'a06.component_count':2}
        with self.assertRaises(ContractError):self.service.preflight(self.body)

    def test_verified_shared_files_still_do_not_claim_research_sources_ready(self):
        folder=self.settings.data_root/'references';folder.mkdir(parents=True)
        for _,_,filename,manifest_name in REFERENCE_FILES:
            data=('isolated checksum fixture for '+filename).encode()
            (folder/filename).write_bytes(data)
            write_json(folder/manifest_name,{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        preview,body=self.prepare()
        self.assertTrue(preview['materials']['references_verified'])
        self.assertTrue(all(row['status']=='not_provided' for row in preview['materials']['research_sources']))
        result=self.service.create(body)
        self.assertFalse(result['execution_available'])

    def test_new_creation_core_runs_without_scientific_site_packages(self):
        script="""import json,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from modulea.api.server import App
from modulea.config import Settings
app=App(Settings(data_root=Path(sys.argv[2])/'data',runtime_dir=Path(sys.argv[2])/'runtime'))
with patch('modulea.core.plan_creation.verify_mesh_identity',return_value=json.loads(sys.argv[4])):
 p=app.plan_creation.preflight(json.loads(sys.argv[3]))
r=app.plan_creation.create({'request_id':'plancreate_'+'a'*32,'preflight_id':p['preflight_id'],'expected_input_hash':p['input_hash'],'confirmed':True})
assert r['created'] and not r['execution_available']
assert not any(x in sys.modules for x in ('rdkit','meeko','networkx','numpy','docx'))
print('standard_library_creation_passed')"""
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(Path(__file__).resolve().parents[2]/'src'),
            str(self.root/'isolated_stdlib'),json.dumps(self.body),json.dumps(official_fixture('Synthetic Disease','D123456'))],
            capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_duplicate_restart_and_missing_runtime_uses_original_study(self):
        _, body=self.prepare(); first=self.service.create(body)
        path=self.service.folder/(body['preflight_id']+'.json'); path.unlink()
        self.service=PlanCreation(self.app.kernel)
        second=self.service.create(body)
        self.assertEqual(first['study_id'],second['study_id'])
        self.assertFalse(second['created'])
        self.assertEqual(len(list(self.settings.studies_dir.iterdir())),1)
        self.assertEqual(self.verify.call_count,1)
        with self.assertRaises(CreationConflict):self.service.create(dict(body,expected_input_hash='0'*64))

    def test_parallel_duplicate_confirmation_has_single_study_and_plan(self):
        _, body=self.prepare()
        def create(_):
            try:return self.service.create(body)
            except ContractError as error:
                self.assertIn('正在保存',str(error)); return None
        with ThreadPoolExecutor(max_workers=3) as pool: values=list(pool.map(create,range(3)))
        final=self.service.create(body)
        self.assertEqual(len(list(self.settings.studies_dir.iterdir())),1)
        self.assertTrue(any(value for value in values))
        self.assertFalse(final['created'])

    def test_invalid_inputs_fail_before_official_request_or_study_write(self):
        cases=[None,dict(self.body,approved=True),dict(self.body,intake=dict(self.body['intake'],species=9606)),
               dict(self.body,specification={'mode':'personalized','parameters':{'a06.receptor_count':True}}),
               dict(self.body,intake=dict(self.body['intake'],mesh_id='../bad'))]
        for body in cases:
            with self.subTest(body=body),self.assertRaises(ContractError):self.service.preflight(body)
        self.verify.assert_not_called()
        self.assertFalse(self.settings.studies_dir.exists())

    def test_network_failure_does_not_create_study(self):
        self.verify.side_effect=ContractError('暂时无法连接NLM官方MeSH服务')
        with self.assertRaises(ApiError) as error:
            self.app.post_plan_creation_preflight(SimpleNamespace(json=lambda:self.body))
        self.assertEqual(error.exception.status,503)
        self.assertFalse(self.settings.studies_dir.exists())

    def test_expired_corrupt_or_unconfirmed_preflight_cannot_create(self):
        _, body=self.prepare(); path=self.service.folder/(body['preflight_id']+'.json')
        record=read_json(path)
        with self.assertRaises(ContractError):self.service.create(dict(body,confirmed=False))
        with self.assertRaises(ContractError):self.service.create(dict(body,directory='outside'))
        changed=deepcopy(record);changed['content']['plan']['parameters']['a06.seed']=9
        write_json(path,changed,replace=True)
        with self.assertRaises(ContractError):self.service.create(body)
        changed=deepcopy(record);changed['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        write_json(path,changed,replace=True)
        with self.assertRaises(ContractError):self.service.create(body)
        self.assertFalse(self.settings.studies_dir.exists())

    def test_material_change_and_data_root_change_require_new_preflight(self):
        _,body=self.prepare()
        refs=self.settings.data_root/'references';refs.mkdir(parents=True)
        (refs/'tcmsp_snapshot.tsv').write_text('synthetic source',encoding='utf-8')
        with self.assertRaises(ContractError):self.service.create(body)
        # 两个目录同样缺资料时，仍不能用同一凭证切换目标数据根。
        (refs/'tcmsp_snapshot.tsv').unlink()
        with patch.object(self.settings,'data_root',self.root/'other'):
            with self.assertRaises(ContractError):self.service.create(body)
        self.assertFalse(self.settings.studies_dir.exists())

    def test_initial_plan_and_exports_survive_later_draft_and_a00_revision(self):
        preview,body=self.prepare();value=self.service.create(body);w=self.app.kernel.workflow();sid=value['study_id'];m=w.load(sid)
        initial=read_json(verified_file(w.location(sid),m['initial_analysis_plan']))
        w.save_analysis_plan_draft(sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':value['run_id'],
            'expected_draft_id':initial['plan_id'],'specification':{'mode':'standard'},'author':'隔离测试','note':'后续草稿'})
        snapshot=context(w,sid)
        self.assertEqual(snapshot['initial_plan']['parameter_hash'],preview['plan']['parameter_hash'])
        self.assertEqual(snapshot['current_plan']['mode'],'standard')
        again=self.service.create(body)
        self.assertEqual(again['plan_id'],initial['plan_id'])
        exported=self.app.export_plan_creation(SimpleNamespace(),sid)
        self.assertEqual(exported[0],'download')
        self.assertEqual(json.loads(exported[1])['initial_plan_id'],initial['plan_id'])
        intake=dict(w.result(w.load(sid),value['run_id'])['summary'],formula='修订的合成方')
        w.revise_intake(sid,intake,'仅修订登记',value['run_id'])
        self.assertEqual(self.service.create(body)['run_id'],value['run_id'])
        self.assertIsNone(context(w,sid)['current_plan'])
        # 登记修订丢弃扩展标记后，manifest中的初始方案仍保证旧编排不能接管。
        current=w.load(sid)['current']['A00']
        plain={k:intake[k] for k in ('formula','herbs','disease','disease_scope','operator','species','analysis_purpose')}
        w.revise_intake(sid,plain,'仅验证扩展字段遗失的隔离边界',current)
        with self.assertRaises(ApiError):self.app.post_continue(SimpleNamespace(),sid)

    def test_approval_and_continue_cannot_use_legacy_automatic_pipeline(self):
        _,body=self.prepare();value=self.service.create(body);w=self.app.kernel.workflow();sid=value['study_id']
        view=self.app.views.module(sid,'A00')
        self.assertEqual(view['creation_plan']['initial_plan_id'],value['plan_id'])
        self.assertFalse(view['review']['continue']['available'])
        with patch.object(self.app.tasks,'submit',side_effect=AssertionError('不得调用旧编排')):
            result,code=self.app.post_review(SimpleNamespace(json=lambda:{'run_id':value['run_id'],'decision':'approved',
                'reviewer':'合成测试复核','note':'明确测试登记','after':'continue'}),sid,'A00')
            self.assertEqual(code,201);self.assertIsNone(result['task'])
            with self.assertRaises(ApiError):self.app.post_continue(SimpleNamespace(),sid)
        with self.assertRaises(ContractError):w.begin(sid,'A01',{}, {},'禁止旧OB/DL')
        sources=self.app.get_sources(SimpleNamespace(),sid,'A01')
        self.assertTrue(sources['enabled'])
        self.assertFalse(sources['acquisition']['enabled'])
        self.assertFalse(sources['can_process'])
        versions={k:sources[k] for k in ('expected_a00','expected_run','expected_staging')}
        with patch.object(self.app.tasks,'submit',side_effect=AssertionError('不得排队旧OB/DL获取')):
            with self.assertRaises(ApiError):self.app.post_source_acquire(SimpleNamespace(json=lambda:dict(versions,databases=['TCMSP'],reason='禁止旧参数')),sid)
        from modulea.tasks.worker import run_a01_acquire, run_a01_sources, run_a01_resolve
        with patch('modulea.tasks.worker.full_workflow',return_value=w),patch('science_modules.a01.collection_flow.acquire_sources',side_effect=AssertionError('不得旧获取')),patch('science_modules.a01.collection_flow.process',side_effect=AssertionError('不得旧整理')):
            for action in (run_a01_acquire,run_a01_sources,run_a01_resolve):
                with self.subTest(action=action.__name__),self.assertRaises(ValueError):
                    action(self.settings,{'study_id':sid,'task_id':'task_test','payload':'{}'},Mock())
        from modulea.tasks.worker import run_continue
        manager=Mock()
        with patch('modulea.tasks.worker.full_workflow',return_value=w), patch('auto_continue.continue_after_review',side_effect=AssertionError('不得旧接续')):
            message=run_continue(self.settings,{'study_id':sid,'task_id':'task_test'},manager)
        self.assertIn('未启动旧参数',message)

    def test_archived_initial_plan_tampering_blocks_read_and_retry(self):
        _,body=self.prepare();value=self.service.create(body);w=self.app.kernel.workflow();m=w.load(value['study_id'])
        path=verified_file(w.location(value['study_id']),m['initial_analysis_plan']);path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ContractError):context(w,value['study_id'])
        with self.assertRaises(ContractError):self.service.create(body)
