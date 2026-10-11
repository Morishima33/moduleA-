"""身份补查方案由Workflow公开方法留存；只限定本研究和本A03，不代签科研结果。"""

import hashlib
from pathlib import Path
from contracts import require
from storage import file_record, now, read_json, verified_file, write_json, write_lock
from workflow import Workflow

SCHEMA = "A04.identity.plan.1"
RULE = "STRING.explicit_scope.1"


# 官方依据可来自全局参考库或本研究已归档的同指纹原件；不猜最新文件。
def identity_snapshot(root, sid, sha):
    candidates = [
        Path(root) / "references/hgnc_complete_set_20260913.tsv",
        Path(root) / "studies" / sid / "raw" / ("hgnc_" + sha + ".tsv"),
    ]
    for path in candidates:
        if path.is_file():
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == sha, "HGNC官方快照校验失败，请核对原件")
            return raw
    require(False, "HGNC官方快照缺失，请补齐资料后重试")


# 人工方案只追加；索引中的指纹保证历史运行可读取原决定。
class IdentityWorkflow(Workflow):
    def identity_plan(self, manifest, a03):
        for record in reversed(manifest.get("identity_decisions", [])):
            decision = read_json(verified_file(self.location(manifest["study_id"]), record))
            require(
                decision.get("schema_version") == SCHEMA
                and decision.get("study_id") == manifest["study_id"],
                "身份方案归档校验失败",
            )
            if decision.get("scope", {}).get("a03_run") == a03:
                return decision, record
        return None, None

    # 补查失败的已返回原文也留存，不伪装成零命中或覆盖另一尝试。
    def save_identity_evidence(self, sid, decision_record, responses, error_zh):
        from storage import new_id

        with write_lock(self.root):
            manifest = self.load(sid)
            require(not manifest.get("trashed"), "回收站中的研究只读")
            decision = read_json(verified_file(self.location(sid), decision_record))
            require(
                decision.get("study_id") == sid
                and decision_record in manifest.get("identity_decisions", []),
                "补查证据不属于本研究的人工方案",
            )
            evidence = {
                "schema_version": "A04.identity.probes.1",
                "evidence_id": new_id("evidence"),
                "decision_id": decision["decision_id"],
                "study_id": sid,
                "created_at": now(),
                "responses": responses,
                "error_zh": error_zh,
                "completed": not bool(error_zh),
            }
            path = (
                self.location(sid) / "decisions/A04_identity" / (evidence["evidence_id"] + ".json")
            )
            write_json(path, evidence)
            record = file_record(self.location(sid), path, "identity_probe_source")
            manifest.setdefault("identity_evidence", []).append(record)
            self.save(manifest)
            return evidence, record

    # 保存前和后台执行前使用同样的研究、上游、问题清单和并发检查。
    def validate_identity_plan(self, sid, payload, manifest=None):
        manifest = manifest or self.load(sid)
        require(not manifest.get("trashed"), "回收站中的研究只读")
        a03, a04 = payload.get("expected_a03"), payload.get("expected_a04")
        require(
            a03
            and a04
            and manifest["current"].get("A03") == a03
            and manifest["current"].get("A04") == a04,
            "交集或PPI版本已改变，请刷新",
        )
        require(
            self.active(manifest, a03)
            and self.approved(manifest, a03)
            and self.active(manifest, a04),
            "请先通过有效上游A03，并使用当前有效A04",
        )
        parent = self.run(manifest, a04)
        require(parent["parent_runs"].get("A03") == a03, "PPI上游版本已改变，请刷新")
        result = self.result(manifest, a04)
        issues = {r["target_id"] for r in result.get("tables", {}).get("identity_issues", [])}
        ids, omitted = payload.get("check_ids"), payload.get("omit_ids")
        require(
            isinstance(ids, list)
            and ids
            and all(isinstance(x, str) for x in ids)
            and len(set(ids)) == len(ids)
            and set(ids) <= issues,
            "请从本次待核验清单选择补查项，不能混用其他研究或版本",
        )
        require(
            isinstance(omitted, list)
            and all(isinstance(x, str) for x in omitted)
            and len(set(omitted)) == len(omitted)
            and set(omitted) <= set(ids),
            "暂不采用范围必须属于本次补查项",
        )
        require(payload.get("confirmed") is True, "请明确确认本次补查方案")
        require(
            all(
                isinstance(payload.get(k), str) and 0 < len(payload[k].strip()) <= 2000
                for k in ("reviewer", "note")
            ),
            "请填写核验人和核验说明（每项不超过2000字）",
        )
        latest, _ = self.identity_plan(manifest, a03)
        # 失败重试复用同一决定，其他页的旧版本不能覆盖更新的人工方案。
        expected = payload.get("expected_decision_id") or None
        actual = latest["decision_id"] if latest else None
        require(
            actual == expected or actual == payload.get("decision_id"),
            "身份方案已更新，请刷新后重新确认",
        )
        return manifest

    # 决定和 manifest 指针在统一写锁下追加；重试不重复代签。
    def save_identity_plan(self, sid, payload):
        with write_lock(self.root):
            manifest = self.validate_identity_plan(sid, payload)
            latest, record = self.identity_plan(manifest, payload["expected_a03"])
            if latest and latest["decision_id"] == payload["decision_id"]:
                require(latest["request"] == payload, "重试方案与已保存决定不一致")
                return latest, record
            from contracts import safe_id

            safe_id(payload["decision_id"], "decision")
            prior_run = self.run(manifest, payload["expected_a04"])
            carried = prior_run.get("inputs", {}).get("identity_authorization")
            previous_scope = (
                read_json(verified_file(self.location(sid), carried))["scope"] if carried else {}
            )
            scope = {
                "study_id": sid,
                "a03_run": payload["expected_a03"],
                "check_ids": list(
                    dict.fromkeys(previous_scope.get("check_ids", []) + payload["check_ids"])
                ),
                "omit_ids": list(
                    dict.fromkeys(previous_scope.get("omit_ids", []) + payload["omit_ids"])
                ),
                "decision": payload["reviewer"].strip() + "：" + payload["note"].strip(),
            }
            decision = {
                "schema_version": SCHEMA,
                "identity_rule": RULE,
                "decision_id": payload["decision_id"],
                "study_id": sid,
                "a04_run": payload["expected_a04"],
                "created_at": now(),
                "reviewer": payload["reviewer"].strip(),
                "note": payload["note"].strip(),
                "scope": scope,
                "a03_result": manifest["runs"][payload["expected_a03"]]["result_file"],
                "a04_result": manifest["runs"][payload["expected_a04"]]["result_file"],
                "request": dict(payload),
                "carried_authorization": carried,
            }
            path = (
                self.location(sid) / "decisions/A04_identity" / (payload["decision_id"] + ".json")
            )
            write_json(path, decision)
            record = file_record(self.location(sid), path, "identity_authorization")
            manifest.setdefault("identity_decisions", []).append(record)
            self.save(manifest)
            return decision, record


