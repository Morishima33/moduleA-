"""A05人工展示确认由Workflow公开方法保存，界面状态只读取不可变归档。"""

from contracts import require, safe_id
from storage import write_lock, write_json, read_json, verified_file, file_record, now
from .identity_workflow import IdentityWorkflow

from science_modules.a05.display import metadata

SCHEMA = "A05.display.decision.1"


# 科学运行和人工决定在同一研究锁下绑定；旧索引和审批保留。
class EnrichmentWorkflow(IdentityWorkflow):
    def display_decision(self, manifest, a03, base_run):
        for record in reversed(manifest.get("enrichment_display_decisions", [])):
            decision = read_json(verified_file(self.location(manifest["study_id"]), record))
            require(decision["study_id"] == manifest["study_id"] and decision["schema_version"] == SCHEMA, "A05确认记录归属或版本不一致")
            if decision["a03_run"] == a03 and decision["base_run"] == base_run:
                return decision, record
        return None, None

    # 只接受本次显著名单，零项排除也须明确核对确认；版式确认不能暗中换名单。
    def validate_display_confirmation(self, sid, payload, manifest=None):
        manifest = manifest or self.load(sid)
        require(not manifest.get("trashed"), "回收站中的研究只读")
        rid, a03 = payload.get("expected_a05"), payload.get("expected_a03")
        require(manifest["current"].get("A05") == rid and manifest["current"].get("A03") == a03, "A05或交集版本已改变，请刷新")
        require(rid and self.active(manifest, rid) and self.approved(manifest, a03), "请使用当前有效A05及已通过A03")
        result = self.result(manifest, rid)
        meta = metadata(result["tables"])
        require(meta, "当前A05尚未准备新版展示")
        require(payload.get("action") in ("exclusions", "layout"), "未知展示确认操作")
        ids = payload.get("excluded_ids")
        require(isinstance(ids, list) and all(isinstance(x, str) for x in ids) and len(ids) == len(set(ids)), "排除清单格式不正确")
        require(set(ids) <= {r["ID"] for r in result["tables"]["kegg_significant"]}, "不能混用其他研究或非显著条目")
        require(payload.get("confirmed") is True, "请勾选本次核对确认")
        require(all(isinstance(payload.get(k), str) and 0 < len(payload[k].strip()) <= 2000 for k in ("reviewer", "note")), "请填写核验人和说明（每项不超过2000字）")
        latest, record = self.display_decision(manifest, a03, meta["base_run"])
        require((latest["decision_id"] if latest else None) == (payload.get("expected_decision_id") or None), "展示确认记录已更新，请刷新")
        if payload["action"] == "layout":
            require(meta.get("exclusions_confirmed") and not meta["missing_translations"], "请先确认展示范围并补齐图表中文")
            require(set(ids) == set(meta["excluded_ids"]), "确认版式不能同时修改排除清单，请先保存新清单")
        return manifest, result

    # 已保存但任务未应用的记录仍留存；失败重试复用相同决定，不重复签名。
    def save_display_confirmation(self, sid, payload):
        with write_lock(self.root):
            manifest = self.load(sid)
            for record in manifest.get("enrichment_display_decisions", []):
                decision = read_json(verified_file(self.location(sid), record))
                if decision["decision_id"] == payload["decision_id"]:
                    require(decision["request"] == payload, "重试的确认内容与已保存记录不一致")
                    current = manifest["current"].get("A05")
                    result = self.result(manifest, current) if current else None
                    require(current == payload["expected_a05"] or (result and (metadata(result["tables"]) or {}).get("decision_id") == decision["decision_id"]), "确认已过期，不能在新版本上重试")
                    return decision, record
            manifest, result = self.validate_display_confirmation(sid, payload, manifest)
            safe_id(payload["decision_id"], "decision")
            meta = metadata(result["tables"])
            decision = {"schema_version": SCHEMA, "decision_id": payload["decision_id"], "study_id": sid, "a03_run": payload["expected_a03"], "a05_run": payload["expected_a05"], "base_run": meta["base_run"], "created_at": now(), "reviewer": payload["reviewer"].strip(), "note": payload["note"].strip(), "action": payload["action"], "excluded_ids": sorted(payload["excluded_ids"]), "exclusions_confirmed": True, "layout_confirmed": payload["action"] == "layout", "request": dict(payload)}
            path = self.location(sid) / "decisions/A05_display" / (decision["decision_id"]+".json")
            write_json(path, decision)
            record = file_record(self.location(sid), path, "enrichment_display_decision")
            manifest.setdefault("enrichment_display_decisions", []).append(record)
            self.save(manifest)
            return decision, record

    # 资料归档和索引更新在研究锁内，写入接口不能直接改studies文件。
    def archive_enrichment_display_source(self, sid, expected_a05, source):
        from storage import new_id
        with write_lock(self.root):
            manifest = self.load(sid)
            require(not manifest.get("trashed") and manifest["current"].get("A05") == expected_a05 and self.active(manifest, expected_a05), "A05或研究状态已改变，请刷新")
            path = self.location(sid)/"raw/A05_display"/(new_id("source")+".json")
            write_json(path,source)
            record = file_record(self.location(sid),path,"enrichment_display_source")
            manifest.setdefault("enrichment_display_sources",[]).append(record)
            self.save(manifest)
            return record

    # 科学子进程通过此公开入口发布新A05展示修订；不能覆盖旧运行或改变统计。
    def publish_enrichment_display(self, sid, expected_a05, inputs, config, summary, tables, figures_builder, reason, anomalies):
        with write_lock(self.root):
            manifest = self.load(sid)
            require(manifest["current"].get("A05") == expected_a05 and self.active(manifest, expected_a05), "A05版本已改变，请刷新")
            run = self._begin(manifest, "A05", inputs, config, reason)
            figures = figures_builder(self.location(sid)/"runs/A05"/run["run_id"])
            result = self._finish(manifest, run["run_id"], summary, tables, anomalies, "success" if any(tables[g+"_significant"] for g in ("bp","cc","mf","kegg")) else "empty", sources=list(inputs.values()), figures=figures)
            self.save(manifest)
            return result


