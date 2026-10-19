"""自动连接当前批准对象的官方原件；仅下载和核查，不准备或计算研究配体评分。"""
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote
import json
import re
import urllib.error
import urllib.request
from contracts import require, fingerprint
from storage import file_record, new_id, now, read_json, verified_file, write_json
from .automatic_rules import POLICY


# 每次官方请求都保存原件及成功/失败事实，网络失败不能变成零命中。
class Fetcher:
    def __init__(self, root, folder):
        self.root, self.folder, self.records = root, folder, []

    def get(self, url, suffix="json"):
        key = new_id("source")
        path = self.folder / (key + "." + suffix)
        fact = {"url": url, "created_at": now(), "state": "failed"}
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json" if suffix == "json" else "*/*", "User-Agent": "ModuleA/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(20_000_001)
                require(len(raw) <= 20_000_000, "官方来源文件超过20MB，本次保留待处理")
                fact.update(status=response.status, state="success")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            record = file_record(self.root, path, "automatic_source")
            self.records.append(record)
            fact["file"] = record
            return (json.loads(raw) if suffix == "json" and raw else {}), record
        except Exception as error:
            fact["error_zh"] = str(error)
            raise
        finally:
            metadata = self.folder / (key + "_request.json")
            write_json(metadata, fact)
            self.records.append(file_record(self.root, metadata, "automatic_source_request"))


# 替代构象只在各残基有一致、唯一的最高占有率A/B时自动选取；否则留为异常。
def conformer(inspection):
    codes = {code for row in inspection["alternate_residues"] for code in row["locations"]}
    if not codes:
        return None, {"selection": None, "reason_zh": "原件未见替代构象"}
    require(codes <= {"A", "B"}, "存在A/B以外替代构象，不能自动选择")
    groups = defaultdict(lambda: defaultdict(list))
    for row in inspection["partial_occupancy_atoms"]:
        if row.get("altloc"):
            groups[(row["auth_chain"], row["auth_sequence"], row["atom"])][row["altloc"]].append(row["occupancy"])
    winners = set()
    for values in groups.values():
        scores = {key: sum(items) / len(items) for key, items in values.items()}
        top = max(scores.values())
        best = [key for key, value in scores.items() if value == top]
        require(len(best) == 1, "替代构象占有率并列，保留待核对")
        winners.add(best[0])
    require(len(winners) == 1, "不同原子最高占有率构象不一致，保留待核对")
    chosen = winners.pop()
    return chosen, {"selection": chosen, "reason_zh": "各已报告替代原子最高占有率一致且唯一", "occupancy_rows": inspection["partial_occupancy_atoms"]}


# 成分名称只能定位唯一官方CID；用原三维逐字节和完整立体身份复验，不生成新形态。
def compound_source(row, fetch):
    from docking_audit import ligand_identity
    name = row["name"]
    ids, _ = fetch.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/" + quote(name, safe="") + "/cids/JSON")
    cids = ids.get("IdentifierList", {}).get("CID", [])
    require(len(cids) == 1, "名称不能对应唯一PubChem CID，保留待核对")
    cid = cids[0]
    props, properties = fetch.get(f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/InChIKey,MolecularFormula/JSON")
    values = props["PropertyTable"]["Properties"]
    require(len(values) == 1 and values[0]["CID"] == cid, "官方化学身份响应不一致")
    _, sdf = fetch.get(f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d", "sdf")
    audit = ligand_identity(verified_file(fetch.root, sdf).read_text("utf-8"), cid, values[0]["InChIKey"])
    return {**row, "name_zh": name, "cid": cid, "identity_matched": True, "audit": audit, "sdf": sdf, "properties": properties, "state": "connected", "identity_basis_zh": "批准名称的唯一PubChem检索响应及官方属性与实际三维一致；未人工选择其他异构体"}


# 新结构仅按人类唯一UniProt实体、序列差异和分辨率顺序选择；无可靠参考一律探索。
def receptor_sources(row, fetch, progress):
    from docking_audit import receptor_identity
    from docking_receptor import inspect_structure
    tid = row["target_id"]
    hgnc, _ = fetch.get("https://rest.genenames.org/fetch/hgnc_id/" + quote(tid, safe=""))
    docs = hgnc.get("response", {}).get("docs", [])
    require(len(docs) == 1 and docs[0].get("hgnc_id") == tid and docs[0].get("status") == "Approved", "HGNC身份未唯一核实")
    ids = docs[0].get("uniprot_ids", [])
    require(len(ids) == 1, "HGNC没有唯一UniProt身份，保留待核对")
    uniprot = ids[0]
    query = {"query": {"type": "terminal", "service": "text", "parameters": {"attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession", "operator": "exact_match", "value": uniprot}}, "return_type": "polymer_entity", "request_options": {"paginate": {"start": 0, "rows": POLICY["search_limit"]}, "sort": [{"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}]}}
    found, _ = fetch.get("https://search.rcsb.org/rcsbsearch/v2/query?json=" + quote(json.dumps(query), safe=""))
    candidates, rejected = [], []
    for item in found.get("result_set", []):
        try:
            pdb, entity_id = item["identifier"].split("_")
            if any(value["spec"]["pdb_id"] == pdb for value in candidates):
                continue
            progress("核对结构：" + row["symbol"] + " / " + pdb)
            entity, _ = fetch.get(f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb}/{entity_id}")
            chains = sorted(entity.get("rcsb_polymer_entity_container_identifiers", {}).get("auth_asym_ids", []))
            require(chains and re.fullmatch(r"[A-Za-z0-9]", chains[0]), "作者链不能直接用于当前准备工具")
            chain = chains[0]
            identity = receptor_identity(entity, uniprot, chain)
            require(identity["pdb_id"] == pdb and str(identity["entity_id"]) == entity_id, "返回结构实体身份与检索编号不符")
            require(all(value == 0 for value in identity["sequence_differences"].values()), "存在序列差异或缺少差异记录，不能自动采用")
            _, cif = fetch.get(f"https://files.rcsb.org/download/{pdb}.cif", "cif")
            inspection = inspect_structure(verified_file(fetch.root, cif).read_text("utf-8"), pdb, [chain])
            altloc, choice = conformer(inspection)
            spec = {"source_type": "experimental", "pdb_id": pdb, "chains": [chain], "uniprot": uniprot, "pocket": "p2rank", "altloc": altloc}
            candidates.append({"spec": spec, "identity": [identity], "cif": cif, "conformer": choice, "inspection": inspection})
            if len(candidates) >= POLICY["structures_per_target"]:
                break
        except Exception as error:
            rejected.append({"candidate": item.get("identifier"), "reason_zh": str(error)})
    report = fetch.folder / ("rejected_" + tid.replace(":", "_") + ".json")
    write_json(report, {"target_id": tid, "search_total": found.get("total_count"), "rejected": rejected})
    fetch.records.append(file_record(fetch.root, report, "structure_rejections"))
    require(candidates, "检索范围内没有通过自动身份/构型核查的实验结构；候选拒绝依据见原始请求及集中异常")
    return {**row, "state": "connected", "identity_matched": True, "candidates": candidates, "rejected": rejected, "uniprot": uniprot, "search_total": found.get("total_count"), "search_limit": POLICY["search_limit"]}


# 连接时可沿用本研究同源、已明确的共晶方案；不把新检索到的小分子擅自当参考配体。
def connected_reference(workflow, manifest, context):
    try:
        source = workflow.current_source_review(manifest, context)
        plan, _ = workflow.latest_two_pass(manifest, context)
        if source and plan:
            return source, plan["plan"]
    except (ValueError, KeyError):
        pass
    return None, None


# 新建唯一尝试目录，重试不会覆盖上次原件；全部失败仍归档可查的异常清单。
def connect(workflow, sid, payload, progress):
    manifest, bound = workflow.automatic_binding(sid, payload["expected_binding"])
    identity = payload["connection_id"]
    existing = workflow.automatic_record(manifest, identity)
    if existing:
        return existing
    candidate_binding = workflow.candidate_binding(manifest)
    if workflow.candidate_record(manifest, candidate_binding)[0] is None:
        workflow.generate_candidates(sid, {**candidate_binding, "group_id": new_id("group"), "reason": "自动连接采用已批准A04的固定A/B规则，不改变科学名单"})
    from .plan_adapter import source_context
    manifest = workflow.load(sid)
    context = source_context(workflow, sid, manifest)
    require(all(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", r["compound_id"]) for r in context["compounds"]), "成分稳定编号不适合作为安全目录名，保留待处理")
    root = workflow.location(sid)
    folder = root / "raw/A06_automatic" / identity / new_id("attempt")
    fetch = Fetcher(root, folder)
    compounds, receptors, exceptions = [], [], []
    old_source, old_plan = connected_reference(workflow, manifest, context)
    for kind, rows, output, builder in (("compound", context["compounds"], compounds, compound_source), ("receptor", context["receptors"], receptors, receptor_sources)):
        for row in rows:
            progress("连接资料：" + (row.get("name") or row.get("symbol") or ""))
            try:
                # 已有同源共晶仅作为连接依据；质控和评分仍重新执行。
                selected = None
                if kind == "receptor" and old_source and old_plan:
                    planned = next((r for r in old_plan["receptors"] if r["target_id"] == row["target_id"]), None)
                    spec = (planned or {}).get("first")
                    source = next((r for r in old_source["receptors"] if r["target_id"] == row["target_id"] and spec and r["pdb_id"] == spec.get("pdb_id") and r.get("identity_matched")), None)
                    if source and spec.get("pocket") == "reference":
                        item = next(f["file"] for f in old_source["files"] if f["key"] == source["file_key"])
                        verified_file(root, item)
                        fetch.records.append(item)
                        selected = {**row, "state": "connected", "identity_matched": True, "candidates": [{"spec": spec, "identity": source["audit"]["identity"], "cif": item, "conformer": {"selection": spec.get("altloc"), "reason_zh": "沿用本研究同源明确方案；实际质控重新执行"}, "reference_audit": source}], "uniprot": spec["uniprot"]}
                output.append(selected or (builder(row, fetch) if kind == "compound" else builder(row, fetch, progress)))
            except Exception as error:
                message = str(error)
                state = "failed" if isinstance(error, (urllib.error.URLError, TimeoutError, OSError)) else "unavailable"
                output.append({**row, "state": state, "reason_zh": message, "candidates": []} if kind == "receptor" else {**row, "state": state, "reason_zh": message})
                exceptions.append({"kind": kind, "id": row.get("compound_id", row.get("target_id")), "name": row.get("name", row.get("symbol")), "state": state, "reason_zh": message})
    packet = {"schema_version": POLICY["version"], "id": identity, "study_id": sid, "binding": fingerprint(bound), "context": context, "created_at": now(), "policy": POLICY, "compounds": compounds, "receptors": receptors, "exceptions": exceptions, "files": fetch.records, "counts": {"compounds": len(compounds), "receptors": len(receptors), "pairs": len(compounds) * len(receptors)}, "summary": {"connected_compounds": sum(r["state"] == "connected" for r in compounds), "connected_receptors": sum(r["state"] == "connected" for r in receptors), "exceptions": len(exceptions)}, "objects": [{"id": r.get("compound_id", r.get("target_id")), "kind": kind, "name": r.get("name", r.get("symbol")), "state": r["state"], "reason_zh": r.get("reason_zh", ""), "structures": [c["spec"] for c in r.get("candidates", [])], "cid": r.get("cid"), "source": r.get("sdf")} for kind, rows in (("compound", compounds), ("receptor", receptors)) for r in rows]}
    return workflow.save_automatic_connection(sid, payload["expected_binding"], packet, fetch.records)