# 页面只显示方案保存和实际应用结果；不会把“已确认方案”算作“已核验身份”。
def plan_view(workflow, manifest, run, result, enabled, historical=False):
    if not run or run["module_id"] != "A04":
        return None
    a03 = run.get("parent_runs", {}).get("A03", "")
    decision, record = workflow.identity_plan(manifest, a03)
    if historical:
        record = run.get("inputs", {}).get("identity_authorization")
        decision = (
            read_json(verified_file(workflow.location(manifest["study_id"]), record))
            if record
            else None
        )
    applied = None
    if record:
        for rid in reversed(list(manifest["runs"])):
            candidate = workflow.run(manifest, rid)
            if candidate.get("inputs", {}).get("identity_authorization") == record and manifest[
                "runs"
            ][rid].get("result_file"):
                applied = workflow.result(manifest, rid)
                break
    probe = None
    if decision:
        for evidence_record in reversed(manifest.get("identity_evidence", [])):
            candidate = read_json(
                verified_file(workflow.location(manifest["study_id"]), evidence_record)
            )
            if candidate["decision_id"] == decision["decision_id"]:
                probe = candidate
                break
    pending = len((result or {}).get("tables", {}).get("identity_issues", []))
    return {
        "enabled": bool(enabled and pending and not historical),
        "disabled_reason_zh": ""
        if enabled and pending and not historical
        else "请使用当前有效A04，并等待活动任务结束；历史和回收站只读。",
        "expected_a03": a03,
        "expected_a04": run["run_id"],
        "expected_decision_id": decision["decision_id"] if decision else None,
        "latest": {
            "decision_id": decision["decision_id"],
            "reviewer": decision["reviewer"],
            "note_zh": decision["note"],
            "created_at": decision["created_at"],
            "check_ids": decision["scope"]["check_ids"],
            "omit_ids": decision["scope"]["omit_ids"],
            "applied_run_id": applied["run_id"] if applied else None,
            "pending_count": applied["summary"].get("身份待核验数", 0) if applied else None,
            "evidence_url": "/api/v1/studies/"
            + manifest["study_id"]
            + "/modules/A04/identity_evidence/"
            + probe["evidence_id"]
            if probe
            else None,
            "error_zh": probe.get("error_zh", "") if probe else "",
            # 通过状态只读取Workflow的实际批准关系，不把保存方案视为模块通过。
            "status_zh": "已应用，A04已通过复核"
            if applied and workflow.approved(manifest, applied["run_id"])
            else "已应用，新A04仍待独立复核"
            if applied
            else "方案已保存，尚未成功生成新A04；请查看任务结果",
        }
        if decision
        else None,
    }
