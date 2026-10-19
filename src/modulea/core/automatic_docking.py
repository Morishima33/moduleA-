"""一次授权自动对接的Workflow入口：独立版本、原件索引、失效判断和结果复核。"""
from copy import deepcopy
from pathlib import Path
import re
from contracts import SCHEMA_VERSION, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from science_modules.a06.automatic_rules import VERSION, POLICY, SUMMARY, DETAILS, binding
from .ranked_pathway_workflow import RankedPathwayWorkflow


# 新协议显式绑定已批准的输入和一次执行授权，不批准或解除旧A06_PREP协议。
class AutomaticDockingWorkflow(RankedPathwayWorkflow):
    def active(self, manifest, run_id):
        """单次查询复用依赖校验，不跨请求缓存版本或文件状态。"""
        if getattr(self, "_view_cache", None) is not None:
            return super().active(manifest, run_id)
        with self.handoff_read_cache():
            return super().active(manifest, run_id)

    def approved(self, manifest, run_id):
        """单次查询复用复核链，科学可用性仍由原内核判断。"""
        if getattr(self, "_view_cache", None) is not None:
            return super().approved(manifest, run_id)
        with self.handoff_read_cache():
            return super().approved(manifest, run_id)

    def _begin(self, manifest, module, inputs, config, reason):
        """冻结报告适配前禁止把新协议当旧报告输入。"""
        a06 = manifest.get("current", {}).get("A06")
        if module == "A07" and a06:
            require(self.run(manifest, a06).get("config", {}).get("schema_version") != VERSION,
                    "自动对接新协议尚未接入冻结报告模板，请先完成报告适配")
        return super()._begin(manifest, module, inputs, config, reason)

    def automatic_binding(self, sid, expected=None, manifest=None):
        manifest = manifest or self.load(sid)
        if getattr(self, "_view_cache", None) is not None:
            data = binding(self, manifest)
        else:
            with self.handoff_read_cache():
                data = binding(self, manifest)
        require(expected is None or expected == fingerprint(data), "对接输入或复核已改变，请刷新")
        return manifest, data

    # 连接及评分共用研究内索引；只读文件下载不接受任意路径。
    def automatic_record(self, manifest, identity):
        for key in ("automatic_connections", "automatic_batches"):
            for row in manifest.get(key, []):
                if row["id"] == identity:
                    return row
        return None

    def current_automatic_connection(self, manifest, key):
        rows = manifest.get("automatic_connections", [])
        if not rows or rows[-1]["binding"] != key:
            return None
        return rows[-1]

    # 只追加已经取得的资料与逐项异常；连接并不授权评分。
    def save_automatic_connection(self, sid, expected, packet, files):
        with write_lock(self.root):
            manifest, bound = self.automatic_binding(sid, expected)
            require(packet["study_id"] == sid and packet["binding"] == expected and packet["policy"] == POLICY, "自动连接资料归属或策略不一致")
            safe_id(packet["id"], "connection")
            existing = self.automatic_record(manifest, packet["id"])
            if existing:
                require(existing["binding"] == expected and read_json(verified_file(self.location(sid), existing["packet"])) == packet, "同一连接编号内容不一致")
                return existing
            for record in files:
                verified_file(self.location(sid), record)
            path = self.location(sid) / "decisions/A06_automatic" / (packet["id"] + ".json")
            write_json(path, packet)
            row = {"id": packet["id"], "binding": expected, "created_at": now(), "packet": file_record(self.location(sid), path, "automatic_connection"), "files": files}
            manifest.setdefault("automatic_connections", []).append(row)
            self.save(manifest)
            return row

    # 所有授权字段显式核对；浏览器不能替换参数、结构、名单或工具路径。
    def validate_automatic_request(self, sid, payload, manifest=None):
        fields = {"expected_binding", "expected_connection_id", "expected_a06", "request_id", "policy_version", "reviewer", "note", "confirmed"}
        require(isinstance(payload, dict) and set(payload) == fields, "自动计算请求字段不完整或含隐藏参数")
        require(isinstance(payload["expected_binding"], str) and re.fullmatch(r"[0-9a-f]{64}", payload["expected_binding"]), "自动输入指纹不合法，请刷新")
        require(payload["confirmed"] is True and payload["policy_version"] == VERSION, "请明确确认本次自动策略及执行范围")
        require(all(isinstance(payload[k], str) and 0 < len(payload[k].strip()) <= 2000 for k in ("reviewer", "note")), "请填写实际确认人和执行说明")
        safe_id(payload["request_id"], "auto")
        manifest, bound = self.automatic_binding(sid, payload["expected_binding"], manifest)
        connection = self.current_automatic_connection(manifest, payload["expected_binding"])
        require(connection and connection["id"] == payload["expected_connection_id"], "连接资料已更新，请刷新")
        packet = read_json(verified_file(self.location(sid), connection["packet"]))
        require(packet["summary"]["connected_compounds"] > 0 and packet["summary"]["connected_receptors"] > 0, "尚无可用成分或受体连接，请先处理集中异常清单")
        existing = self.automatic_record(manifest, payload["request_id"])
        current = manifest["current"].get("A06")
        require(current == payload["expected_a06"] or (existing and existing.get("run_id") == current), "A06结果已改变，请刷新后重新确认")
        return manifest, bound, connection

    def authorize_automatic(self, sid, payload):
        with write_lock(self.root):
            manifest, bound, connection = self.validate_automatic_request(sid, payload)
            existing = self.automatic_record(manifest, payload["request_id"])
            if existing:
                original = read_json(verified_file(self.location(sid), existing["authorization"]))
                require(original["request"] == payload, "同一自动请求的内容不一致")
                return existing
            authorization = {"schema_version": VERSION, "study_id": sid, "id": payload["request_id"], "created_at": now(), "request": deepcopy(payload), "binding": bound, "connection": connection["packet"], "policy": deepcopy(POLICY), "approval": None}
            path = self.location(sid) / "decisions/A06_automatic" / (payload["request_id"] + ".json")
            write_json(path, authorization)
            row = {"id": payload["request_id"], "binding": payload["expected_binding"], "connection_id": connection["id"], "created_at": now(), "authorization": file_record(self.location(sid), path, "automatic_authorization"), "state": "authorized", "run_id": None, "files": [], "attempts": []}
            manifest.setdefault("automatic_batches", []).append(row)
            self.save(manifest)
            return row

    # A06新结果采用独立输入链；准备是本次任务的技术证据，不伪造人工通过。
    def begin_automatic(self, sid, payload):
        self.authorize_automatic(sid, payload)
        with write_lock(self.root):
            manifest, bound, connection = self.validate_automatic_request(sid, payload)
            batch = self.automatic_record(manifest, payload["request_id"])
            if batch["state"] == "completed" and self.active(manifest, batch["run_id"]):
                return batch, self.run(manifest, batch["run_id"]), True
            inputs = {"automatic_authorization": batch["authorization"], "automatic_connection": connection["packet"]}
            artifacts = [self.run(manifest, rid)["artifact_id"] for rid in bound["runs"].values()]
            config = {"schema_version": VERSION, "policy": deepcopy(POLICY)}
            run = {"schema_version": SCHEMA_VERSION, "study_id": sid, "run_id": new_id("run"), "module_id": "A06", "artifact_id": new_id("artifact"), "parent_runs": bound["runs"], "parent_review_ids": bound["reviews"], "parent_artifact_ids": artifacts, "inputs": inputs, "config": config, "input_hash": fingerprint({"inputs": inputs, "parents": artifacts}), "config_hash": fingerprint(config), "code_version": self.code_version, "environment_version": fingerprint(self.environment), "environment": self.environment, "created_at": now(), "reason": "一次授权自动准备、质控和对接；结果待独立复核"}
            path = self.location(sid) / "runs/A06" / run["run_id"] / "run.json"
            write_json(path, run)
            manifest["runs"][run["run_id"]] = {"run_file": file_record(self.location(sid), path, "run"), "result_file": None}
            manifest["current"]["A06"] = run["run_id"]
            batch.update(state="running", run_id=run["run_id"])
            batch["attempts"].append({"run_id": run["run_id"], "started_at": now()})
            self.save(manifest)
            return batch, run, False

    def _active(self, manifest, run_id):
        if not super()._active(manifest, run_id):
            return False
        run = self.run(manifest, run_id)
        if run.get("config", {}).get("schema_version") == VERSION:
            try:
                _, bound = AutomaticDockingWorkflow.automatic_binding(self, manifest["study_id"], manifest=manifest)
                key = fingerprint(bound)
                connection = self.current_automatic_connection(manifest, key)
                verified_file(self.location(manifest["study_id"]), run["inputs"]["automatic_connection"])
                verified_file(self.location(manifest["study_id"]), run["inputs"]["automatic_authorization"])
                return bool(connection and connection["packet"] == run["inputs"]["automatic_connection"])
            except ValueError:
                return False
        return True

    # 公开完成入口在写锁内再次核验所有输入；异常与成功均保留原始文件。
    def finish_automatic(self, sid, payload, run_id, packet, summary, tables, files):
        with write_lock(self.root):
            manifest, _, _ = self.validate_automatic_request(sid, payload)
            batch = self.automatic_record(manifest, payload["request_id"])
            require(batch["run_id"] == run_id and manifest["current"]["A06"] == run_id, "本轮自动结果已改变，请刷新")
            for record in files:
                verified_file(self.location(sid), record)
            result = self._finish(manifest, run_id, summary, tables, ["自动计算不代表实验验证；探索位点与严格质控分别记录"], "success", attachments=files)
            batch.update(state="completed", summary=summary, packet=packet, files=files)
            self.save(manifest)
            return result

    def fail_automatic(self, sid, identity, reason):
        with write_lock(self.root):
            manifest = self.load(sid)
            batch = self.automatic_record(manifest, identity)
            if not batch or batch.get("state") == "completed":
                return
            batch.update(state="failed", error_zh=reason)
            if batch.get("run_id"):
                folder = self.location(sid) / "runs/A06" / batch["run_id"]
                batch["files"] = [file_record(self.location(sid), p, "automatic_failure_evidence") for p in folder.rglob("*") if p.is_file()]
            self.save(manifest)


