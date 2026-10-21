"""一次执行授权后的动态全矩阵：逐项质控、仅计算合格对象、原始构型位点可回溯。"""
from copy import deepcopy
from pathlib import Path
import csv
import hashlib
import json
import math
import shutil
import subprocess
from contracts import require
from storage import file_record, read_json, verified_file, write_json
from .reference_rules import VERSION, POLICY


def preparation_source(connection):
    """配体准备只读取本连接成分，受体由补救编排独立处理。"""
    from .automatic_engine import preparation_source as original
    return original(dict(connection, receptors=[]))


# 完整二维表和图使用同一原始评分；NA白底，不用零填补。
def draw_matrix(packet, folder, names=None):
    """第三版直接使用统一展示导出，评分与旧协议文件均不改写。"""
    from .automatic_exports import build_view, export
    return export(build_view(packet, names), folder)


def score_pair(root, folder, binary, compound, receptor):
    """全部区域按同一预定集合执行，选有效区域Top-1最低值，保留部分失败。"""
    from .trial_compute import score_region
    from .trial_rules import choose_score
    from docking_redocking import _poses, _inside_box
    facts=[]
    for region in receptor['regions']:
        fact=score_region(root,folder,binary,compound,{'target_id':receptor['target_id'],'receptor':receptor['receptor']},region)
        if fact['state']=='completed':
            pose=_poses(verified_file(root,fact['pose']).read_text('ascii'))[0]
            if not _inside_box(pose,{'center_angstrom':region['center'],'size_angstrom':region['size']})['passed']:
                fact=dict(fact,state='failed',original_score=fact['score'],score=None,reason_zh='实际Top-1姿势越出预定搜索盒')
        facts.append(fact)
    best=choose_score(facts,receptor['mode'])
    return {'state':'completed' if best else 'failed','score':best['score'] if best else None,
        'reason_zh':'' if best else '所有预定区域执行失败，见各区域日志','mode':receptor['mode'],
        'regions':facts,'region_id':best['region_id'] if best else None,'execution':best,
        'partial_regions':bool(best and any(r['state']!='completed' for r in facts))}


