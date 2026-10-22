"""中断恢复只复用明确匹配的同运行区域，已有原值保持且不放宽原发布校验。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch, Mock
import json

from contracts import ContractError, fingerprint
from storage import file_record, write_json
from science_modules.a06 import interrupted_recovery as recovery
from science_modules.a06.trial_rules import VERSION, VINA
from docking_top10_execute import _vina_arguments


class RecoveryTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.folder=self.home/'runs/A06/run_synthetic/automatic'
        self.folder.mkdir(parents=True)
        self.binary=self.folder/'vina.exe';self.binary.write_bytes(b'fixed synthetic binary')
        ligand=self.folder/'ligand.pdbqt';ligand.write_text('synthetic ligand')
        receptor=self.folder/'receptor.pdbqt';receptor.write_text('synthetic receptor')
        self.compound={'compound_id':'C1','files':[file_record(self.home,ligand,'prepared_ligand')]}
        self.receptor={'target_id':'HGNC:1','receptor':file_record(self.home,receptor,'trial_receptor')}
        self.region={'region_id':'pocket_1','center':[0,0,0],'size':[20,20,20]}
        self.work=self.folder/'scores/C1/HGNC_1/pocket_1'

    def fact(self):
        self.work.mkdir(parents=True)
        pose=self.work/'poses.pdbqt';pose.write_text('synthetic pose')
        config=dict(compound=self.compound['files'][0],receptor=self.receptor['receptor'],region=self.region,
                    version=VERSION,vina=VINA,executable_sha256=file_record(self.home,self.binary,'vina')['sha256'])
        cmd=_vina_arguments(self.binary,self.home/self.receptor['receptor']['path'],self.home/self.compound['files'][0]['path'],self.region,pose)+['--cpu','2']
        row=dict(config=config,input_key=fingerprint(config),command=cmd,state='completed',returncode=0,
                 score=-6.123,pose=file_record(self.home,pose,'trial_pose'))
        write_json(self.work/'execution.json',row)
        return row

    def test_finished_region_returns_exact_original_without_execution(self):
        row=self.fact();before=(self.work/'execution.json').read_bytes()
        with patch('docking_redocking._poses',return_value=[{'score_kcal_mol':-6.123}]),patch.object(recovery,'execute_region') as execute:
            actual=recovery.recover_region(self.home,self.folder,self.binary,self.compound,self.receptor,self.region)
        self.assertEqual(actual,row);self.assertEqual((self.work/'execution.json').read_bytes(),before)
        execute.assert_not_called()

    def test_in_memory_tuple_and_archived_list_share_identical_scientific_input(self):
        self.region['center']=(0,0,0);self.region['size']=(20,20,20)
        self.fact()
        with patch('docking_redocking._poses',return_value=[{'score_kcal_mol':-6.123}]),patch.object(recovery,'execute_region') as execute:
            actual=recovery.recover_region(self.home,self.folder,self.binary,self.compound,self.receptor,self.region)
        self.assertEqual(actual['score'],-6.123);execute.assert_not_called()

    def test_changed_parameter_or_pose_is_rejected(self):
        row=self.fact();row['config']['vina']=dict(VINA,seed=999);write_json(self.work/'execution.json',row,replace=True)
        with self.assertRaises(ContractError):recovery.recover_region(self.home,self.folder,self.binary,self.compound,self.receptor,self.region)
        row['config']['vina']=VINA;write_json(self.work/'execution.json',row,replace=True)
        (self.work/'poses.pdbqt').write_text('tampered')
        with self.assertRaises(ContractError):recovery.recover_region(self.home,self.folder,self.binary,self.compound,self.receptor,self.region)

    def test_partial_directory_is_preserved_then_only_missing_region_executes(self):
        self.work.mkdir(parents=True);(self.work/'unfinished.txt').write_text('partial output')
        with patch.object(recovery,'execute_region',return_value={'state':'failed'}) as execute:
            row=recovery.recover_region(self.home,self.folder,self.binary,self.compound,self.receptor,self.region)
        execute.assert_called_once();self.assertEqual(row['state'],'failed');self.assertFalse(self.work.exists())
        self.assertEqual(len(list((self.folder/'recovery/interrupted_regions').rglob('unfinished.txt'))),1)

    def test_cached_source_requires_verified_file_and_never_networks(self):
        p=self.home/'official.json';p.write_text('{"species":9606}')
        rec=file_record(self.home,p,'source');fetch=SimpleNamespace(root=self.home,records=[])
        get=recovery.cached_get({'https://official.invalid/source':[rec]})
        self.assertEqual(get(fetch,'https://official.invalid/source')[0],{'species':9606})
        with self.assertRaises(ContractError):get(fetch,'https://other.invalid/source')
        p.write_text('{}')
        with self.assertRaises(ContractError):get(fetch,'https://official.invalid/source')

    def test_source_cache_prefers_this_attempt_over_other_archived_batches(self):
        own=self.home/'current/sources';other=self.home/'older/sources'
        own.mkdir(parents=True);other.mkdir(parents=True)
        for folder,value in [(own,'current'),(other,'old')]:
            (folder/'source.json').write_text(json.dumps({'batch':value}))
        current=file_record(self.home,own/'source.json','source');old=file_record(self.home,other/'source.json','source')
        fetch=SimpleNamespace(root=self.home,folder=own,records=[])
        get=recovery.cached_get({'https://official.invalid/source':[current,old]})
        data,record=get(fetch,'https://official.invalid/source')
        self.assertEqual(data,{'batch':'current'});self.assertEqual(record,current)
        with self.assertRaises(ContractError):
            recovery.cached_get({'https://official.invalid/source':[old]})(fetch,'https://official.invalid/source')

    def test_completed_or_other_run_cannot_be_resumed(self):
        workflow=Mock();workflow.validate_automatic_request.return_value=({'current':{'A06':'current'}},{},{})
        workflow.automatic_record.return_value={'state':'completed','run_id':'current'}
        with self.assertRaises(ContractError):recovery.run(workflow,'synthetic',{'request_id':'auto_synthetic'},None,None,Mock(),None)
        workflow.automatic_record.return_value={'state':'running','run_id':'other'}
        with self.assertRaises(ContractError):recovery.run(workflow,'synthetic',{'request_id':'auto_synthetic'},None,None,Mock(),None)

    def test_explicit_retry_routes_interrupted_authorization_to_resume_without_new_confirmation(self):
        from modulea.tasks.manager import TaskManager
        from modulea.config import Settings
        manager=TaskManager(Settings(project_root=self.home,data_root=self.home,runtime_dir=self.home/'runtime'))
        original={'request_id':'auto_synthetic','policy_version':'A06.automatic.3','expected_a06':None,'confirmed':True,'reviewer':'actual','note':'explicit'}
        with patch.object(manager,'_spawn'):
            first,_=manager.submit('synthetic','a06_auto_start','actual',dict(original,continuation_version='A06.connect_run.1'))
            manager.update(first['task_id'],state='interrupted')
            bad_retry,_=manager.submit('synthetic','a06_auto_start','actual',dict(original,continuation_version='A06.connect_run.1'))
            manager.update(bad_retry['task_id'],state='failed')
            auth=self.home/'authorization.json';write_json(auth,{'request':original})
            flow=Mock();flow.load.return_value={'current':{'A06':'current'}}
            flow.location.return_value=self.home
            flow.automatic_record.return_value={'state':'running','run_id':'current','authorization':file_record(self.home,auth,'authorization')}
            with patch('modulea.core.kernel.Kernel',return_value=SimpleNamespace(workflow=lambda:flow)):
                resumed,created=manager.retry(bad_retry['task_id'],'explicit retry')
            self.assertTrue(created);self.assertEqual(resumed['kind'],'a06_resume')
            self.assertEqual(json.loads(manager._raw(resumed['task_id'])['payload']),original)
            manager.update(bad_retry['task_id'],state='cancelled')
            with self.assertRaises(ValueError):manager.recovery_source(manager._raw(resumed['task_id']))


if __name__=='__main__':main()
