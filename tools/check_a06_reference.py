"""公开样本参考质控审计；仅写独立审计目录，不建立研究或执行组合评分。"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def immutable_evidence_files(folder):
    """可变下载断点只用于恢复，不进入已完成结果的不可变证据清单。"""
    from storage import file_record
    folder = Path(folder)
    return [file_record(folder,p,"audit_evidence") for p in sorted(folder.rglob("*"))
            if p.is_file() and p != folder / "source_checkpoint.json"]


def main():
    """公开样本身份必须显式给出，原件可按指纹在同次审计断点续用。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tools-root", type=Path, required=True)
    parser.add_argument("--pdb-id", required=True)
    parser.add_argument("--entity-id", required=True)
    parser.add_argument("--uniprot", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chain", required=True)
    parser.add_argument("--reference-code", required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--verify-result", type=Path)
    parser.add_argument("--negative-checks", action="store_true")
    args = parser.parse_args()
    if args.verify_result and not args.resume:
        parser.error("--verify-result需要同时指定--resume")
    if args.negative_checks and not args.verify_result:
        parser.error("--negative-checks仅用于--verify-result离线复核")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    from docking_runtime import activate
    runtime = activate(args.tools_root)
    sys.path.append(str(Path(sys.executable).parents[1] / "Lib/site-packages"))
    from contracts import require
    from storage import new_id, now, read_json, write_json, verified_file, file_record
    from science_modules.a06.reference_sources import Fetcher
    from science_modules.a06.automatic_sources import conformer
    from science_modules.a06.reference_candidates import discover
    from science_modules.a06.plan_preparation_v2 import execution_config, _version
    from science_modules.analysis_protocol import compile_plan
    from science_modules.a06.plan_reference_evidence import prepare_selected, validate_ready, VERSION
    from docking_audit import receptor_identity
    from docking_receptor import inspect_structure
    for value, pattern in ((args.pdb_id,r"[0-9][A-Za-z0-9]{3}"), (args.entity_id,r"[0-9]+"),
            (args.uniprot,r"[A-Z0-9]{6,10}"), (args.chain,r"[A-Za-z0-9]"),
            (args.target_id,r"HGNC:[0-9]+"), (args.symbol,r"[A-Za-z0-9_-]{1,60}"),
            (args.reference_code,r"[A-Za-z0-9]{1,3}")):
        require(re.fullmatch(pattern,value), "审计样本身份格式不合法")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    folder = args.resume.resolve() if args.resume else root / new_id("audit")
    require(folder.is_relative_to(root) and folder != root, "审计断点必须属于明确输出根目录")
    folder.mkdir(exist_ok=bool(args.resume))
    sample = {k:getattr(args,k) for k in ("pdb_id","entity_id","uniprot","target_id","symbol","chain","reference_code")}
    config = execution_config(compile_plan({"mode":"standard"}))
    if args.resume:
        require(read_json(folder / "sample.json")["sample"] == sample, "审计样本已改变，不能续用断点")
    else:
        write_json(folder / "sample.json", {"sample":sample,"purpose":"isolated_public_reference_quality_check",
                   "created_at":now(),"runtime":runtime,"config":config})
    executable = _version(args.tools_root)
    snapshot_folder = folder / new_id("verification_code" if args.verify_result else "execution_code")
    for name in ("tools/check_a06_reference.py", "src/science_modules/a06/plan_reference_evidence.py",
                 "src/science_modules/a06/plan_quality_engine_v2.py", "src/science_modules/a06/reference_candidates.py",
                 "src/science_modules/a06/reference_prepare.py", "src/docking_top10_execute.py",
                 "src/docking_reference_ligand.py", "src/docking_receptor.py", "src/docking_redocking.py"):
        destination = snapshot_folder / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CODE / name,destination)
    binary = snapshot_folder / "software/vina_1.2.7.exe"
    binary.parent.mkdir()
    shutil.copyfile(executable,binary)
    # 可变断点不纳入不可变原件清单；旧审计索引只读兼容，不覆盖历史指纹。
    index_path = folder / "source_checkpoint.json"
    legacy_index = folder / "source_index.json"
    index = read_json(index_path) if index_path.exists() else read_json(legacy_index) if legacy_index.exists() else {}

    def check_hgnc(data):
        """标准基因编号、名称与唯一人类UniProt须由同一官方响应支持。"""
        docs = data.get("response",{}).get("docs",[])
        require(len(docs) == 1 and docs[0].get("hgnc_id") == args.target_id and
                docs[0].get("symbol") == args.symbol and docs[0].get("status") == "Approved" and
                docs[0].get("uniprot_ids") == [args.uniprot], "HGNC与公开结构目标身份不一致")

    if args.verify_result:
        require(args.resume is not None and args.verify_result.resolve().is_relative_to(folder), "复核结果必须属于当前审计断点")
        packet = read_json(args.verify_result)
        require(packet["schema_version"] == VERSION and packet["sample"] == sample and packet["config"] == config and
                packet["vina_sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest(), "审计样本、参数或工具指纹不一致")
        for ref in packet["files"]:
            verified_file(folder,ref)
        hgnc_slot = index.get("hgnc")
        if hgnc_slot is None and (folder / "hgnc_verification/index.json").exists():
            hgnc_slot = read_json(folder / "hgnc_verification/index.json")
        require(hgnc_slot is not None, "审计尚缺HGNC原件核对")
        check_hgnc(read_json(verified_file(folder,hgnc_slot["file"])))
        assessment = validate_ready(folder,packet["connection"],packet["result"],config)
        rejected = []
        if args.negative_checks:
            for name in ("changed_rmsd", "changed_seed", "changed_box_padding", "wrong_reference_key", "wrong_quality_label"):
                modified, altered_config = deepcopy(packet["result"]),deepcopy(config)
                if name == "changed_rmsd": modified["evidence"]["top1_rmsd"] += 1
                elif name == "changed_seed": altered_config["vina_parameters"]["seed"] += 1
                elif name == "changed_box_padding": altered_config["box_padding"] += 1
                elif name == "wrong_reference_key": modified["choice"]["reference_key"] = "0" * 64
                else: modified["quality"] = "探索"
                try:
                    validate_ready(folder,packet["connection"],modified,altered_config)
                except ValueError as error:
                    rejected.append({"name":name,"rejected":True,"reason_zh":str(error)})
                else:
                    raise ValueError("证据篡改未被拒绝：" + name)
        evidence = {"verified_at":now(),"result_file":file_record(folder,args.verify_result,"original_audit_result"),
                    "assessment":assessment,"runtime":runtime,
                    "hgnc_file":hgnc_slot["file"],
                    "negative_checks":rejected,
                    "verification_code":[file_record(folder,p,"verification_code") for p in snapshot_folder.rglob("*") if p.is_file()]}
        path = folder / (new_id("verification") + ".json")
        write_json(path,evidence)
        print(json.dumps({"verified":True,"evidence":str(path),"assessment":assessment},ensure_ascii=False),flush=True)
        return 0
    fetch = Fetcher(folder, folder / "raw")

    def get(slot, url, suffix="json"):
        """请求成功立即落盘；同次续核只能使用同URL和完整SHA原件。"""
        print("SOURCE " + slot, flush=True)
        if slot in index:
            require(index[slot]["url"] == url, "来源地址与审计断点不一致")
            path = verified_file(folder,index[slot]["file"])
            return (read_json(path) if suffix == "json" else None),index[slot]["file"]
        value, ref = fetch.get(url,suffix)
        index[slot] = {"url":url,"file":ref}
        write_json(index_path,index,replace=True)
        return value,ref

    result = None
    try:
        hgnc, hgnc_ref = get("hgnc","https://rest.genenames.org/fetch/hgnc_id/" + args.target_id.replace(":","%3A"))
        check_hgnc(hgnc)
        entity, entity_ref = get("entity",f"https://data.rcsb.org/rest/v1/core/polymer_entity/{args.pdb_id}/{args.entity_id}")
        _, cif_ref = get("structure",f"https://files.rcsb.org/download/{args.pdb_id}.cif","cif")
        official, official_ref = get("uniprot",f"https://rest.uniprot.org/uniprotkb/{args.uniprot}.json")
        identity = receptor_identity(entity,args.uniprot,args.chain)
        require(str(identity["pdb_id"]).upper() == args.pdb_id.upper() and
                str(identity["entity_id"]) == args.entity_id, "实体与指定公开结构不一致")
        text = verified_file(folder,cif_ref).read_text("utf-8")
        inspection = inspect_structure(text,args.pdb_id,[args.chain])
        alt, choice = conformer(inspection)
        spec = {"source_type":"experimental","pdb_id":args.pdb_id,"chains":[args.chain],
                "uniprot":args.uniprot,"pocket":"p2rank","altloc":alt}
        candidate = {"spec":spec,"cif":cif_ref,"identity":[identity],"conformer":choice,
                     "inspection":inspection,"official_sequence_file":official_ref}
        row = {"target_id":args.target_id,"symbol":args.symbol,"state":"connected","candidates":[candidate]}
        connection = {"id":folder.name,"compounds":[],"receptors":[row],
                      "files":[hgnc_ref,entity_ref,cif_ref,official_ref]}
        choices = discover(folder,connection)
        write_json(folder / (new_id("candidates") + ".json"),choices)
        matches = [r for r in choices if r["component_id"] == args.reference_code and r["selectable"]]
        require(len(matches) == 1, "指定公开参考配体不能唯一定位为可核查候选")
        selected = {k:matches[0][k] for k in ("target_id","candidate_key","reference_key")}
        attempt_folder = folder / new_id("reference")
        result = prepare_selected(folder,connection,selected,attempt_folder,args.tools_root,config,
                                  lambda message:print("PROGRESS "+message,flush=True))
        if result["state"] == "ready":
            validate_ready(folder,connection,result,config)
        packet = {"schema_version":VERSION,"purpose":"isolated_public_reference_quality_check",
                  "sample":sample,"connection":connection,"choice":selected,"result":result,"config":config,
                  "runtime":runtime,"vina_sha256":hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "files":immutable_evidence_files(folder)}
        path=folder/(new_id("result")+".json")
        write_json(path,packet)
        print(json.dumps({"folder":str(folder),"result_file":str(path),"state":result["state"],
                          "quality":result["quality"],"reason_zh":result["reason_zh"],
                          "rmsd":result.get("evidence",{}).get("top1_rmsd")},ensure_ascii=False),flush=True)
        return 0 if result["state"] == "ready" else 2
    except Exception as error:
        write_json(folder/(new_id("failure")+".json"),{"sample":sample,"error_zh":str(error),"created_at":now()})
        print(json.dumps({"folder":str(folder),"error_zh":str(error)},ensure_ascii=False),flush=True)
        raise


if __name__ == "__main__":
    sys.exit(main())
