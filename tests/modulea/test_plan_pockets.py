"""口袋确认的隔离证据测试；合成结构与工具响应不作为真实研究。"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from contracts import ContractError
from modulea.config import Settings
from modulea.core.kernel import full_workflow
from modulea.tasks.worker import run_a06_plan_preparation
from science_modules.a06 import plan_preparation_v2 as prep
from science_modules.a06.plan_pockets import eligible_trace
from science_modules.a06.plan_pocket_review import validator
from science_modules.a06.plan_quality_engine_v2 import prediction_box, prepare_compounds
from science_modules.a06.automatic_engine import preparation_source
from science_modules.a06.two_pass import pocket_key
from storage import file_record, read_json, verified_file
import tests.modulea.test_plan_a04_selection_task as fixture


class PocketReviewTests(unittest.TestCase):
    """沿用真实新方案A04发布夹具，新增可逐字节核对的合成预测证据。"""
    def setUp(self):
        self.base = fixture.PlanA04SelectionTaskTests('test_a06_preparation_v2_archives_bound_config_and_delegates_v1')
        self.base.setUp()
        self.addCleanup(self.base.tearDown)
        base = self.base
        self.workflow = full_workflow(base.settings.data_root)
        self.sid = base.sid
        self.home = self.workflow.location(self.sid)
        selected = base.workflow.save_analysis_plan_a04_selection(self.sid, base.payload())['record']
        review = base.workflow.review_analysis_plan_a04_selection(
            self.sid, base.review_payload(selected['selection_id']))['review']
        self.input_record = base.workflow.save_analysis_plan_a06_preparation_input(
            self.sid, base.a06_payload(selected, review))['record']
        self.packet = self.input_record['packet']
        binary = Path(base.temp.name)/'vina.exe'; binary.write_bytes(b'isolated-not-vina')
        with patch.object(prep, '_version', return_value=binary), \
             patch.object(prep, 'connect', side_effect=self.connect), \
             patch.object(prep, 'prepare', side_effect=self.prepare):
            self.source_result = prep.run(self.workflow, self.sid, {
                'expected_input_id': self.input_record['input_id'], 'request_id': 'planprep_'+uuid4().hex,
                'author': '隔离测试', 'note': '合成两次预测与真实配体参数化', 'confirmed': True},
                Path(base.temp.name), lambda _: None)
        self.source_run_id = self.source_result['run_id']
        self.source_ref = self.source_result['tables']['preparation_packet'][0]
        self.source = read_json(verified_file(self.home, self.source_ref))
        self.key = self.source['receptors'][0]['attempts'][0]['evidence']['pocket']['pocket_key']

    def connect(self, home, packet, folder, progress):
        """仅创建测试用三维与结构原件；不请求公共数据库。"""
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from docking_audit import ligand_identity
        folder.mkdir(parents=True)
        mol = Chem.AddHs(Chem.MolFromSmiles('CCO'))
        self.assertEqual(AllChem.EmbedMolecule(mol, randomSeed=1), 0)
        sdf = Chem.MolToMolBlock(mol) + '\n> <PUBCHEM_COMPOUND_CID>\n123\n\n$$$$\n'
        path = folder/'ligand.sdf'; path.write_text(sdf, encoding='utf-8')
        sdf_ref = file_record(home, path, 'synthetic_source_3d')
        self.pdb = ('ATOM      1  CA  ALA A  10       0.000   1.000   2.000  1.00  0.00           C  \n'
                    'ATOM      2  C   ALA A  10       2.000   4.000   6.000  1.00  0.00           C  \nEND\n')
        import gemmi
        structure = gemmi.read_pdb_string(self.pdb)
        structure.name = '1ABC'; structure.setup_entities()
        cif = folder/'1ABC.cif'; cif.write_text(structure.make_mmcif_document().as_string(), encoding='utf-8')
        cif_ref = file_record(home, cif, 'synthetic_source_structure')
        first = packet['receptors'][0]
        spec = {'source_type':'experimental','pdb_id':'1ABC','chains':['A'],
                'uniprot':'P12345','pocket':'p2rank','altloc':None}
        candidate = {'spec':spec,'identity':[{'uniprot':'P12345','identity_check':'matched'}], 'cif':cif_ref}
        compound = {**packet['compounds'][0], 'state':'connected','name_zh':'合成成分',
                    'cid':123,'identity_matched':True,'audit':ligand_identity(sdf,123,Chem.MolToInchiKey(mol)), 'sdf':sdf_ref}
        return {'id':folder.parent.parent.name, 'files':[sdf_ref,cif_ref],
                'compounds':[compound, {**packet['compounds'][1], 'state':'NA','reason_zh':'测试保留缺失成分'}],
                'receptors':[{**first, 'state':'connected','candidates':[candidate]},
                             {**packet['receptors'][1], 'state':'NA','reason_zh':'测试保留缺失受体','candidates':[]}]}

    def prepare(self, home, source, folder, tools, progress, config):
        """配体使用真实Meeko；预测/受体由合成夹具提供并通过真实文件核验。"""
        compounds = prepare_compounds(home, preparation_source(source),
            {'compounds':[{'compound_id': source['compounds'][0]['compound_id'], 'status':'use'}]}, folder/'quality', progress)
        self.assertEqual(compounds[0]['state'], 'ready', compounds[0])
        compounds.append({'compound_id':source['compounds'][1]['compound_id'],'state':'NA','reason_zh':'测试保留缺失成分'})
        target = source['receptors'][0]
        candidate = target['candidates'][0]
        directory = folder/'quality/receptor'; directory.mkdir(parents=True)
        pdb = directory/'input.pdb'; pdb.write_text(self.pdb, encoding='ascii')
        receptor = directory/'receptor.pdbqt'
        lines = [line[:77]+'C' for line in self.pdb.splitlines() if line.startswith('ATOM')]
        receptor.write_text('\n'.join(lines)+'\n', encoding='ascii')
        shared = {'rank':'1','score':'9.0','probability':'0.9','center_x':'1','center_y':'2','center_z':'3','residue_ids':'A_10'}
        refs=[]
        for serial in (1,2):
            path=directory/f'prediction_{serial}.csv'
            path.write_text(','.join(shared)+'\n'+','.join(shared.values())+'\n',encoding='utf-8')
            refs.append(file_record(home,path,'p2rank_prediction'))
        pocket={'rank':1,'runs':[shared,shared],'mapped_indices':['A_10'],'confirmation':{}}
        pocket['pocket_key']=pocket_key(candidate['spec'],pocket)
        evidence={'structure_id':'1ABC','identity':{'target_id':target['target_id'],'uniprot':'P12345',
            'species':9606,'polymer_type':'Protein','sequence_matches':True,'chains':['A']},
            'receptor_ready':True,'pocket_complete':True,'environment_resolved':True,
            'error_zh':'两次首位口袋一致，仍待明确确认',
            'receptor':file_record(home,receptor,'receptor'), 'pocket':pocket,
            'box':prediction_box(self.pdb,shared,config['box_padding']),
            'predicted_pocket':{'files':refs,'input_pdb':file_record(home,pdb,'p2rank_input_pdb')},
            'files':refs+[file_record(home,receptor,'receptor'),file_record(home,pdb,'p2rank_input_pdb')]}
        assessment=prep.assess_plan_attempt(candidate['spec'],evidence,target,2,config)
        receptors=[{'target_id':target['target_id'],'symbol':target['symbol'],'state':'NA',
            'quality':'待核查','reason_zh':assessment['reason_zh'],
            'attempts':[{'candidate':candidate,'evidence':evidence,'assessment':assessment}]},
            {'target_id':source['receptors'][1]['target_id'],'symbol':source['receptors'][1]['symbol'],
             'state':'NA','quality':'待核查','reason_zh':'测试保留缺失受体','attempts':[]}]
        return compounds,receptors

    def payload(self, **changes):
        """默认明确采用首个口袋，另一个受体原样保留。"""
        return dict({'request_id':'pocketreq_'+uuid4().hex,'expected_input_id':self.input_record['input_id'],
                     'expected_preparation_run_id':self.source_run_id,'reviewer':'隔离核查人',
                     'note':'仅作合成预测位点测试','confirmed':True,
                     'decisions':[{'target_id':r['target_id'],'pocket_key':self.key if i==0 else None}
                                  for i,r in enumerate(self.packet['receptors'])]}, **changes)

    def test_confirmation_revision_preserves_sources_and_na_without_scoring(self):
        before=self.workflow.load(self.sid)
        hashes={r['path']:r['sha256'] for r in self.source_result['files']}
        body=self.payload()
        with patch('urllib.request.urlopen', side_effect=AssertionError('不得联网')), \
             patch('subprocess.run', side_effect=AssertionError('不得调用工具')):
            result=self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,body)
        self.assertEqual(result['summary']['ready_pairs'],1)
        self.assertEqual(result['summary']['na_pairs'],3)
        self.assertEqual(result['summary']['scored_pairs'],0)
        self.assertTrue(result['summary']['handoff_blocked'])
        self.assertTrue(all(r['score'] is None for r in result['tables']['planned_pairs']))
        self.assertEqual(self.workflow.load(self.sid)['reviews'],before['reviews'])
        self.assertEqual(self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,body)['run_id'],result['run_id'])
        self.assertFalse(self.workflow.approved(self.workflow.load(self.sid),result['run_id']))
        self.assertEqual({r['path']:file_record(self.home,self.home/r['path'],r['role'])['sha256']
                          for r in self.source_result['files']},hashes)
        self.assertFalse(self.source['receptors'][0]['attempts'][0]['evidence']['pocket']['confirmation'])
        adopted=read_json(verified_file(self.home,result['tables']['preparation_packet'][0]))['receptors'][0]['attempts'][0]['evidence']
        self.assertNotIn('error_zh',adopted)
        self.assertIn('source_preparation_note_zh',adopted)
        amended=self.payload(expected_preparation_run_id=result['run_id'],decisions=[
            {'target_id':r['target_id'],'pocket_key':None} for r in self.packet['receptors']])
        reverted=self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,amended)
        self.assertEqual(reverted['summary']['ready_pairs'],0)
        self.assertEqual(len(self.workflow.load(self.sid)['analysis_plan_a06_pocket_records']),2)
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,body)

    def test_route_readonly_submission_and_idempotent_response(self):
        base=self.base
        before=self.workflow.load(self.sid)
        status,info=base.call('GET',f'/studies/{self.sid}/analysis-plan/a06-pockets')
        self.assertEqual(status,200,info)
        self.assertTrue(info['items'][0]['options'][0]['eligible'])
        self.assertEqual(self.workflow.load(self.sid),before)
        base.settings.science_tools_root=Path(base.temp.name)
        body=self.payload()
        with patch.object(base.app.tasks,'_spawn'):
            status,queued=base.call('POST',f'/studies/{self.sid}/analysis-plan/a06-pockets/reviews',body)
        self.assertEqual(status,202,queued)
        self.assertEqual(queued['task']['kind'],'a06_plan_pocket_review')
        base.app.tasks.update(queued['task']['task_id'],state='cancelled')
        result=self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,body)
        status,repeated=base.call('POST',f'/studies/{self.sid}/analysis-plan/a06-pockets/reviews',body)
        self.assertEqual(status,200,repeated)
        self.assertEqual(repeated['run_id'],result['run_id'])

    def test_invalid_key_shape_and_raw_prediction_mismatch_are_rejected(self):
        before=self.workflow.load(self.sid)
        wrong=self.payload()
        wrong['decisions'][1]['pocket_key']=self.key
        for body in (wrong,self.payload(confirmed=False),dict(self.payload(),score=-8)):
            with self.assertRaises(ContractError):
                self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,body)
        self.assertEqual(before,self.workflow.load(self.sid))
        trace=deepcopy(self.source['receptors'][0]['attempts'][0])
        trace['evidence']['pocket']['runs'][0]['score']='10'
        with self.assertRaises(ContractError):
            eligible_trace(self.home,trace,self.source['receptors'][0],self.source['config'])
        prediction=self.home/trace['evidence']['predicted_pocket']['files'][0]['path']
        prediction.write_text('tampered',encoding='utf-8')
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,self.payload())

    def test_upstream_review_revocation_blocks_confirmation(self):
        manifest=self.workflow.load(self.sid)
        run_id=manifest['current']['A03_SELECT']
        previous=self.workflow.latest_review(manifest,self.workflow.run(manifest,run_id)['artifact_id'])
        self.workflow.review(self.sid,run_id,'pending','隔离测试','撤回选择批准',expected_review=previous['review_id'])
        with self.assertRaises(ContractError):
            self.workflow.publish_analysis_plan_a06_pocket_review(self.sid,self.payload())
        self.assertEqual(self.workflow.load(self.sid)['current']['A06_PREP'],self.source_run_id)
        self.assertFalse(self.workflow.load(self.sid).get('analysis_plan_a06_pocket_records'))

    def test_json_metadata_normalization_still_rejects_changed_parameters(self):
        modified=deepcopy(self.source)
        modified['compounds'][0]['preparation']['settings']['merge_these_atom_types']=['C']
        path=self.home/self.source_ref['path']
        path.write_text(json.dumps(modified,ensure_ascii=False),encoding='utf-8')
        tables=deepcopy(self.source_result['tables'])
        tables['preparation_packet']=[file_record(self.home,path,'preparation_packet')]
        run=self.workflow.run(self.workflow.load(self.sid),self.source_run_id)
        with self.assertRaises(ContractError):
            prep.validator(self.workflow.root,Mock())(run,self.source_result['summary'],tables,[],'success')


class PocketTaskTests(unittest.TestCase):
    def test_older_preparation_versions_delegate_to_frozen_validator(self):
        previous=Mock()
        validator(Path('unused'),previous)({'config':{'version':'A06.plan_preparation.2'}},{},{},[],'success')
        previous.assert_called_once()

    def test_task_uses_configured_isolated_interpreter_and_review_script(self):
        """后台入口使用服务端配置，不由请求决定解释器和工具。"""
        with tempfile.TemporaryDirectory() as name:
            settings=Settings(project_root=Path(name),runtime_dir=Path(name)/'runtime',
                              science_python='configured-python.exe',science_tools_root=Path(name)/'tools')
            def launch(command,**kwargs):
                output=Path(command[command.index('--result-file')+1])
                output.write_text(json.dumps({'run_id':'fixture','summary':{'ready_pairs':1,'pair_count':4}}),encoding='utf-8')
                return SimpleNamespace(stdout=['PROGRESS 核验原件\n'],wait=lambda:0)
            with patch('subprocess.Popen',side_effect=launch) as popen:
                run_a06_plan_preparation(settings,{'task_id':'task_fixture','study_id':'study_fixture',
                    'kind':'a06_plan_pocket_review','payload':'{}'},Mock())
            args=popen.call_args.args[0]
            self.assertEqual(args[0],'configured-python.exe')
            self.assertEqual(args[1:4],['-I','-S','-B'])
            self.assertTrue(args[4].endswith('run_a06_plan_pocket_review.py'))


if __name__ == '__main__':
    unittest.main()
