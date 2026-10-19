"""虚构来源验证第二版补齐，不联网、不计算真实研究、不借用另一项目原件。"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import urllib.error
from urllib.parse import urlsplit,parse_qs

from contracts import ContractError, fingerprint
from storage import file_record, write_json, read_json, verified_file, new_id
from science_modules.a06.automatic_coverage_sources import Fetcher, pages, sequence_scope, conformer, published_model
from science_modules.a06.automatic_coverage_prepare import prepare, check_exploration, region_confidence
from science_modules.a06.automatic_coverage_engine import score_pair
from science_modules.a06.automatic_coverage_rules import VERSION, POLICY


def source_fixture(root, alternate=False):
    """两残基虚构蛋白及明确线性映射，保留真实文件供结构解析。"""
    import gemmi
    st=gemmi.Structure();model=gemmi.Model('1');chain=gemmi.Chain('A')
    for index,name in enumerate(('ALA','GLY'),1):
        residue=gemmi.Residue();residue.name=name;residue.seqid=gemmi.SeqId(index,' ')
        for offset,atom_name in enumerate(('N','CA','C','O')+ (('CB',) if index==1 else ())):
            for alt in ('A','B') if alternate and atom_name=='CB' else ('',):
                atom=gemmi.Atom();atom.name=atom_name;atom.element=gemmi.Element('N' if atom_name=='N' else 'O' if atom_name=='O' else 'C')
                atom.pos=gemmi.Position(index*4+offset*.5,offset*.3,0)
                atom.b_iso=85;atom.occ=.5 if alt else 1
                if alt:atom.altloc=alt
                residue.add_atom(atom)
        chain.add_residue(residue)
    model.add_chain(chain);st.add_model(model);st.setup_entities()
    doc=st.make_mmcif_document();block=doc.sole_block()
    block.set_pair('_entry.id','1ABC')
    block.set_mmcif_category('_struct_ref_seq.',{'pdbx_strand_id':['A'],'pdbx_db_accession':['P12345'],'pdbx_auth_seq_align_beg':['1'],'pdbx_auth_seq_align_end':['2'],'db_align_beg':['1'],'db_align_end':['2']})
    cif=root/'source.cif';doc.write_file(str(cif))
    spec={'source_type':'experimental','pdb_id':'1ABC','uniprot':'P12345','chains':['A'],'pocket':'p2rank','altloc':'A' if alternate else None}
    official={'primaryAccession':'P12345','organism':{'taxonId':9606},'sequence':{'value':'AGQ'}}
    return st,cif,spec,official


class SourceTests(unittest.TestCase):
    def test_pagination_continues_past_twenty(self):
        starts=[]
        class Fake:
            def get(self,url):
                start=json.loads(parse_qs(urlsplit(url).query)['json'][0])['request_options']['paginate']['start'];starts.append(start)
                ids=range(20) if start==0 else range(20,23)
                return {'total_count':23,'result_set':[{'identifier':f'1A{i:02d}_1'} for i in ids]},None
        self.assertEqual(len(list(pages('P12345',Fake(),lambda x:None))),23)
        self.assertEqual(starts,[0,20])

    def test_incomplete_and_duplicate_pages_are_not_zero(self):
        for response in ({'total_count':2,'result_set':[]},{'total_count':2,'result_set':[{'identifier':'1ABC_1'},{'identifier':'1ABC_1'}]}):
            fake=type('Fake',(),{'get':lambda self,url:(response,None)})()
            with self.assertRaises(ContractError):list(pages('P12345',fake,lambda x:None))

    def test_three_transient_attempts_and_archived_failures(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);fetch=Fetcher(root,root/'raw')
            with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('isolated EOF')) as transport,self.assertRaises(urllib.error.URLError):
                fetch.get('https://rest.uniprot.org/test')
            self.assertEqual(transport.call_count,3)
            self.assertEqual(len(fetch.records),3)
            self.assertTrue(all(read_json(verified_file(root,r))['state']=='failed' for r in fetch.records))

    def test_permanent_error_not_retried_and_nonofficial_rejected(self):
        with TemporaryDirectory() as folder:
            fetch=Fetcher(Path(folder),Path(folder)/'raw')
            with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('x',404,'not found',{},None)) as transport,self.assertRaises(urllib.error.HTTPError):
                fetch.get('https://rest.uniprot.org/test')
            self.assertEqual(transport.call_count,1)
            with self.assertRaises(ContractError):fetch.get('https://example.com/file')

    def test_actual_sequence_allows_matching_fragment_not_mutation(self):
        with TemporaryDirectory() as folder:
            _,cif,spec,official=source_fixture(Path(folder))
            result=sequence_scope(cif.read_text('utf-8'),spec,official)
            self.assertTrue(result['matched']);self.assertFalse(result['full_length'])
            self.assertEqual(result['mapped_positions'],[1,2])
            official['sequence']['value']='AAQ'
            with self.assertRaises(ContractError):sequence_scope(cif.read_text('utf-8'),spec,official)

    def test_complete_tied_conformer_is_deterministic(self):
        with TemporaryDirectory() as folder:
            _,cif,_,_=source_fixture(Path(folder),True)
            selected,proof=conformer(cif.read_text('utf-8'),['A'])
            self.assertEqual(selected,'A');self.assertTrue(proof['tie'])

    def test_published_model_identity_and_pae(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);_,cif,_,official=source_fixture(root)
            metadata={'uniprotAccession':'P12345','entryId':'AF-P12345-F1','uniprotStart':1,'uniprotEnd':2,'cifUrl':'https://alphafold.ebi.ac.uk/model.cif','paeDocUrl':'https://alphafold.ebi.ac.uk/pae.json'}
            class Fake:
                def __init__(self):self.root=root
                def get(self,url,suffix='json'):
                    if url.endswith('/P12345'):return [metadata],None
                    if suffix=='cif':return {},file_record(root,cif,'source')
                    path=root/'pae.json';write_json(path,[{'predicted_aligned_error':[[0,1],[1,0]]}])
                    return read_json(path),file_record(root,path,'pae')
            value=published_model({'target_id':'HGNC:1'},'P12345',official,Fake())
            self.assertEqual(value['spec']['source_type'],'alphafold')
            self.assertEqual(value['confidence']['plddt'],[85,85])


class PreparationTests(unittest.TestCase):
    def test_independent_alternative_used_before_model(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            row={'target_id':'HGNC:1','symbol':'TEST','state':'connected','uniprot':'P12345','official_sequence':{},'official_sequence_file':{},'candidates':[{'spec':{'source_type':'experimental','pdb_id':'1ABC','pocket':'p2rank'}}]}
            alternative={'spec':{'source_type':'experimental','pdb_id':'2ABC','pocket':'p2rank'}}
            wf=type('Workflow',(),{'location':lambda self,sid:root})()
            def explore_fake(root,row,origin,*args):
                if origin['spec']['pdb_id']=='1ABC':raise ValueError('isolated original failed')
                return {'state':'ready','quality':'探索','origin':origin,'reason_zh':'synthetic','regions':[]}
            with patch('science_modules.a06.automatic_coverage_prepare.explore',side_effect=explore_fake),patch('science_modules.a06.automatic_coverage_prepare.experimental_candidates',return_value=iter([alternative])),patch('science_modules.a06.automatic_coverage_prepare.published_model') as model:
                result=prepare(wf,'study',{},row,root/'quality',root,root,root,'auto',lambda x:None)
            self.assertEqual(result['state'],'ready');self.assertEqual(result['quality'],'探索')
            self.assertEqual(result['selected_candidate']['spec']['pdb_id'],'2ABC');model.assert_not_called()

    def test_published_model_after_experimental_failure(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            row={'target_id':'HGNC:1','symbol':'TEST','state':'connected','uniprot':'P12345','official_sequence':{},'official_sequence_file':{},'candidates':[{'spec':{'source_type':'experimental','pdb_id':'1ABC','pocket':'p2rank'}}]}
            model={'spec':{'source_type':'alphafold','model_id':'AF-P12345-F1','pocket':'p2rank'}}
            wf=type('Workflow',(),{'location':lambda self,sid:root})()
            def explore_fake(root,row,origin,*args):
                if origin['spec']['source_type']=='experimental':raise ValueError('isolated failed')
                return {'state':'ready','quality':'探索','origin':origin,'reason_zh':'synthetic','regions':[]}
            with patch('science_modules.a06.automatic_coverage_prepare.explore',side_effect=explore_fake),patch('science_modules.a06.automatic_coverage_prepare.experimental_candidates',return_value=iter([])),patch('science_modules.a06.automatic_coverage_prepare.published_model',return_value=model):
                result=prepare(wf,'study',{},row,root/'quality',root,root,root,'auto',lambda x:None)
            self.assertEqual(result['selected_candidate']['spec']['source_type'],'alphafold')
            self.assertEqual(result['quality'],'探索')

    def test_regional_confidence_not_whole_protein_mean(self):
        with TemporaryDirectory() as folder:
            st,cif,spec,official=source_fixture(Path(folder))
            origin={'cif_text':cif.read_text('utf-8'),'confidence':{'plddt':[99,69],'pae':[[0,1],[1,0]]}}
            result=region_confidence(origin,{'prediction':{'residue_ids':'A_1 A_2'}},st.make_pdb_string())
            self.assertFalse(result['passed'])
            origin['confidence']['plddt']=[85,85]
            self.assertTrue(region_confidence(origin,{'prediction':{'residue_ids':'A_1 A_2'}},st.make_pdb_string())['passed'])

    def test_score_uses_minimum_region_top1_and_keeps_failures(self):
        receptor={'target_id':'HGNC:1','receptor':{},'mode':'predicted_sites','regions':[{'region_id':'pocket_1'},{'region_id':'pocket_2'},{'region_id':'pocket_3'}]}
        facts=[{'region_id':'pocket_1','state':'completed','score':-6.1,'pose':{}}, {'region_id':'pocket_2','state':'completed','score':-7.2,'pose':{}}, {'region_id':'pocket_3','state':'NA','score':None,'reason_zh':'synthetic failure'}]
        for r in receptor['regions']:r.update(center=[0,0,0],size=[10,10,10])
        fake_path=type('Path',(),{'read_text':lambda *a:'synthetic'})()
        with patch('science_modules.a06.trial_compute.score_region',side_effect=facts),patch('science_modules.a06.automatic_coverage_engine.verified_file',return_value=fake_path),patch('docking_redocking._poses',return_value=[{}]),patch('docking_redocking._inside_box',return_value={'passed':True}):
            result=score_pair(Path('.'),Path('.'),Path('binary'),{},receptor)
        self.assertEqual(result['score'],-7.2);self.assertEqual(result['region_id'],'pocket_2')
        self.assertTrue(result['partial_regions']);self.assertEqual(len(result['regions']),3)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from modulea.devtools.demo_data import build
        cls.base=TemporaryDirectory();cls.sid=build(Path(cls.base.name))

    @classmethod
    def tearDownClass(cls):cls.base.cleanup()

    def setUp(self):
        from test_automatic_docking import AutomaticTests
        AutomaticTests.setUp(self)
        from modulea.core.automatic_coverage import AutomaticCoverageWorkflow
        self.old=self.connection
        self.workflow=AutomaticCoverageWorkflow(self.data)
        _,bound=self.workflow.automatic_binding(self.sid)
        self.key=fingerprint(bound)
        self.packet=dict(self.packet,id=new_id('connection'),policy=POLICY,binding=self.key)
        self.connection=self.workflow.save_automatic_connection(self.sid,self.key,self.packet,[])
        self.payload=dict(self.payload,policy_version=VERSION,expected_binding=self.key,expected_connection_id=self.connection['id'])

    def test_new_policy_does_not_inherit_old_authorization(self):
        with self.assertRaises(ContractError):
            self.workflow.authorize_automatic(self.sid,dict(self.payload,policy_version='A06.automatic.1'))
        record=self.workflow.authorize_automatic(self.sid,self.payload)
        self.assertIsNone(read_json(verified_file(self.home,record['authorization']))['approval'])

    def test_new_policy_migration_note_never_signs_or_changes_study(self):
        from modulea.core.automatic_coverage import automatic_context
        m=self.workflow.load(self.sid);m['automatic_connections']=[self.old]
        self.workflow.save(m)
        before=self.workflow.load(self.sid)
        with patch('science_modules.a06.candidates.build',return_value={'degree_top15':self.receptors}):
            context=automatic_context(self.workflow,before)
        self.assertIsNone(context['connection']);self.assertTrue(context['migration_note_zh'])
        self.assertEqual(before,self.workflow.load(self.sid))

    def test_dynamic_exception_matrix_pipeline_is_archived(self):
        from science_modules.a06.automatic_coverage_engine import run,validator
        self.workflow.validators['A06']=validator(self.data,lambda *args:None)
        binary=Path(self.temp.name)/'tools/environments/vina_1.2.7/vina_1.2.7_win.exe'
        binary.parent.mkdir(parents=True);binary.write_bytes(b'synthetic version probe only')
        version=type('Version',(),{'returncode':0,'stdout':'AutoDock Vina v1.2.7'})()
        with patch('science_modules.a06.automatic_coverage_engine.subprocess.run',return_value=version),patch('science_modules.a06.quality_engine.prepare_compounds',return_value=[]):
            result=run(self.workflow,self.sid,self.payload,binary.parents[2],Path(__file__).resolve().parents[2],{'synthetic':True},lambda x:None,Path(self.temp.name))
        self.assertEqual(result['summary']['计划组合数'],6)
        self.assertEqual(result['summary']['成功组合数'],0)
        self.assertTrue(result['summary']['handoff_blocked'])
        self.assertEqual(result['summary']['science_version'],VERSION)
        self.assertTrue(all(r['score'] is None for r in result['tables']['pairs']))

    def test_connect_reuses_successful_same_study_objects_only(self):
        from science_modules.a06.automatic_coverage_sources import connect
        m=self.workflow.load(self.sid)
        packet=read_json(verified_file(self.home,self.connection['packet']))
        packet['compounds'][0]['state']='connected'
        packet['id']=new_id('connection')
        self.workflow.save_automatic_connection(self.sid,self.key,packet,[])
        context={'compounds':self.compounds,'receptors':self.receptors}
        bound=self.workflow.automatic_binding(self.sid)[1]
        with patch.object(self.workflow,'candidate_binding',return_value={}),patch.object(self.workflow,'candidate_record',return_value=({},None)),patch('science_modules.a06.plan_adapter.source_context',return_value=context),patch('science_modules.a06.automatic_coverage_sources.compound_source',side_effect=lambda r,f:dict(r,state='connected')) as compound,patch('science_modules.a06.automatic_coverage_sources.receptor_sources',side_effect=lambda r,f,p:dict(r,state='unavailable',candidates=[])):
            record=connect(self.workflow,self.sid,{'expected_binding':self.key,'connection_id':new_id('connection')},lambda x:None)
        self.assertEqual(compound.call_count,1)
        actual=read_json(verified_file(self.home,record['packet']))
        self.assertEqual(actual['compounds'][0]['reused_connection'],packet['id'])
        self.assertEqual(actual['study_id'],self.sid)
        self.assertEqual(self.workflow.load(self.sid)['reviews'],m['reviews'])

    def test_successful_multiregion_pipeline_rejects_changed_score(self):
        """模拟准备和Vina，实际重核坐标、完整预测表、区域集合及归档命令。"""
        from science_modules.a06.automatic_coverage_engine import run,validator
        from science_modules.a06.automatic_coverage_prepare import check_exploration
        from science_modules.a06.trial_rules import VINA,fingerprint as execution_key
        from docking_p2rank import box_from_prediction
        from docking_top10_execute import _vina_arguments
        fixtures=self.home/'real_format_fixture';fixtures.mkdir()
        st,cif,spec,official=source_fixture(fixtures)
        official_file=fixtures/'official.json';write_json(official_file,official)
        original={'spec':spec,'cif':file_record(self.home,cif,'source'),'official_sequence':official,
            'official_sequence_file':file_record(self.home,official_file,'official_sequence'),'sequence_scope':sequence_scope(cif.read_text('utf-8'),spec,official),'identity':[{'identity_check':'matched','uniprot':'P12345'}]}
        sdf=fixtures/'source.sdf';sdf.write_text('synthetic preparation input',encoding='utf-8')
        packet=deepcopy(self.packet);packet['id']=new_id('connection')
        packet['compounds'][0].update(state='connected',name_zh='虚构',cid=1,audit={},sdf=file_record(self.home,sdf,'source'))
        packet['receptors'][1].update(state='connected',candidates=[original],uniprot='P12345')
        packet['files']=[original['cif'],packet['compounds'][0]['sdf']]
        connection=self.workflow.save_automatic_connection(self.sid,self.key,packet,packet['files'])
        payload=dict(self.payload,expected_connection_id=connection['id'])
        self.workflow.validators['A06']=validator(self.data,lambda *a:None)
        tools=Path(self.temp.name)/'tools';binary=tools/'environments/vina_1.2.7/vina_1.2.7_win.exe'
        binary.parent.mkdir(parents=True);binary.write_bytes(b'synthetic never executed')
        qt=fixtures/'ligand.pdbqt'
        line=f"ATOM  {1:5d}  C   LIG A   1    {6:8.3f}{0:8.3f}{0:8.3f}  0.00  0.00    {0:6.3f} C\n"
        line=line[:77]+'C\n';qt.write_text(line,encoding='ascii')
        ligand={'compound_id':self.compounds[0]['compound_id'],'state':'ready','files':[file_record(self.home,qt,'prepared_ligand')],'reason_zh':'synthetic'}
        def prepare_fake(workflow,sid,conn,row,folder,*args):
            if row['target_id']!=self.receptors[1]['target_id']:
                return dict(row,state='NA',quality='未通过',reason_zh='synthetic',attempts=[])
            folder.mkdir(parents=True)
            import gemmi
            from docking_top10_execute import _protein_pdb
            converted=folder/'original.pdb';converted.write_text(gemmi.make_structure_from_block(gemmi.cif.read_string(cif.read_text('utf-8')).sole_block()).make_pdb_string(),encoding='ascii')
            protein=_protein_pdb(converted,spec['chains'],spec.get('altloc'))
            observed=folder/'observed.pdb';observed.write_text(protein,encoding='ascii')
            repaired=folder/'repaired.pdb';repaired.write_text(protein,encoding='ascii')
            files=[];raw={'rank':'1','score':'1','probability':'1','center_x':'6','center_y':'0','center_z':'0','residue_ids':'A_1 A_2'}
            for i in range(2):
                csv=folder/f'prediction_{i}.csv';csv.write_text(','.join(raw)+'\n'+','.join(raw.values())+'\n',encoding='utf-8')
                files.append(file_record(self.home,csv,'p2rank_prediction'))
            region=dict(box_from_prediction(st.make_pdb_string(),raw),region_id='pocket_1',prediction=raw)
            value=dict(row,state='ready',quality='探索',selected_candidate=original,origin=original,spec=spec,source=original['cif'],
                receptor=file_record(self.home,qt,'receptor'),repair_input=file_record(self.home,observed,'observed_input'),repair_output=file_record(self.home,repaired,'repaired_output'),
                original_conversion=file_record(self.home,converted,'source_conversion'),
                repair={'added_atoms':[],'original_coordinates_unchanged':True},prediction_files=files,mode='predicted_sites',regions=[region],reason_zh='synthetic',attempts=[])
            regions,rejected=check_exploration(self.home,original,value)
            value.update(regions=regions,rejected_regions=rejected)
            return value
        def score_fake(root,folder,exe,compound,receptor,region):
            out=folder/'scores'/compound['compound_id']/receptor['target_id'].replace(':','_')/region['region_id']/'poses.pdbqt'
            out.parent.mkdir(parents=True);out.write_text('MODEL 1\nREMARK VINA RESULT: -6.321 0.0 0.0\n'+line+'ENDMDL\n',encoding='ascii')
            config={'compound':ligand['files'][0],'receptor':receptor['receptor'],'region':region,'version':'synthetic','vina':VINA,'executable_sha256':__import__('hashlib').sha256(exe.read_bytes()).hexdigest()}
            return {'region_id':region['region_id'],'state':'completed','score':-6.321,'pose':file_record(root,out,'pose'),'config':config,'input_key':execution_key(config),'returncode':0,'reason_zh':'',
                'command':_vina_arguments(exe,root/receptor['receptor']['path'],qt,region,out)+['--cpu','2']}
        version=type('Version',(),{'returncode':0,'stdout':'AutoDock Vina v1.2.7'})()
        with patch('science_modules.a06.automatic_coverage_engine.subprocess.run',return_value=version),patch('science_modules.a06.quality_engine.prepare_compounds',return_value=[ligand]),patch('science_modules.a06.automatic_coverage_prepare.prepare',side_effect=prepare_fake),patch('science_modules.a06.trial_compute.score_region',side_effect=score_fake):
            result=run(self.workflow,self.sid,payload,tools,Path(__file__).resolve().parents[2],{'synthetic':True},lambda x:None,fixtures)
        self.assertEqual(result['summary']['成功组合数'],1)
        self.assertEqual(result['summary']['严格受体数'],0)
        self.assertEqual(result['summary']['探索受体数'],1)
        m=self.workflow.load(self.sid)
        actual=read_json(verified_file(self.home,result['tables']['automatic_packet'][0]))
        next(r for r in actual['pairs'] if r['state']=='completed')['score']=-99
        forged=self.home/'changed.json';write_json(forged,actual)
        tables=dict(result['tables'],automatic_packet=[file_record(self.home,forged,'automatic_packet')])
        with self.assertRaises(ContractError):
            validator(self.data,lambda *a:None)(self.workflow.run(m,result['run_id']),result['summary'],tables,[],'success')


if __name__=='__main__':unittest.main()