# 只依据已保存范围与应用记录判断图表能否展示，不改变科学结果或模块审批。
def kegg_display_status(meta, decision, run_id, historical=False, busy=False):
    if not meta.get("exclusions_confirmed"):
        return {"kegg_ready":False,"kegg_reason_zh":"请先确认排除清单，应用完成后再显示KEGG图和两张表。"}
    pending = bool(decision and decision.get("a05_run")==run_id and decision.get("decision_id")!=meta.get("decision_id"))
    if not historical and (busy or pending):
        return {"kegg_ready":False,"kegg_reason_zh":"排除清单正在应用或尚未成功应用，暂不显示旧KEGG图表；请查看后台任务，失败时重试。"}
    return {"kegg_ready":True,"kegg_reason_zh":""}


# 只读界面绑定当前运行、人工确认及同源图；任务成功不等于A05复核通过。
def display_context(workflow, manifest, run, result, historical, busy):
    meta = metadata((result or {}).get("tables", {}))
    if not meta:
        return None
    enabled = bool(not historical and not manifest.get("trashed") and not busy and workflow.active(manifest, run["run_id"]))
    decision, _ = workflow.display_decision(manifest, run["parent_runs"]["A03"], meta["base_run"])
    applied = bool(decision and decision["decision_id"] == meta.get("decision_id"))
    return {**kegg_display_status(meta,decision,run["run_id"],historical,busy), "enabled": enabled, "disabled_reason_zh": "" if enabled else "历史及回收站只读；请使用当前有效结果并等待后台任务结束。", "expected_a03": run["parent_runs"]["A03"], "expected_a05": run["run_id"], "expected_decision_id": decision["decision_id"] if decision else None, "exclusions_confirmed": bool(meta.get("exclusions_confirmed")), "layout_confirmed": bool(meta.get("layout_confirmed")), "excluded_ids": meta["excluded_ids"], "missing_translations": meta["missing_translations"], "catalog": result["tables"]["kegg_catalog"], "retained_count": meta["retained_count"], "excluded_count": meta["excluded_count"], "significant_count": meta["significant_count"], "latest": {"reviewer": decision["reviewer"], "note_zh": decision["note"], "created_at": decision["created_at"], "applied": applied, "status_zh": "确认已应用，A05结果仍须独立复核" if applied else "确认已保存但尚未应用，请查看后台任务并重试"} if decision else None}
