"""原生工具链隔离检查：准备/修补/双预测/评分/构象/图件；不创建研究或科研批准。"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE/'src'))


def main(argv=None):
    """仅接受明确技术夹具，不提供把本检查升级为研究质控通过的选项。"""
    parser=argparse.ArgumentParser()
    for name in ('tools-profile','receptor-pdb','ligand-sdf','output-dir','font-regular','font-bold'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('cid','inchi-key','chain'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--altloc')
    parser.add_argument('--fixture-only',action='store_true',required=True)
    args=parser.parse_args(argv)
    from contracts import require
    from modulea.config import Settings
    from modulea.core.bounded_evidence import file_record,verified_file
    from science_modules.a06.native_tools import NativeTools,NativeIO,VERSION
    from docking_top10_execute import _protein_pdb,_meeko_settings
    from docking_ligand import prepare_ligand
    from science_modules.a06.plan_score_pair import execute,validate
    from science_modules.a06.system_receptor_rescue import _top1_bytes
    from science_modules.a06.native_display import export
    settings=Settings(science_python=sys.executable,tools_profile=args.tools_profile,
        font_regular=args.font_regular,font_bold=args.font_bold)
    tools=NativeTools(settings);adapter=NativeIO(tools)
    root=args.output_dir.resolve()
    require(not root.exists(),'工具链检查输出已存在，请使用新目录，历史诊断保持')
    root.mkdir(parents=True)
    try:
        source=root/'raw/source.pdb';source.parent.mkdir()
        shutil.copy2(args.receptor_pdb,source)
        sdf=root/'raw/official_3d.sdf';shutil.copy2(args.ligand_sdf,sdf)
        observed=root/'observed.pdb'
        observed.write_text(_protein_pdb(source,{args.chain},args.altloc),encoding='ascii')
        repair=root/'repair';repair.mkdir()
        repaired=repair/'repaired.pdb';evidence=repair/'evidence.json'
        tools.repair_observed(observed,repaired,evidence,repair)
        prediction=tools.predict_twice(None,repaired,root/'prediction','工具夹具',root)
        receptor=tools.prepare_receptor(root,repaired.read_text('ascii'),prediction['box'],'fixture',root/'preparation')
        ligand=prepare_ligand(sdf.read_text('utf-8'),args.cid,args.inchi_key,_meeko_settings())
        ligand_path=root/'prepared_ligand.pdbqt';ligand_path.write_text(ligand.pop('pdbqt_text'),encoding='ascii',newline='\n')
        ligand_ref=file_record(root,ligand_path,'prepared_ligand');receptor_ref=file_record(root,receptor,'receptor')
        binary=tools.copy_vina(root,root/'software')
        config={'vina_parameters':{'scoring':'vina','exhaustiveness':8,'num_modes':9,
            'energy_range_kcal_mol':3,'seed':1},'cpu_per_pair':1,'timeout_seconds':1800}
        execution=adapter.bind(execute)(root,root/'score',binary,ligand_ref,receptor_ref,prediction['box'],config)
        actual=adapter.bind(validate)(root,execution,binary,ligand_ref,receptor_ref,prediction['box'],config)
        require(actual['state']=='completed','原生对接没有形成有效技术输出')
        pose=verified_file(root,actual['pose']).read_bytes()
        top=root/'top1.pdbqt';top.write_bytes(_top1_bytes(pose))
        packet={'schema_version':VERSION,'study_id':'fixture_only','run_id':'fixture_only','source_fixed':{
            'compounds':[{'compound_id':'TOOLTEST_C1','name':'工具链配体夹具','name_zh':'工具链配体夹具'}],
            'receptors':[{'target_id':'TOOLTEST_R1','symbol':'工具链受体夹具'}]},
            'compounds':[{'compound_id':'TOOLTEST_C1','name':'工具链配体夹具'}],
            'receptors':[{'target_id':'TOOLTEST_R1','symbol':'工具链受体夹具','state':'ready','quality':'探索'}],
            'pairs':[{'compound_id':'TOOLTEST_C1','target_id':'TOOLTEST_R1','state':'completed','score':actual['score'],
                      'quality':'探索','reason_zh':'仅技术工具输出，不是研究质控结论','source_kind':'native'}],
            'summary':{'scored_pairs':1,'input_key':'fixture-only','message_zh':'隔离技术夹具，不是研究结果'}}
        figures,attachments=export(root,packet,root/('display_'+'a'*32),font_path=str(args.font_regular))
        tools.verify_current()
        value={'schema_version':VERSION,'system':tools.profile['system'],'machine':tools.profile['machine'],
            'fixture_only':True,'scientific_qualification_passed':False,'human_review_written':False,
            'research_files_used':False,'parameters':config,'tools_sha256':tools.signature_sha256,
            'packages':tools.profile['packages'],'prediction':prediction,'repair':json.loads(evidence.read_text()),
            'ligand_preparation':ligand,'execution':execution,'top1':file_record(root,top,'top1'),
            'original_pose':actual['pose'],'score':actual['score'],'figures':figures,'attachments':attachments,
            'source_note_zh':'原始PDB和官方SDF全部保留。夹具蛋白提取不等于身份/伙伴/金属/口袋质控；'
                             '本程序不建立研究、不放行科研准备、不代签批准。'}
        (root/'toolchain-result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        (root/'tools-signature.json').write_text(json.dumps(tools.signature_value,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'state':'toolchain_completed','system':tools.profile['system'],
            'machine':tools.profile['machine'],'score':actual['score'],'result':str(root/'toolchain-result.json'),
            'scientific_qualification_passed':False},ensure_ascii=False),flush=True)
    finally:adapter.close()


if __name__=='__main__':main()
