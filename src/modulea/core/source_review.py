"""A06获准来源原件与只读核查独立留存：不准备、不审批、不运行对接。"""
from copy import deepcopy
from uuid import uuid4
from urllib.parse import urlsplit
import base64
import re
from contracts import require, safe_id, fingerprint
from storage import write_lock, write_json, read_json, verified_file, file_record, now
from science_modules.a06.plan_adapter import source_context

SCHEMA = "A06.source_review.1"


def allowed_url(value):
    """仅接受PubChem三维/属性、RCSB坐标与组分字典的官方来源，不接受用户凭据。"""
    p = urlsplit(value)
    require(p.scheme == "https" and not p.username and not p.password and not p.fragment,
            "来源原件必须使用无凭据的官方HTTPS链接")
    good = (
        p.hostname == "pubchem.ncbi.nlm.nih.gov" and p.path.startswith("/rest/pug/compound/cid/")
        or p.hostname == "files.rcsb.org" and re.fullmatch(r"/download/[0-9][A-Za-z0-9]{3}\.cif", p.path)
        or p.hostname == "data.rcsb.org" and re.fullmatch(r"/rest/v1/core/chemcomp/[A-Z0-9]{1,3}", p.path)
    )
    require(bool(good), "不支持该来源原件链接")


class SourceReviewMixin:
    # 新原件只追加到独立版本目录，不覆盖历史、科研运行或批准记录。
    def save_source_review(self, sid, payload):
        with write_lock(self.root):
            manifest = self.load(sid)
            context = source_context(self, sid, manifest)
            fields = {"schema_version", "study_id", "source_key", "review_id", "expected_review_id",
                      "authorization_zh", "note_zh", "compounds", "receptors", "choices", "files",
                      "execution_allowed", "approval"}
            require(isinstance(payload, dict) and set(payload) == fields, "来源核查包字段不完整")
            require(payload["schema_version"] == SCHEMA and payload["study_id"] == sid
                    and payload["source_key"] == context["source_key"], "来源资料跨研究或上游已过期")
            require(payload["execution_allowed"] is False and payload["approval"] is None,
                    "资料核查不能准备、计算或代签")
            require(payload["authorization_zh"] == "用户允许获取并核查资料，暂不计算"
                    and isinstance(payload["note_zh"], str) and payload["note_zh"].strip(),
                    "须明确本次资料获取范围与限制")
            safe_id(payload["review_id"], "source_review")
            request_key = fingerprint(payload)
            for record in manifest.get("source_review_records", []):
                old = read_json(verified_file(self.location(sid), record))
                if old["review_id"] == payload["review_id"]:
                    require(old["request_key"] == request_key, "来源核查重试内容不一致")
                    for file in old["files"]:
                        verified_file(self.location(sid), file["file"])
                    return old
            latest = self.current_source_review(manifest, context)
            require(payload["expected_review_id"] == (latest["review_id"] if latest else None),
                    "来源核查资料已更新，请刷新后重试")
            for kind, identity in (("compounds", "compound_id"), ("receptors", "target_id")):
                rows = payload[kind]
                require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
                        and [r.get(identity) for r in rows] == [r[identity] for r in context[kind]],
                        "来源核查须覆盖完整当前" + kind + "名单")
            known = {r["compound_id"]: r for r in self.current_docking_review(manifest)["compounds"]}
            for row in payload["compounds"]:
                origin = known[row["compound_id"]]
                require(origin["identity_prechecked"] and str(row["cid"]) == str(origin["cid"]),
                        "化学身份冲突或CID改变，不能纳入")
                require(row["audit"].get("docking_ready") is False, "身份核查不能冒充准备通过")
                if row["identity_matched"]:
                    key = origin["official_evidence"]["properties"]["InChIKey"]
                    require(row["audit"]["inchi_key"] == key
                            and row["audit"]["coordinate_inchi_key"] == key, "来源三维立体身份不符")
            metadata = self.current_receptor_review(manifest, context)
            targets = {r["target_id"]: r for r in metadata["receptors"]}
            for row in payload["receptors"]:
                origin = targets[row["target_id"]]
                require(row["symbol"] == origin["symbol"]
                        and row["candidate_grade"] == origin["candidate_grade"], "受体身份或梯队改变")
                require(row["pdb_id"] in {c["pdb_id"] for c in origin["candidates"]},
                        "来源结构不属于已整理候选")
                audit = row.get("audit", {})
                require(not audit.get("receptor_prepared") and not audit.get("docking_ready")
                        and not audit.get("coordinate_modified"), "原件核查不能写成准备或质控结果")
            # 核查原件字节、来源和文件名，再写入；不接受目录链接或任意路径。
            decoded = []
            require(isinstance(payload["files"], list) and payload["files"], "来源原件缺失")
            keys = set()
            for item in payload["files"]:
                require(set(item) == {"key", "name", "url", "sha256", "content_base64"}
                        and re.fullmatch(r"f[0-9]{3,}", item["key"]) and item["key"] not in keys,
                        "来源文件键重复或字段非法")
                require(re.fullmatch(r"[A-Za-z0-9_-]+\.(sdf|cif|json)", item["name"]),
                        "来源文件名不安全")
                keys.add(item["key"])
                allowed_url(item["url"])
                raw = base64.b64decode(item["content_base64"], validate=True)
                require(0 < len(raw) <= 15000000, "来源原件为空或过大")
                import hashlib
                require(hashlib.sha256(raw).hexdigest() == item["sha256"], "来源原件校验值不符")
                decoded.append((item, raw))
            by_key = {item["key"]: item for item in payload["files"]}
            for row in payload["compounds"] + payload["receptors"]:
                require(row["file_key"] in keys, "核查对象缺少对应来源原件")
                item = by_key[row["file_key"]]
                if "compound_id" in row:
                    require(item["url"] == "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                            + str(row["cid"]) + "/SDF?record_type=3d", "三维原件来源CID不符")
                else:
                    require(item["url"] == "https://files.rcsb.org/download/" + row["pdb_id"] + ".cif",
                            "坐标原件来源PDB不符")
            for choice in payload["choices"]:
                require(choice["target_id"] in targets and choice["kind"] in ("altloc", "route")
                        and choice["round"] in ("first", "second"), "待核对选择超出当前受体范围")
            folder = self.location(sid) / "raw/A06_source_reviews" / payload["review_id"]
            require(folder.resolve().is_relative_to(self.location(sid).resolve()), "来源目录超出当前研究")
            folder.mkdir(parents=True, exist_ok=True)
            files = []
            for item, raw in decoded:
                path = folder / item["name"]
                if path.exists():
                    require(path.read_bytes() == raw, "中断重试的来源原件内容不一致")
                else:
                    with path.open("xb") as stream:
                        stream.write(raw)
                files.append({k: item[k] for k in ("key", "name", "url")}
                             | {"file": file_record(self.location(sid), path, "source_original")})
            data = {k: deepcopy(v) for k, v in payload.items() if k != "files"}
            data.update(files=files, request_key=request_key, created_at=now())
            path = self.location(sid) / "decisions/A06_source_review" / (data["review_id"] + ".json")
            if path.exists():
                previous=read_json(path)
                require(previous["request_key"] == request_key, "中断重试的核查记录内容不一致")
                data=previous
            else:
                write_json(path, data)
            manifest.setdefault("source_review_records", []).append(
                file_record(self.location(sid), path, "source_review")
            )
            self.save(manifest)
            return data

    # 只展示同上游最新版本，读取时再次核验原件；上游改变不回退旧资料。
    def current_source_review(self, manifest, context):
        records = manifest.get("source_review_records", [])
        if not records:
            return None
        data = read_json(verified_file(self.location(manifest["study_id"]), records[-1]))
        require(data["schema_version"] == SCHEMA and data["study_id"] == manifest["study_id"]
                and data["execution_allowed"] is False and data["approval"] is None,
                "来源核查版本或身份不符")
        if data["source_key"] != context["source_key"]:
            return None
        for item in data["files"]:
            verified_file(self.location(manifest["study_id"]), item["file"])
        return data

    # 资料更新后旧窗口不能确认另一批原件，旧无原件流程仍保持兼容。
    def guard_source_review(self, manifest, context, payload):
        current = self.current_source_review(manifest, context)
        require(current is None or payload.get("expected_source_review_id") == current["review_id"],
                "来源原件核查版本已更新，请刷新后核对")
        return current


def merged_metadata(metadata, source):
    """展示新取得来源三维和实际坐标核查；保留原摘要，不把原件数解释为质控通过。"""
    if not metadata or not source:
        return metadata
    result = deepcopy(metadata)
    files = {f["key"]: f["file"] for f in source["files"]}
    compounds = {r["compound_id"]: r for r in source["compounds"]}
    for row in result["compounds"]:
        raw = compounds[row["compound_id"]]
        if raw["identity_matched"]:
            row["source_3d_evidence"] = [dict(files[raw["file_key"]], is_3d=True)]
            row["source_3d_state_zh"] = "来源三维已取得且身份预核对；尚未准备或质控"
    receptors = {r["target_id"]: r for r in source["receptors"]}
    for row in result["receptors"]:
        source_row = receptors[row["target_id"]]
        row["source_audit"] = deepcopy(source_row)
        rejected = {r["pdb_id"]: r["reason_zh"] for r in source_row.get("rejected_sources", [])}
        for candidate in row["candidates"]:
            if candidate.get("pdb_id") in rejected:
                candidate["source_rejected"] = True
                candidate["source_reason_zh"] = rejected[candidate["pdb_id"]]
        proposal = row.get("plan_proposal")
        if proposal and source_row.get("planned_round"):
            proposal[source_row["planned_round"] + "_pdb_id"] = source_row["pdb_id"]
            proposal["reason_zh"] = source_row["reason_zh"]
            proposal["route_zh"] = "原件核查后的候选草案（未确认）"
            spec = source_row.get("spec", {})
            proposal["reference_zh"] = (
                str(spec["reference_code"]) + " " + str(spec["reference_chain"])
                + ":" + str(spec["reference_sequence"])
                if spec.get("pocket") == "reference" else "无常规共晶参考；预测口袋仍待证据"
            )
            row["limitations_zh"] = (
                "本轮原件已独立核查；具体缺失、构象、位点及环境处理仍待确认或质控。"
                "不修改原始来源，不用历史结果代替本次重对接。"
            )
    return result


def source_row_checks(source, plan, checks):
    """已有原件核查后，不允许改用未核查或冲突结构；也不把未知构象当成无构象。"""
    if not source:
        return checks
    audits = {r["target_id"]: r for r in source["receptors"]}
    out = []
    for row, facts in zip(plan["receptors"], checks):
        result = deepcopy(facts)
        try:
            if row["unavailable"]:
                out.append(result)
                continue
            original = audits[row["target_id"]]
            rejected = {r["pdb_id"] for r in original.get("rejected_sources", [])}
            for key in ("first", "second"):
                spec = row.get(key)
                if not spec:
                    continue
                require(spec.get("pdb_id") not in rejected, "该来源存在冲突或不适用，不能采用")
                require(spec.get("source_type") == "experimental"
                        and spec.get("pdb_id") == original["pdb_id"], "新来源尚未完成原件核查")
                require(original["identity_matched"] and spec["chains"] == original["chains"]
                        and spec["uniprot"] == original["spec"]["uniprot"], "目标身份或作者链改变")
                locations = original["altloc_codes"]
                require("altloc" in spec and (spec["altloc"] in locations if locations
                        else spec["altloc"] is None), "请按原件明确选择替代构象")
                if spec.get("pocket") == "reference":
                    expected = original["spec"]
                    require(original.get("reference_count_matches") is True
                            and original.get("reference_covalent_count") == 0
                            and all(spec.get(k) == expected.get(k) for k in
                                    ("reference_code", "reference_chain", "reference_sequence")),
                            "参考配体定位、完整性或非共价关系与原件不符")
        except (ValueError, KeyError, TypeError) as error:
            result.update(valid=False, bulk_allowed=False, reason_zh=str(error))
        out.append(result)
    return out


def source_compound_issues(source, plan, materials):
    """不能把另一CID或未经本轮原件核查的上传版本标成已核对的配体方案。"""
    if not source:
        return []
    rows = {r["compound_id"]: r for r in source["compounds"]}
    originals = {f["key"]: f["file"] for f in source["files"]}
    uploaded = {r["material_id"]: r for r in materials}
    issues = []
    for row in plan.get("compounds", []) or []:
        if not isinstance(row, dict) or row.get("status") != "use":
            continue
        origin = rows.get(row.get("compound_id"))
        try:
            require(origin is not None and origin["identity_matched"]
                    and str(row.get("cid")) == str(origin["cid"]), "CID或化学身份与本轮原件不符")
            mid = row.get("material_id")
            if mid:
                require(mid in uploaded and uploaded[mid]["file"]["sha256"]
                        == originals[origin["file_key"]]["sha256"], "新三维资料尚未完成本轮原件核查")
        except (ValueError, KeyError, TypeError) as error:
            issues.append({"kind": "compound", "id": row.get("compound_id", "unknown"),
                "label_zh": (origin or {}).get("name_zh") or row.get("compound_id", "未知成分"),
                "reason_zh": str(error)})
    return issues
