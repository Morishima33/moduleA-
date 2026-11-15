"""真实登记二版运行与合成外部执行：中断后只补缺区，完整组和稳定失败不重算。"""
from hashlib import sha256
import unittest
from unittest.mock import patch

from contracts import ContractError
import storage
from modulea.core.worker_io import WorkerIO
from science_modules.a06 import system_receptor_rescue as actual
from science_modules.a06 import plan_score_pair
from science_modules.a06 import system_receptor_rescue_v2 as actual_second
from modulea.core.rescue_recovery import inventory
from tests.modulea import test_system_receptor_rescue_v2_core as core_fixture
from tests.modulea import test_system_receptor_rescue_science as geometry
from tests.modulea.test_foundation_evidence import atom

SCORE_PAIR = actual._score_pair


class WorkerRegionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.seed=core_fixture.ReceptorRescueV2CoreTests('test_exact_incomplete_v2_request_resumes_same_run_and_checkpoint_dispatches')
        self.seed.setUp();self.addCleanup(self.seed.doCleanups)
        self.io=WorkerIO();self.addCleanup(self.io.close)
        self.w=self.io.wrap(self.seed.w);self.sid=self.seed.sid;self.home=self.w.location(self.sid)
        self.params={'scoring':'vina','exhaustiveness':8,'num_modes':2,'energy_range_kcal_mol':3,'seed':1}
        raw=b'synthetic executable bytes; never executed'
        self.seed.seed.configuration.update(vina_sha256=sha256(raw).hexdigest(),cpu_per_pair=1,
            timeout_seconds=1800,vina_parameters=self.params)
        body=self.seed.body();self.seed.science.compute.side_effect=RuntimeError('合成计算中断')
        with self.assertRaises(RuntimeError):self.seed.execute(body)
        m=self.w.load(self.sid);self.rid=m['current']['A06'];self.run=self.w.run(m,self.rid)
        self.folder=self.home/'runs/A06'/self.rid/'rescue'
        self.binary=self.folder/'software/vina.exe';self.binary.parent.mkdir(parents=True);self.binary.write_bytes(raw)
        def save(name,text,role):
            p=self.home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='ascii')
            return storage.file_record(self.home,p,role)
        self.compound={'compound_id':'C1','state':'ready','files':[save('inputs/ligand.pdbqt',atom(1,0)+'\n','prepared_ligand')]}
        self.receptor={'target_id':'HGNC:1','symbol':'合成受体','state':'ready','quality':'探索',
            'receptor':save('inputs/receptor.pdbqt',atom(7,1)+'\n','receptor'),'mode':'predicted_sites',
            'regions':[{'region_id':'region_1','center':[0,0,0],'size':[10,10,10]},
                       {'region_id':'region_2','center':[1,0,0],'size':[10,10,10]}]}
        self.scores={'region_1':-5.125,'region_2':-9.25}

    def synthetic_execution(self,*args):
        return geometry.SystemReceptorRescueScienceTests.synthetic_execution(self,*args)

    def score(self):
        return self.io.bind(SCORE_PAIR)(self.w,self.sid,self.run,1,self.compound,self.receptor,
                    self.binary,self.folder/'scores',lambda _:None)

    def test_interruption_reuses_registered_success_and_completes_only_missing_region(self):
        def interrupt(*args):
            if args[-2]['region_id']=='region_2':raise RuntimeError('合成断电')
            return self.synthetic_execution(*args)
        with patch.object(plan_score_pair,'execute',side_effect=interrupt),self.assertRaises(RuntimeError):self.score()
        checkpoints=self.w.load(self.sid)['analysis_plan_receptor_rescue_v2_checkpoints']
        self.assertEqual(len(checkpoints),1)
        original=storage.read_json(storage.verified_file(self.home,checkpoints[0]))
        pose=next(r for r in original['files'] if r['role']=='scoring_pose')
        before=(self.home/pose['path']).read_bytes()
        with patch.object(plan_score_pair,'execute',side_effect=self.synthetic_execution) as execute:
            row=self.score()
        self.assertEqual(execute.call_count,1)
        self.assertEqual(row['score'],-9.25)
        self.assertEqual((self.home/pose['path']).read_bytes(),before)
        with patch.object(plan_score_pair,'execute',side_effect=AssertionError('完整组禁止重算')):
            self.assertEqual(self.score(),row)
        # 未登记残件没有检查点，不能冒充已完成区域。
        orphan=self.folder/'scores/pair_000002/region_0001/orphan/execution.json'
        orphan.parent.mkdir(parents=True);orphan.write_text('{}')
        self.assertIsNone(self.w.read_analysis_plan_receptor_rescue_checkpoint(self.sid,self.rid,'pair_000002_region_0001'))

    def test_partial_failure_and_corrupt_file_do_not_hide_original_facts(self):
        self.scores['region_1']=None
        with patch.object(plan_score_pair,'execute',side_effect=self.synthetic_execution):row=self.score()
        self.assertTrue(row['partial_regions']);self.assertEqual(row['score'],-9.25)
        with patch.object(plan_score_pair,'execute',side_effect=AssertionError('稳定失败不重算')):
            self.assertEqual(self.score(),row)
            path=self.home/row['original_pose']['path'];path.write_bytes(b'corrupt')
            with self.assertRaises(ContractError):self.score()

    def test_read_only_inventory_validates_real_region_records_and_rejects_cross_region_swap(self):
        with patch.object(plan_score_pair,'execute',side_effect=self.synthetic_execution):row=self.score()
        source={'baseline_receptors':[self.receptor],'fixed':{'receptors':[self.receptor]},
            'baseline_packet':{'compounds':[self.compound],'pairs':[dict(compound_id='C1',target_id='HGNC:1',state='NA')]},
            'fact':{'compounds':[self.compound]}}
        before={str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        # 来源规范已有独立生产回归；此测试只替代来源读取，区域/命令/MODEL1使用真实冻结校验器。
        with patch('science_modules.a06.system_receptor_rescue_v2',actual_second), \
             patch.object(actual_second,'source_data',return_value=source), \
             patch.object(actual_second,'_read_baseline',return_value=None):
            result=inventory(self.io,self.w,self.sid,self.run)
            self.assertEqual(result['registered_successful_regions'],2)
            self.assertEqual(len(result['registered_complete_groups']),1)
            self.assertEqual(result['remaining'],[])
            self.assertEqual(before,{str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
            m=self.w.load(self.sid);ref=m['analysis_plan_receptor_rescue_v2_checkpoints'][0]
            cp=storage.read_json(self.home/ref['path'])
            cp['payload']['execution']=row['regions'][1]['execution']
            storage.write_json(self.home/ref['path'],cp,replace=True)
            m['analysis_plan_receptor_rescue_v2_checkpoints'][0]=storage.file_record(self.home,self.home/ref['path'],ref['role'])
            self.w.save(m)
            with self.assertRaises(ContractError):inventory(self.io,self.w,self.sid,self.run)


if __name__=='__main__':unittest.main()
