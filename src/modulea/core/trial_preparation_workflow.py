"""把已确认扩展试算的准备证据关联到前页，不改科研版本或代签审批。"""

from copy import deepcopy

from contracts import ContractError, require
from storage import (
    file_record,
    new_id,
    now,
    read_json,
    verified_file,
    write_json,
    write_lock,
)

from .trial_handoff_workflow import TrialHandoffWorkflow

VERSION = "A06.trial.preparation_link.1"


def preparation_files(packet):
    """收集实际准备及来源证据，保留原始指纹，不包含评分矩阵。"""
    records = {}

    def collect(value):
        if isinstance(value, dict):
            if {"path", "sha256", "bytes"} <= value.keys():
                key = (value["path"], value["sha256"])
                records[key] = deepcopy(value)
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(packet["compounds"])
    collect(packet["receptors"])
    return sorted(records.values(), key=lambda r: (r["path"], r["sha256"]))


class TrialPreparationWorkflow(TrialHandoffWorkflow):
    """关联是技术溯源记录，正式批准仍只由原review方法判断。"""

    def _resolve_preparation_sources(self, manifest, packet):
        """历史复用受体沿原准备与来源索引追溯，不按文件名猜测原件。"""
        packet = deepcopy(packet)
        missing = [r for r in packet["receptors"] if not r.get("source")]
        if not missing:
            return packet, []
        root = self.location(manifest["study_id"])
        base_record = packet["base_packet"]
        base = read_json(verified_file(root, base_record))
        evidence = [deepcopy(base_record)]
        for row in missing:
            require(row.get("reused"), "未复用受体缺少来源原件")
            chosen = next(
                (
                    r.get("selected")
                    for r in base["receptors"]
                    if r["target_id"] == row["target_id"]
                ),
                None,
            )
            require(
                chosen
                and chosen["receptor"]["path"] == row["receptor"]["path"]
                and chosen["receptor"]["sha256"] == row["receptor"]["sha256"],
                "复用准备文件与原证据不一致",
            )
            source_id = chosen["identity"]["source_review_id"]
            records = [
                (r, read_json(verified_file(root, r)))
                for r in manifest.get("source_review_records", [])
            ]
            match = next(
                (
                    (r, s)
                    for r, s in records
                    if s["review_id"] == source_id
                    and s["study_id"] == manifest["study_id"]
                ),
                None,
            )
            require(match, "复用结构的来源核查索引缺失")
            source_record, source = match
            source_row = next(
                (
                    r
                    for r in source["receptors"]
                    if r["target_id"] == row["target_id"]
                    and r["pdb_id"] == row["structure_id"]
                ),
                None,
            )
            require(
                source_row
                and source_row["identity_matched"]
                and source_row["spec"]["uniprot"] == row["spec"]["uniprot"],
                "复用结构原件身份不匹配",
            )
            original = next(
                (
                    r["file"]
                    for r in source["files"]
                    if r["key"] == source_row["file_key"]
                ),
                None,
            )
            require(original, "复用结构来源原件未登记")
            verified_file(root, original)
            row["source"] = deepcopy(original)
            row["source_resolution_zh"] = (
                "由同一准备文件指纹追溯原来源核查及结构原件；未修改本批归档。"
            )
            evidence.append(deepcopy(source_record))
        return packet, list({r["path"]: r for r in evidence}.values())

    def _preparation_binding(self, manifest):
        """重新核对同研究、当前批准、准备字节及已有人工核查。"""
        require(not manifest.get("trashed"), "回收站研究只读")
        sid = manifest["study_id"]
        rid = manifest["current"].get("A06")
        require(rid and self.approved(manifest, rid), "当前A06尚未有效批准")
        run = self.run(manifest, rid)
        require(
            run["config"].get("schema_version") == "A06.trial.handoff.1",
            "当前A06不是扩展试算交接版本",
        )
        trial = self.handoff_binding(manifest, run["inputs"])
        root = self.location(sid)
        packet = read_json(verified_file(root, trial["packet"]))
        require(
            packet["study_id"] == sid and packet["trial_id"] == trial["trial_id"],
            "准备资料跨研究或批次",
        )
        require(
            len(packet["compounds"]) == len(packet["receptors"]) == 15,
            "准备范围必须对应本批15×15",
        )
        require(
            len({c["compound_id"] for c in packet["compounds"]}) == 15
            and len({r["target_id"] for r in packet["receptors"]}) == 15,
            "准备名单重复",
        )
        packet, resolution_files = self._resolve_preparation_sources(manifest, packet)
        for compound in packet["compounds"]:
            require(compound["state"] == "ready", "本批成分尚未准备完成")
            require(
                {"source_3d", "prepared_ligand"}
                <= {f.get("role") for f in compound["files"]},
                "成分缺少来源三维或准备文件",
            )
        for receptor in packet["receptors"]:
            require(
                receptor["state"] == "ready"
                and receptor.get("source")
                and receptor.get("receptor"),
                "本批受体缺少准备证据",
            )
        review = self.latest_review(manifest, run["artifact_id"])
        review_record = next(
            r
            for r in manifest["reviews"]
            if read_json(verified_file(root, r))["review_id"] == review["review_id"]
        )
        files = sorted(
            {
                r["path"]: r for r in preparation_files(packet) + resolution_files
            }.values(),
            key=lambda r: r["path"],
        )
        for record in files:
            verified_file(root, record)
        binding = {
            "study_id": sid,
            "a06_run_id": rid,
            "a06_result": deepcopy(manifest["runs"][rid]["result_file"]),
            "a06_review": deepcopy(review_record),
            "trial_id": trial["trial_id"],
            "trial_packet": deepcopy(trial["packet"]),
            "trial_review": deepcopy(run["inputs"]["trial_review"]),
            "legacy_run_id": manifest["current"].get("A06_PREP"),
            "preparation_files": files,
        }
        return binding, packet

    def link_trial_preparation(self, sid, expected_a06, expected_review_id, reason):
        """追加明确绑定的技术关联；不更换指针、不写人工reviews。"""
        require(isinstance(reason, str) and reason.strip(), "请说明准备关联依据")
        with write_lock(self.root), self.handoff_read_cache():
            manifest = self.load(sid)
            require(manifest["current"].get("A06") == expected_a06, "A06版本已改变")
            binding, _ = self._preparation_binding(manifest)
            root = self.location(sid)
            require(
                read_json(verified_file(root, binding["a06_review"]))["review_id"]
                == expected_review_id,
                "A06批准已改变",
            )
            records = manifest.get("trial_preparation_link_records", [])
            if records:
                old = read_json(verified_file(root, records[-1]))
                if old.get("schema_version") == VERSION and old["binding"] == binding:
                    return old
            link = {
                "schema_version": VERSION,
                "link_id": new_id("prep_link"),
                "created_at": now(),
                "reason_zh": reason.strip(),
                "binding": binding,
                "files": binding["preparation_files"]
                + [binding["trial_review"], binding["a06_review"]],
            }
            path = (
                root
                / "decisions/A06_trial_preparation_link"
                / (link["link_id"] + ".json")
            )
            write_json(path, link)
            manifest.setdefault("trial_preparation_link_records", []).append(
                file_record(root, path, "trial_preparation_link")
            )
            self.save(manifest)
            return link

    def trial_preparation_context(self, manifest):
        """返回有效关联或明确的失效原因；不把历史严格准备改成已批准。"""
        records = manifest.get("trial_preparation_link_records", [])
        if not records:
            return None
        root = self.location(manifest["study_id"])
        link = read_json(verified_file(root, records[-1]))
        require(
            link["schema_version"] == VERSION
            and link["binding"]["study_id"] == manifest["study_id"],
            "准备关联归档不匹配",
        )
        binding = link["binding"]
        reason, packet = "", None
        try:
            current, packet = self._preparation_binding(manifest)
            require(current == binding, "批准、名单或准备版本已改变，请重新核查关联")
        except ContractError as error:
            reason, packet = str(error), None
        trial_review = read_json(verified_file(root, binding["trial_review"]))
        a06_review = read_json(verified_file(root, binding["a06_review"]))
        legacy = (
            self.result(manifest, binding["legacy_run_id"])
            if binding["legacy_run_id"]
            else None
        )
        return {
            "link_id": link["link_id"],
            "created_at": link["created_at"],
            "active": packet is not None,
            "read_only": True,
            "reason_zh": reason,
            "a06_run_id": binding["a06_run_id"],
            "trial_id": binding["trial_id"],
            "reviewer": trial_review["reviewer"],
            "reviewed_at": trial_review.get("created_at"),
            "note": trial_review["note"],
            "a06_reviewer": a06_review["reviewer"],
            "a06_reviewed_at": a06_review["created_at"],
            "result_url": f"#/studies/{manifest['study_id']}/A06"
            + ("" if packet else f"?run_id={binding['a06_run_id']}"),
            "legacy_run_id": binding["legacy_run_id"],
            "compounds": deepcopy(packet["compounds"]) if packet else [],
            "receptors": deepcopy(packet["receptors"]) if packet else [],
            "files": deepcopy(link["files"]),
            "history_rows": deepcopy(
                (legacy or {}).get("tables", {}).get("receptor_diagnostics", [])
            ),
        }

    def _view_snapshot(self, study_id):
        """当前扩展准备关口状态来自同一Workflow，科研批准谓词不变。"""
        view = super()._view_snapshot(study_id)
        context = self.trial_preparation_context(view["manifest"])
        view["trial_preparation"] = context
        if context:
            raw = next(m for m in view["modules"] if m["module_id"] == "A06_PREP")
            raw["legacy_state"] = raw["state"]
            raw["state"] = "scope_confirmed" if context["active"] else "stale"
            raw["preparation_scope"] = context
        return view
