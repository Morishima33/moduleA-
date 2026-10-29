"""合成几何的真实Meeko/Vina同研究报告夹具，不证明真实身份或结合。"""
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from storage import read_json,write_json,file_record,verified_file
from modulea.core import system_validation,plan_reports
from science_modules.a06 import plan_preparation_v2 as prep,reference_review,plan_scoring
from science_modules.a06.plan_quality_engine_v2 import prepare_compounds,prediction_box
from science_modules.a06.automatic_engine import preparation_source
from science_modules.a06.two_pass import pocket_key

class Sources:
    """与既有评分测试相同的合成几何，按本研究实际固定名单建档，不添加额外受体。"""
    def connect(self,home,packet,folder,progress):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        import gemmi
        from docking_audit import ligand_identity
        folder.mkdir(parents=True,exist_ok=False)
        mol=Chem.AddHs(Chem.MolFromSmiles('CCO'));assert AllChem.EmbedMolecule(mol,randomSeed=1)==0
        sdf=Chem.MolToMolBlock(mol)+'\n> <PUBCHEM_COMPOUND_CID>\n123\n\n$$$$\n'
        path=folder/'explicit_synthetic_ligand.sdf';path.write_text(sdf,encoding='utf8');sdf_ref=file_record(home,path,'synthetic_source_3d')
        self.pdb=('ATOM      1  CA  ALA A  10       0.000   1.000   2.000  1.00  0.00           C  \n'
                  'ATOM      2  C   ALA A  10       2.000   4.000   6.000  1.00  0.00           C  \nEND\n')
        structure=gemmi.read_pdb_string(self.pdb);structure.name='1ABC';structure.setup_entities()
        cif=folder/'explicit_synthetic_1ABC.cif';cif.write_text(structure.make_mmcif_document().as_string(),encoding='utf8');cif_ref=file_record(home,cif,'synthetic_source_structure')
        note=folder/'synthetic_scope.json';write_json(note,{'synthetic':True,'real_official_request_performed':False,
            'real_chemical_identity_verified':False,'purpose':'仅测试Meeko/Vina和归档，不作为任何真实成分结构或结合证据'})
        spec={'source_type':'experimental','pdb_id':'1ABC','chains':['A'],'uniprot':'P12345','pocket':'p2rank','altloc':None}
        candidate={'spec':spec,'identity':[{'uniprot':'P12345','identity_check':'matched'}],'cif':cif_ref}
        return {'id':'explicit_synthetic_scoring','files':[sdf_ref,cif_ref,file_record(home,note,'synthetic_scope')],
            'compounds':[{**packet['compounds'][0],'state':'connected','name_zh':'明确合成结构测试','cid':123,'identity_matched':True,
                'audit':ligand_identity(sdf,123,Chem.MolToInchiKey(mol)),'sdf':sdf_ref},
                *[{**r,'state':'NA','reason_zh':'明确合成保留缺失成分'} for r in packet['compounds'][1:]]],
            'receptors':[{**packet['receptors'][0],'state':'connected','candidates':[candidate]},
                *[{**r,'state':'NA','reason_zh':'明确合成保留缺失受体','candidates':[]} for r in packet['receptors'][1:]]]}
    def prepare(self,home,connection,folder,tools,progress,config):
        compounds=prepare_compounds(home,preparation_source(connection),{'compounds':[{'compound_id':connection['compounds'][0]['compound_id'],'status':'use'}]},folder/'quality',progress)
        assert compounds[0]['state']=='ready',compounds[0]
        compounds.extend({'compound_id':r['compound_id'],'state':'NA','reason_zh':r['reason_zh']} for r in connection['compounds'][1:])
        target=connection['receptors'][0];candidate=target['candidates'][0];directory=folder/'quality/receptor';directory.mkdir(parents=True)
        pdb=directory/'input.pdb';pdb.write_text(self.pdb,encoding='ascii');receptor=directory/'receptor.pdbqt'
        receptor.write_text('\n'.join(line[:77]+'C' for line in self.pdb.splitlines() if line.startswith('ATOM'))+'\n',encoding='ascii')
        prediction={'rank':'1','score':'9.0','probability':'0.9','center_x':'1','center_y':'2','center_z':'3','residue_ids':'A_10'};refs=[]
        for serial in (1,2):
            path=directory/f'explicit_synthetic_prediction_{serial}.csv';path.write_text(','.join(prediction)+'\n'+','.join(prediction.values())+'\n',encoding='utf8');refs.append(file_record(home,path,'p2rank_prediction'))
        pocket={'rank':1,'runs':[prediction,prediction],'mapped_indices':['A_10'],'confirmation':{}};pocket['pocket_key']=pocket_key(candidate['spec'],pocket);self.key=pocket['pocket_key']
        evidence={'structure_id':'1ABC','identity':{'target_id':target['target_id'],'uniprot':'P12345','species':9606,'polymer_type':'Protein','sequence_matches':True,'chains':['A']},
            'receptor_ready':True,'pocket_complete':True,'environment_resolved':True,'error_zh':'明确合成两次预测一致，等待测试采用',
            'receptor':file_record(home,receptor,'receptor'),'pocket':pocket,'box':prediction_box(self.pdb,prediction,config['box_padding']),
            'predicted_pocket':{'files':refs,'input_pdb':file_record(home,pdb,'p2rank_input_pdb')},
            'files':refs+[file_record(home,receptor,'receptor'),file_record(home,pdb,'p2rank_input_pdb')]}
        assessment=prep.assess_plan_attempt(candidate['spec'],evidence,target,2,config)
        receptors=[{'target_id':target['target_id'],'symbol':target['symbol'],'state':'NA','quality':'待核查','reason_zh':assessment['reason_zh'],
            'attempts':[{'candidate':candidate,'evidence':evidence,'assessment':assessment}]}]
        receptors.extend({'target_id':r['target_id'],'symbol':r['symbol'],'state':'NA','quality':'待核查','reason_zh':r['reason_zh'],'attempts':[]} for r in connection['receptors'][1:])
        return compounds,receptors