# 参数、软件和执行源码固定到本次尝试，失败原件与输出同样保留。
def run(workflow, sid, payload, tools, code, runtime, progress, repair_packages):
    from .quality_engine import prepare_compounds, target_folder
    from .reference_prepare import prepare
    from .trial_compute import score_region
    executable = tools / "environments/vina_1.2.7/vina_1.2.7_win.exe"
    check = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=20)
    require(check.returncode == 0 and check.stdout.strip() == "AutoDock Vina v1.2.7", "固定Vina 1.2.7工具未就绪")
    batch, run_info, completed = workflow.begin_automatic(sid, payload)
    if completed:
        return workflow.result(workflow.load(sid), batch["run_id"])
    root = workflow.location(sid)
    folder = root / "runs/A06" / run_info["run_id"] / "automatic"
    folder.mkdir(parents=True, exist_ok=False)
    connection = read_json(verified_file(root, run_info["inputs"]["automatic_connection"]))
    from .reference_candidates import validate_choices
    validate_choices(root, connection, payload.get("reference_choices", []))
    connection = dict(connection, reference_choices=payload.get("reference_choices", []))
    source = preparation_source(connection)
    try:
        binary = folder / "software/vina_1.2.7.exe"
        binary.parent.mkdir(parents=True)
        shutil.copyfile(executable, binary)
        write_json(folder / "software/runtime.json", {"runtime": runtime, "policy": POLICY, "source_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest()})
        for name in ("science_modules/a06/compound_recovery.py", "modulea/core/automatic_start.py", "tools/run_a06_automatic.py", "science_modules/a06/reference_engine.py", "science_modules/a06/reference_prepare.py", "science_modules/a06/reference_sources.py", "science_modules/a06/reference_candidates.py", "science_modules/a06/reference_rules.py", "science_modules/a06/automatic_coverage_engine.py", "science_modules/a06/automatic_coverage_prepare.py", "science_modules/a06/automatic_coverage_sources.py", "science_modules/a06/automatic_coverage_rules.py", "tools/repair_a06_trial.py", "science_modules/a06/trial_prepare.py", "science_modules/a06/automatic_engine.py", "science_modules/a06/automatic_rules.py", "science_modules/a06/automatic_sources.py", "science_modules/a06/quality_engine.py", "science_modules/a06/trial_compute.py", "science_modules/a06/trial_rules.py", "docking_ligand.py", "docking_receptor.py", "docking_audit.py", "docking_reference_ligand.py", "docking_redocking.py", "docking_top10_execute.py", "docking_p2rank.py"):
            destination = folder / "code" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(code / name if name.startswith("tools/") else code / "src" / name, destination)
        ligand_plan = {"compounds": [{"compound_id": r["compound_id"], "status": "use"} for r in source["compounds"]]}
        prepared = prepare_compounds(root, source, ligand_plan, folder / "quality", progress)
        compounds = []
        for original in connection["compounds"]:
            actual = next((r for r in prepared if r["compound_id"] == original["compound_id"]), None)
            compounds.append({**original, **(actual or {}), "state": actual["state"] if actual else original["state"]})
        receptors = [prepare(workflow,sid,connection,original,folder/"quality/receptors"/target_folder(original["target_id"]),tools,repair_packages,code,payload["request_id"],progress) for original in connection["receptors"]]
        pairs = []
        total = len(compounds) * len(receptors)
        for compound in compounds:
            for receptor in receptors:
                row = {"compound_id": compound["compound_id"], "target_id": receptor["target_id"], "state": "NA", "score": None, "quality": receptor["quality"], "reason_zh": ""}
                if compound["state"] != "ready" or receptor["state"] != "ready":
                    row["state"] = "failed" if compound["state"] == "failed" or receptor.get("state") == "failed" else "NA"
                    row["reason_zh"] = "；".join(r.get("reason_zh", "") for r in (compound, receptor) if r["state"] != "ready") or "对象未通过本轮准备或质控"
                else:
                    progress(f"自动对接 {len(pairs)+1}/{total}：{compound['compound_id']} / {receptor['symbol']}")
                    row.update(score_pair(root,folder,binary,compound,receptor))
                pairs.append(row)
                write_json(folder / "progress" / f"pair_{len(pairs):06d}.json", {"completed_pairs": len(pairs), "total": total})
        strict = [r["target_id"] for r in receptors if r["state"] == "ready" and r["quality"] == "严格"]
        primary = strict[:5] if len(strict) >= 5 else []
        summary = {"science_version": VERSION, "成分数": len(compounds), "受体数": len(receptors), "计划组合数": total, "成功组合数": sum(p["state"] == "completed" for p in pairs), "失败组合数": sum(p["state"] == "failed" for p in pairs), "NA组合数": sum(p["state"] == "NA" for p in pairs), "严格受体数": len(strict), "探索受体数": sum(r["state"] == "ready" and r["quality"] == "探索" for r in receptors), "主要受体数": len(primary), "handoff_blocked": not any(p["state"] == "completed" for p in pairs), "interpretation_scope": "strict_and_exploratory_separate", "automatic_scientific_approval": False}
        packet = {"schema_version": VERSION, "study_id": sid, "id": payload["request_id"], "run_id": run_info["run_id"], "connection": run_info["inputs"]["automatic_connection"], "authorization": run_info["inputs"]["automatic_authorization"], "policy": POLICY, "runtime": runtime, "compounds": compounds, "receptors": receptors, "pairs": pairs, "summary": summary, "primary_targets": primary, "executable": file_record(root, binary, "automatic_vina")}
        from modulea.core.automatic_experience import automatic_names
        display_names = automatic_names(workflow, workflow.load(sid), packet, run_info["parent_runs"]["A03"])
        draw_matrix(packet, folder / "display", display_names)
        packet_path = folder / "packet.json"
        write_json(packet_path, packet)
        record = file_record(root, packet_path, "automatic_packet")
        files = list({r["path"]: r for r in connection["files"] + list(run_info["inputs"].values()) + [file_record(root, path, "automatic_evidence") for path in folder.rglob("*") if path.is_file()]}.values())
        tables = {"automatic_packet": [record], "pairs": [{k: r[k] for k in ("compound_id", "target_id", "state", "score", "quality", "reason_zh")} for r in pairs], "receptor_setup": [{"基因": r["symbol"], "HGNC": r["target_id"], "质控": r["quality"], "状态": r["state"], "PDB": r.get("selected_candidate", {}).get("spec", {}).get("pdb_id", r.get("selected_candidate", {}).get("spec", {}).get("model_id", "")), "原因": r["reason_zh"]} for r in receptors]}
        return workflow.finish_automatic(sid, payload, run_info["run_id"], record, summary, tables, files)
    except Exception as error:
        workflow.fail_automatic(sid, payload["request_id"], str(error))
        raise


def validator(root, previous):
    """独立第三版发布校验；核定原件及执行授权稳定键，不升级旧协议。"""
    def check(run_info, summary, tables, anomalies, outcome):
        if run_info.get('config',{}).get('schema_version') != VERSION:
            return previous(run_info,summary,tables,anomalies,outcome)
        from .automatic_coverage_prepare import check_exploration
        from .automatic_rules import assess
        from .trial_rules import choose_score, VINA, fingerprint
        from docking_redocking import _poses, _inside_box, symmetry_rmsd
        from docking_top10_execute import _vina_arguments
        home=Path(root)/'studies'/run_info['study_id']
        authorization=read_json(verified_file(home,run_info['inputs']['automatic_authorization']))
        connection=read_json(verified_file(home,run_info['inputs']['automatic_connection']))
        packet=read_json(verified_file(home,tables['automatic_packet'][0]))
        from .reference_candidates import apply_choices, validate_choices
        choices=authorization['request'].get('reference_choices', [])
        validate_choices(home, connection, choices)
        confirmed_connection=apply_choices(home, connection, choices)
        require(packet['policy']==connection['policy']==authorization['policy']==POLICY and run_info['config']=={'schema_version':VERSION,'policy':POLICY},'补救策略或参数不一致')
        require(packet['study_id']==connection['study_id']==authorization['study_id']==run_info['study_id'],'补救资料跨研究')
        require(packet['id']==authorization['id'] and packet['run_id']==run_info['run_id'],'补救批次身份不一致')
        require(authorization['request']['confirmed'] is True and authorization['request']['policy_version']==VERSION and authorization['approval'] is None,'没有第三版明确执行授权，不能继承旧授权')
        require(authorization['binding']['runs']==run_info['parent_runs'] and authorization['binding']['reviews']==run_info['parent_review_ids'],'补救输入与批准版本不一致')
        require(packet['authorization']==run_info['inputs']['automatic_authorization'] and packet['connection']==authorization['connection']==run_info['inputs']['automatic_connection'],'补救引用原件与执行授权不一致')
        require([r['compound_id'] for r in packet['compounds']]==[r['compound_id'] for r in connection['context']['compounds']] and [r['target_id'] for r in packet['receptors']]==[r['target_id'] for r in connection['context']['receptors']],'补救名单、顺序或范围被改变')
        compounds={r['compound_id']:r for r in packet['compounds']}
        receptors={r['target_id']:r for r in packet['receptors']}
        expected={(c,r) for c in compounds for r in receptors}
        actual=[(p['compound_id'],p['target_id']) for p in packet['pairs']]
        require(len(actual)==len(set(actual)) and set(actual)==expected,'补救矩阵漏项或重复')
        for receptor in packet['receptors']:
            if receptor['state']!='ready':
                continue
            candidate=receptor['selected_candidate']
            original=next(r for r in connection['receptors'] if r['target_id']==receptor['target_id'])
            require(candidate['spec']['uniprot']==original.get('uniprot',original['candidates'][0]['spec']['uniprot']),'补救更换目标UniProt')
            verified_file(home,receptor['receptor'])
            if receptor['quality']=='严格':
                confirmed=next(r for r in confirmed_connection['receptors'] if r['target_id']==receptor['target_id'])
                matched=next((r for r in confirmed['candidates'] if r['spec']==candidate['spec'] and r['cif']==candidate['cif'] and r.get('reference_choice')==candidate.get('reference_choice')), None)
                require(matched is not None and matched.get('reference_choice'), '严格对象不是本次明确核定的共晶方案')
                require(candidate.get('reference_audit')=={'reference_count_matches':True,'reference_covalent_count':0},'共晶实际原子完整性未通过')
                ev=receptor['evidence']
                from .reference_prepare import complete_reference
                ccd_records=[r for r in ev['files'] if r['path'].endswith('/ccd_'+candidate['spec']['reference_code']+'.cif')]
                require(len(ccd_records)==1,'缺少实际采用的唯一CCD拓扑原件')
                require({k:v for k,v in candidate.items() if k!='reference_sequence_audit'}==complete_reference(home,matched,verified_file(home,ccd_records[0]).read_text('utf-8')),'共晶候选、原子完整性或来源依据与核定不一致')
                from .automatic_coverage_sources import sequence_scope
                sequence_audit=candidate['reference_sequence_audit']
                official=read_json(verified_file(home,sequence_audit['official_sequence_file']))
                require(sequence_scope(verified_file(home,candidate['cif']).read_text('utf-8'),candidate['spec'],official)==sequence_audit['sequence_scope'],'共晶实际序列映射与官方原件不符')
                result=assess(candidate['spec'],ev,authorization['id'],receptor)
                require(result['state']=='ready' and result['quality']=='严格','补救探索不能升格严格')
                pose=_poses(verified_file(home,ev['redocking_output']).read_text('ascii'))[0]
                rmsd=symmetry_rmsd(verified_file(home,ev['reference_sdf']).read_bytes(),verified_file(home,ev['reference_pdbqt']).read_text('ascii'),pose)['rmsd_angstrom']
                require(abs(rmsd-ev['top1_rmsd'])<1e-9 and rmsd<=2,'严格RMSD与实际原件不一致')
                from .quality_engine import environment_audit
                env=environment_audit(verified_file(home,candidate['cif']).read_text('utf-8'),candidate['spec'],ev['box'])
                require(env==ev['environment_audit'] and env['pocket_complete'] and env['environment_resolved'],'严格口袋环境与原件不一致')
                require(receptor['regions']==[dict(ev['box'],region_id='fixed_site')] and receptor['mode']=='fixed_site','严格位点被更改')
            else:
                require(receptor['quality']=='探索','补救结果没有明确探索分类')
                usable,rejected=check_exploration(home,candidate,receptor)
                require(fingerprint(usable)==fingerprint(receptor['regions']) and fingerprint(rejected)==fingerprint(receptor['rejected_regions']),'探索采用区域或置信度被改写')
        binary=verified_file(home,packet['executable'])
        for pair in packet['pairs']:
            compound,receptor=compounds[pair['compound_id']],receptors[pair['target_id']]
            if compound['state']=='ready' and receptor['state']=='ready':
                ligand=next(r for r in compound['files'] if r['role']=='prepared_ligand')
                ligand_path=verified_file(home,ligand)
                require([f['region_id'] for f in pair['regions']]==[r['region_id'] for r in receptor['regions']],'不同成分使用不同区域集合')
                for fact,region in zip(pair['regions'],receptor['regions']):
                    require(fact['state'] in ('completed','NA','failed'),'区域执行状态不合法')
                    config=fact['config']
                    require(config['compound']==ligand and config['receptor']==receptor['receptor'] and config['region']==region and config['vina']==VINA and config['executable_sha256']==packet['executable']['sha256'] and fact['input_key']==fingerprint(config),'区域实际输入、工具或参数不一致')
                    output=home/'runs/A06'/run_info['run_id']/'automatic/scores'/pair['compound_id']/pair['target_id'].replace(':','_')/region['region_id']/'poses.pdbqt'
                    require(fact['command']==_vina_arguments(binary,verified_file(home,receptor['receptor']),ligand_path,region,output)+['--cpu','2'],'实际执行命令被修改')
                    if fact['state']=='completed':
                        pose=_poses(verified_file(home,fact['pose']).read_text('ascii'))[0]
                        atoms={int(l[6:11]):l[77:].strip().split()[0] for l in ligand_path.read_text('ascii').splitlines() if l.startswith(('ATOM  ','HETATM'))}
                        require(pose['score_kcal_mol']==fact['score'] and fact['returncode']==0 and atoms=={k:a['atom_type'] for k,a in pose['atoms'].items()},'区域Top-1分数或原子身份与实际输出不一致')
                        require(_inside_box(pose,{'center_angstrom':region['center'],'size_angstrom':region['size']})['passed'],'区域Top-1越出搜索盒')
                selected=choose_score(pair['regions'],receptor['mode'])
                require(pair.get('execution')==selected and pair['score']==(selected['score'] if selected else None) and pair['state']==('completed' if selected else 'failed'),'最终分数不是预定区域Top-1最低值')
                require(pair['partial_regions']==bool(selected and any(r['state']!='completed' for r in pair['regions'])),'部分失败标记不一致')
            else:
                require(pair['state'] in ('NA','failed') and pair['score'] is None and pair['reason_zh'],'不可计算对象必须保留原因，不能填分')
        require(summary==packet['summary'] and summary['science_version']==VERSION and summary['automatic_scientific_approval'] is False,'补救摘要或审批标记不一致')
        for label,state in (('成功组合数','completed'),('失败组合数','failed'),('NA组合数','NA')):
            require(summary[label]==sum(r['state']==state for r in packet['pairs']),'补救组合数量不一致')
        strict=[r['target_id'] for r in packet['receptors'] if r['state']=='ready' and r['quality']=='严格']
        primary=strict[:5] if len(strict)>=5 else []
        require(packet['primary_targets']==primary and summary['严格受体数']==len(strict) and summary['主要受体数']==len(primary),'主要受体被补救探索凑数')
        require(summary['探索受体数']==sum(r['state']=='ready' and r['quality']=='探索' for r in packet['receptors']),'探索数量不一致')
        require(summary['计划组合数']==len(expected) and summary['handoff_blocked']==(summary['成功组合数']==0),'补救交接条件不一致')
        require(tables['pairs']==[{k:r[k] for k in ('compound_id','target_id','state','score','quality','reason_zh')} for r in packet['pairs']] and outcome=='success','补救网页表与原始结果不一致')
    return check


