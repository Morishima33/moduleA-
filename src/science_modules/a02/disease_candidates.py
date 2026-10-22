"""疾病定位候选预览：核对官方名称、同义名和编号，不改 A02 或代签。"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from contracts import ContractError, fingerprint, require
from storage import file_record, now, read_json, verified_file, write_json
from ttd_source import BASE as TTD_BASE, FILES as TTD_FILES, parse_snapshot
from pharmgkb_source import BASE_URL, DISEASE_ENDPOINT, GENE_ENDPOINT, _items

VERSION = "A02.disease_mapping.preview.1"
DATABASES = ("TTD", "PharmGKB")
PA_PATTERN = re.compile(r"PA\d+")
MESH_PATTERN = re.compile(r"D\d{6,9}")


def official_identity(summary):
    """只取已核验 A00 的 MeSH 主词、同义词和稳定编号。"""
    from mesh_identity import validate_mesh_identity
    return validate_mesh_identity(summary)


def _terms(identity):
    """保留官方词顺序；不推导宽泛疾病、简称或亚型。"""
    values = [identity.get("preferred_term", ""), *identity.get("entry_terms", [])]
    terms = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
    require(terms and MESH_PATTERN.fullmatch(str(identity.get("mesh_id", ""))), "缺少已核验的 MeSH 疾病身份")
    return terms


def _normal(value):
    """只统一空白与大小写，不删疾病限定词或标点。"""
    return " ".join(str(value or "").split()).casefold()


def _mesh_ids(value):
    """仅承认明确 MeSH 命名空间的 D 编号，不把 ICD 或系统数字当 MeSH。"""
    return set(re.findall(r"(?i)(?:mesh\s*[:=]\s*|id\.nlm\.nih\.gov/mesh/)(D\d{6,9})(?!\d)", str(value)))


def _label(row):
    """兼容官方其他名称字段，绝不把任意描述串解释成同义名。"""
    if isinstance(row, str):
        return row.strip()
    if isinstance(row, dict):
        return str(row.get("name") or row.get("term") or row.get("value") or "").strip()
    return ""


def ttd_candidates(snapshot, identity):
    """检查完整 TTD 原文；合并疾病及相关名称只形成待核候选。"""
    parse_snapshot(snapshot)  # 原适配器验证两个官方文件、版本和逐文件指纹。
    terms = {_normal(v) for v in _terms(identity)}
    target_fields = {}
    for line, text in enumerate(snapshot["files"]["targets"]["text"].splitlines(), 1):
        cells = text.split("\t")
        if len(cells) >= 3 and re.fullmatch(r"T\d+", cells[0]):
            target_fields.setdefault(cells[0], []).append({"line": line, "field": cells[1], "value": "\t".join(cells[2:])})
    grouped = {}
    for line, text in enumerate(snapshot["files"]["diseases"]["text"].splitlines(), 1):
        cells = text.split("\t")
        if len(cells) < 5 or cells[1] != "INDICATI":
            continue
        require(bool(re.fullmatch(r"T\d+", cells[0])), "TTD 疾病关系靶点编号无效")
        name, did = cells[3].strip(), cells[4].strip()
        ids = {v.upper() for v in _mesh_ids(did)}
        parts = {_normal(v) for v in re.split(r"[;|]|\s+/\s+|\s+and\s+", name, flags=re.I) if v.strip()}
        exact = _normal(name) in terms
        compound = len(parts) > 1 and bool(parts & terms)
        same_id = identity["mesh_id"] in ids
        related = any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", _normal(name)) for term in terms)
        if not (exact or compound or same_id or related):
            continue
        conflict = bool(ids and ids != {identity["mesh_id"]})
        kind = "identity_conflict" if conflict else "official_mesh_id" if same_id else "exact_name" if exact else "combined_disease" if compound else "related_name"
        reasons = {"identity_conflict": "名称与本病相近，但显式 MeSH 编号不一致；不得直接采用", "official_mesh_id": "原文显式 MeSH 编号与本研究一致；疾病范围仍须核验", "exact_name": "原文整个疾病名称与 MeSH 官方词精确一致；仍待范围核验", "combined_disease": "明确分隔的合并疾病项含本病；不能把整组自动纳入", "related_name": "名称含本病词，可能为亚型或其他范围；不能按子串直接纳入"}
        key = (name, did)
        row = grouped.setdefault(key, {"candidate_id": fingerprint(["TTD", name, did])[:24], "database": "TTD", "disease_id": did, "disease_name": name,
            "match_kind": kind, "reason_zh": reasons[kind], "scope": "pending", "selected": False, "direct_gene_eligible": False,
            "source_url": TTD_BASE + TTD_FILES["diseases"], "records_count": 0, "source_rows": [], "target_records": []})
        row["records_count"] += 1
        row["source_rows"].append("diseases:" + str(line))
        row["target_records"].append({"target_id": cells[0], "clinical_status": cells[2], "disease_line": line, "fields": target_fields.get(cells[0], [])})
    return [grouped[k] for k in sorted(grouped)]


def _row_mesh_ids(row):
    """ClinPGx 官方 terms 为等价实体；显式 MeSH 外链也可作为编号证据。"""
    ids = set()
    for item in row.get("terms") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("src") or "").casefold().replace(" ", "")
        value = str(item.get("termId") or "").strip()
        if source in ("mesh", "medicalsubjectheadings", "meshdescriptor"):
            value = re.sub(r"(?i)^mesh:", "", value)
            if MESH_PATTERN.fullmatch(value.upper()):
                ids.add(value.upper())
        ids.update(v.upper() for v in _mesh_ids(value))
    for key in ("crossReferences", "linkOuts"):
        for item in row.get(key) or []:
            if not isinstance(item, dict):
                continue
            ids.update(v.upper() for v in _mesh_ids(item.get("_url") or item.get("url") or ""))
            if str(item.get("resource") or "").strip().casefold() == "mesh":
                value = str(item.get("resourceId") or "").strip().upper()
                if MESH_PATTERN.fullmatch(value):
                    ids.add(value)
    return ids


def pharmgkb_candidates(requests, identity):
    """返回精确主名、官方其他名称及等价编号证据；多实体或冲突均不放行。"""
    terms = {_normal(v) for v in _terms(identity)}
    grouped = {}
    for request_index, request in enumerate(requests, 1):
        if request.get("term") == "direct genes" or "/report/" in str(request.get("url", "")):
            continue
        if request.get("status") == 404:
            continue
        require(request.get("status") == 200, "ClinPGx 查询未成功；不能解释为未定位实体")
        for index, row in enumerate(_items(request.get("response")), 1):
            require(isinstance(row, dict) and PA_PATTERN.fullmatch(str(row.get("id", ""))) and row.get("name"), "ClinPGx 疾病记录缺少有效稳定编号或名称")
            # 系统仅把官方疾病/表型对象作为候选，不接收 Gene、Chemical 等错对象。
            require(row.get("objCls", "Phenotype") in ("Phenotype", "Disease"), "ClinPGx 返回非疾病或表型对象")
            did = row["id"]
            names = [_label(v) for key in ("altNames", "synonyms") for v in (row.get(key) or [])]
            exact_name = _normal(row["name"]) in terms
            exact_alias = bool({_normal(v) for v in names if v} & terms)
            ids = _row_mesh_ids(row)
            same_id = identity["mesh_id"] in ids
            conflict = bool(ids and ids != {identity["mesh_id"]})
            kind = "identity_conflict" if conflict else "official_mesh_id" if same_id else "exact_name" if exact_name else "official_synonym" if exact_alias else "unresolved_candidate"
            proof = {"name": row["name"], "altNames": names, "mesh_ids": sorted(ids), "terms": row.get("terms") or []}
            if did in grouped:
                # 不同视图可补充名字和本体字段，但已出现的主名或编号矛盾必须留待核验。
                prior = grouped[did]
                if prior["disease_name"] != row["name"] or (prior["mesh_ids"] and ids and set(prior["mesh_ids"]) != ids):
                    prior["match_kind"] = "identity_conflict"
                    prior["direct_gene_eligible"] = False
                elif kind == "identity_conflict":
                    prior["match_kind"] = kind
                elif prior["match_kind"] == "unresolved_candidate" and kind != "unresolved_candidate":
                    prior["match_kind"] = kind
                prior["evidence"].append(proof)
                prior["source_rows"].append(f"requests:{request_index}:record:{index}")
                prior["mesh_ids"] = sorted(set(prior["mesh_ids"]) | ids)
                continue
            grouped[did] = {"candidate_id": fingerprint(["PharmGKB", did])[:24], "database": "PharmGKB", "disease_id": did, "disease_name": row["name"],
                "match_kind": kind, "mesh_ids": sorted(ids), "evidence": [proof], "scope": "pending", "selected": False, "direct_gene_eligible": False,
                "records_count": None, "source_rows": [f"requests:{request_index}:record:{index}"], "source_url": "https://www.clinpgx.org/disease/" + did}
    valid = [row for row in grouped.values() if row["match_kind"] not in ("identity_conflict", "unresolved_candidate")]
    reasons = {"identity_conflict": "同义名或主名相近，但官方 MeSH 编号或同一实体响应冲突；须核查", "official_mesh_id": "官方等价 MeSH 编号与本研究一致", "exact_name": "官方疾病主名与已核验 MeSH 词精确一致", "official_synonym": "官方其他名称与已核验 MeSH 词精确一致", "unresolved_candidate": "返回候选缺少同病精确名称或稳定编号证据；不自动采用"}
    for row in grouped.values():
        row["direct_gene_eligible"] = len(valid) == 1 and row is valid[0]
        row["reason_zh"] = reasons[row["match_kind"]] + ("；可在明确确认后查询本实体直接基因，当前 A02 未改变" if row["direct_gene_eligible"] else "；尚未核定唯一同病实体，不查询直接基因")
    return [grouped[k] for k in sorted(grouped)]


def _archived_sources(workflow, manifest, a02):
    """只读当前本研究绑定来源，不借用其他项目或共享历史名单。"""
    if not a02:
        return {}
    result = workflow.result(manifest, a02)
    records = [row for row in result.get("sources", []) if row.get("role") == "source_manifest"]
    require(len(records) == 1, "当前 A02 缺少唯一来源清单，无法核查疾病映射")
    return {item["database"]: item for item in read_json(verified_file(workflow.location(manifest["study_id"]), records[0])).get("datasets", [])}


def _response(url, folder, opener, *, json_response=True):
    """固定官方请求逐次留存原件及指纹；失败状态不转成空记录。"""
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.fragment, "疾病来源仅允许官方 HTTPS 请求")
    require(parsed.hostname in ("api.clinpgx.org", "ttd.idrblab.cn"), "疾病来源主机不在官方白名单")
    token = hashlib.sha256(url.encode()).hexdigest()
    path = Path(folder) / ("request_" + token + ".json")
    if path.exists():
        record = read_json(path)
        require(record["url"] == url, "已保存请求不属于本次来源")
        raw = verified_file(folder, record["file"]).read_bytes()
        require(record["status"] in (200, 404), "已归档请求失败，请另建候选预览重试")
    else:
        request = urllib.request.Request(url, headers={"Accept": "application/json" if json_response else "text/plain", "User-Agent": "ModuleA-Disease-Mapping/1.0"})
        try:
            with opener(request, timeout=25) as response:
                status = response.status
                raw = response.read(16 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, "官方疾病响应超过容量；未截断作为成功资料")
        original = Path(folder) / ("response_" + token + (".json" if json_response else ".txt"))
        original.write_bytes(raw)
        record = {"url": url, "status": status, "retrieved_at": now(), "file": file_record(folder, original, "disease_mapping_original")}
        write_json(path, record)
        require(status in (200, 404), "官方疾病接口查询失败：HTTP " + str(status) + "；保留响应，未更新 A02")
    payload = None if record["status"] == 404 else json.loads(raw) if json_response else raw.decode("utf-8")
    return record, payload


def _ttd_snapshot(folder, opener, query):
    """没有本研究 TTD 原文时才获取官方双文件，使用原解析器完整验证。"""
    files, requests = {}, []
    for role, filename in TTD_FILES.items():
        record, text = _response(TTD_BASE + filename, folder, opener, json_response=False)
        require(record["status"] == 200, "TTD 原始文件未取得")
        raw = text.encode("utf-8")
        files[role] = {"url": record["url"], "text": text, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "retrieved_at": record["retrieved_at"]}
        requests.append(record)
    snapshot = {"version": "TTD.snapshot.1", "query": query, "files": files}
    parse_snapshot(snapshot)
    return snapshot, requests


def preview(workflow, study_id, databases, folder, progress=None, opener=urllib.request.urlopen, sleeper=time.sleep):
    """独立预览候选与原始证据；A02 当前运行和复核记录完全不写。"""
    require(isinstance(databases, list) and databases and len(set(databases)) == len(databases) and set(databases) <= set(DATABASES), "请选择 TTD 或 PharmGKB 候选疾病核查")
    manifest = workflow.load(study_id)
    require(not manifest.get("trashed"), "回收站研究只读，不能获取候选")
    a00, a02 = manifest["current"].get("A00"), manifest["current"].get("A02", "")
    require(a00 and workflow.approved(manifest, a00), "请先复核通过 A00 疾病登记")
    identity = official_identity(workflow.result(manifest, a00)["summary"])
    home, folder = workflow.location(study_id).resolve(), Path(folder).resolve()
    require(folder.is_relative_to(home) and folder != home, "候选预览目录必须位于本研究独立子目录")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / "preview.json"
    if destination.exists():
        old = read_json(destination)
        require(old["study_id"] == study_id and old["bound_a00"] == a00 and old["bound_a02"] == a02 and old["requested_databases"] == databases, "旧候选预览不属于当前研究版本")
        for item in old.get("source_files", []):
            verified_file(home, item)
        return old
    sources = _archived_sources(workflow, manifest, a02)
    value = {"version": VERSION, "study_id": study_id, "bound_a00": a00, "bound_a02": a02, "mesh_id": identity["mesh_id"], "terms": _terms(identity),
        "requested_databases": databases, "created_at": now(), "current_a02_unchanged": True, "databases": [], "source_files": []}
    for database in databases:
        if progress:
            progress("核查 " + database + " 官方疾病候选，不更新当前 A02")
        detail = {"database": database, "status": "completed", "status_zh": "候选核查完成，尚未采用", "candidates": [], "requests": []}
        try:
            existing = sources.get(database)
            source_path = verified_file(home, existing["source_record"]) if existing and existing.get("source_record") else None
            if source_path:
                value["source_files"].append(existing["source_record"])
            if database == "TTD":
                if source_path and existing.get("format") == "ttd_snapshot":
                    snapshot = read_json(source_path)
                    detail["source_zh"] = "复用本研究当前 A02 绑定的完整 TTD 原文"
                else:
                    snapshot, detail["requests"] = _ttd_snapshot(folder, opener, value["terms"][0])
                    write_json(folder / "ttd_snapshot.json", snapshot)
                    detail["source_zh"] = "本次独立获取官方 TTD 双文件，未更新 A02"
                detail["candidates"] = ttd_candidates(snapshot, identity)
            else:
                # 要求 max 视图取得官方其他名称与等价本体字段；旧归档也参与比较。
                prior = read_json(source_path) if source_path and existing.get("format") == "pharmgkb_api" else {}
                requests = list(prior.get("requests", []))
                for index, term in enumerate(value["terms"]):
                    if index:
                        sleeper(0.5)
                    url = DISEASE_ENDPOINT.rstrip("/") + "?" + urllib.parse.urlencode({"name": term, "view": "max"})
                    record, payload = _response(url, folder, opener)
                    request = {"term": term, "url": url, "status": record["status"], "response": payload, "original": record["file"]}
                    requests.append(request)
                    detail["requests"].append(request)
                detail["candidates"] = pharmgkb_candidates(requests, identity)
                if not detail["candidates"]:
                    detail.update(status="entity_not_located", status_zh="未定位到本病实体；查询原响应已保留")
        except Exception as error:
            detail.update(status="query_failed", status_zh="疾病候选核查未完成；不是 0 条基因", error_zh=str(error))
        value["databases"].append(detail)
    latest = workflow.load(study_id)
    require(latest["current"].get("A00") == a00 and latest["current"].get("A02", "") == a02 and not latest.get("trashed"), "研究版本已变化，候选不得绑定新 A02")
    for path in sorted(folder.iterdir()):
        if path.is_file():
            value["source_files"].append(file_record(home, path, "disease_mapping_evidence"))
    write_json(destination, value)
    return value