# 页面只读汇总，不重新选结构、计算或修改任何确认状态。
def automatic_context(workflow, manifest, historical=False, busy=False):
    if historical:
        return None
    sid = manifest["study_id"]
    data = {"enabled": False, "disabled_reason_zh": "", "expected_binding": "", "expected_connection_id": None, "expected_a06": manifest["current"].get("A06"), "counts": {"compounds": 0, "receptors": 0, "pairs": 0}, "policy": {"version": VERSION, "summary_zh": SUMMARY, "details_zh": DETAILS}, "connection": None, "latest": None}
    try:
        _, bound = workflow.automatic_binding(sid, manifest=manifest)
        key = fingerprint(bound)
        data["expected_binding"] = key
        selected = workflow.result(manifest, bound["runs"]["A03_SELECT"])["tables"]["selected"]
        from science_modules.a06.candidates import build
        targets = build(workflow.result(manifest, bound["runs"]["A04"])["tables"])["degree_top15"]
        data["counts"] = {"compounds": len(selected), "receptors": len(targets), "pairs": len(selected) * len(targets)}
        record = workflow.current_automatic_connection(manifest, key)
        if record:
            packet = read_json(verified_file(workflow.location(sid), record["packet"]))
            data["expected_connection_id"] = record["id"]
            data["connection"] = {"id": record["id"], "created_at": record["created_at"], "summary": packet["summary"], "exceptions": packet["exceptions"], "objects": packet["objects"], "files": [{"name": Path(f["path"]).name, "path": f["path"], "role": f["role"], "url": f"/api/v1/studies/{sid}/automatic_docking/{record['id']}/files/{i}"} for i, f in enumerate(record["files"])]}
            data["counts"] = packet["counts"]
        rows = manifest.get("automatic_batches", [])
        if rows and rows[-1]["binding"] == key:
            batch = rows[-1]
            item = {k: batch.get(k) for k in ("id", "state", "run_id", "summary", "error_zh")}
            item["files"] = [{"name": Path(f["path"]).name, "path": f["path"], "role": f["role"], "url": f"/api/v1/studies/{sid}/automatic_docking/{batch['id']}/files/{i}"} for i, f in enumerate(batch["files"])]
            item["pairs"] = []
            if batch.get("packet"):
                facts = read_json(verified_file(workflow.location(sid), batch["packet"]))
                for pair in facts["pairs"]:
                    receptor = next(r for r in facts["receptors"] if r["target_id"] == pair["target_id"])
                    compound = next(r for r in facts["compounds"] if r["compound_id"] == pair["compound_id"])
                    item["pairs"].append({**pair, "compound_name": compound.get("name", pair["compound_id"]), "symbol": receptor["symbol"], "trace": {"candidate": receptor.get("selected_candidate"), "quality_evidence": receptor.get("evidence"), "ligand": {k: compound.get(k) for k in ("cid", "audit", "files", "reason_zh")}, "attempts": receptor.get("attempts", []), "policy": POLICY}})
                    refs = set()
                    def collect(value):
                        """只收集当前组合已归档的文件指纹，不接受浏览器路径。"""
                        if isinstance(value, dict):
                            if "path" in value and "sha256" in value:
                                refs.add(value["path"])
                            for child in value.values():
                                collect(child)
                        elif isinstance(value, list):
                            for child in value:
                                collect(child)
                    collect(item["pairs"][-1])
                    score_prefix = f"runs/A06/{batch['run_id']}/automatic/scores/{pair['compound_id']}/{pair['target_id'].replace(':','_')}/"
                    item["pairs"][-1]["evidence_files"] = [f for f in item["files"] if f["path"] in refs or f["path"].startswith(score_prefix)]
            if item["state"] == "running" and not busy:
                item["state"] = "interrupted"
            if batch["connection_id"] != data["expected_connection_id"]:
                item.update(state="stale", error_zh="连接资料已更新；以下旧批次只供追溯，请重新确认当前范围后计算")
            data["latest"] = item
        data["enabled"] = not busy and not manifest.get("trashed")
        data["disabled_reason_zh"] = "请等待当前研究后台任务结束" if busy else ""
    except (ValueError, KeyError) as error:
        data["disabled_reason_zh"] = str(error)
    return data