def publish_scored_report(w,sid,tools):
    """同一真实非空链追加一组探索评分和一组NA，旧报告、原R及全部历史保持。"""
    home=w.location(sid);m=w.load(sid);fixed=read_json(verified_file(home,m['analysis_plan_a06_input_records'][-1]))
    input_id=fixed['input_id'];source=Sources()
    with patch.object(prep,'connect',side_effect=source.connect),patch.object(prep,'prepare',side_effect=source.prepare):
        prepared=prep.run(w,sid,{'request_id':'planprep_'+uuid4().hex,'expected_input_id':input_id,'author':'明确合成评分测试',
            'note':'仅合成几何、真实Meeko；不证明真实成分结构或结合','confirmed':True},Path(tools),lambda _:None)
    pocket=w.publish_analysis_plan_a06_pocket_review(sid,{'request_id':'pocketreq_'+uuid4().hex,'expected_input_id':input_id,
        'expected_preparation_run_id':prepared['run_id'],'reviewer':'明确合成评分测试复核','note':'仅合成位点用于探索测试','confirmed':True,
        'decisions':[{'target_id':row['target_id'],'pocket_key':source.key if index==0 else None} for index,row in enumerate(fixed['packet']['receptors'])]})
    reference=reference_review.run(w,sid,{'request_id':'refreq_'+uuid4().hex,'expected_input_id':input_id,
        'expected_preparation_run_id':pocket['run_id'],'reviewer':'明确合成评分测试复核','note':'合成预测位点，不提升严格等级','confirmed':True,'choices':[]},Path(tools),lambda _:None)['review']
    qualified=w.publish_analysis_plan_a06_reference_qualification_v2(sid,{'request_id':'refprep_'+uuid4().hex,'expected_input_id':input_id,
        'expected_preparation_run_id':pocket['run_id'],'expected_review_id':reference['review_id'],'reviewer':'明确合成评分测试复核',
        'note':'测试原参考规则','confirmed':True})
    reviewable=w.publish_analysis_plan_a06_reviewable(sid,{'request_id':'reviewprep_'+uuid4().hex,'expected_input_id':input_id,
        'expected_preparation_run_id':qualified['run_id'],'reviewer':'明确合成评分测试复核','note':'合成准备进入技术测试复核','confirmed':True})
    review=w.review(sid,reviewable['run_id'],'approved','明确合成评分测试复核','只对合成技术测试，不代表用户或正式研究批准')
    before_scoring=w.load(sid)
    scoring=plan_scoring.run(w,sid,{'request_id':'scoreq_'+uuid4().hex,'expected_preparation_run_id':reviewable['run_id'],
        'expected_preparation_review_id':review['review_id'],'expected_input_id':input_id,'expected_a06_run_id':None,
        'operator':'明确合成评分测试','note':'合成几何的真实Vina执行，保持NA，不证明科研结合','confirmed':True},Path(tools),lambda _:None)
    for module in ('A06_PREP','A06'):
        expected=system_validation.request(w,sid,w.load(sid)['current'][module])
        value=w.validate_analysis_plan_scientific_run(sid,{key:expected[key] for key in ('expected_run_id','expected_input_hash')}|{'request_id':'syscheckreq_'+uuid4().hex})
        assert value['passed'],value
    before_report=w.load(sid);value=plan_reports.info(w,sid);assert value['enabled'],value
    from science_modules.a05 import plan_flow
    with patch.object(plan_flow,'r_call',side_effect=AssertionError('报告不能重算R')):
        report=w.publish_analysis_plan_report(sid,{key:value[key] for key in ('expected_report_run_id','expected_input_hash')}|{
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成评分测试','note':'同研究实际评分与NA的报告','confirmed':True})
    return before_scoring,scoring,before_report,report
