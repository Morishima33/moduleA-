"""视图组装：把科学内核的状态和已归档结果，整理为前端直接使用的 JSON。

所有状态都来自 Workflow.view()（唯一状态来源）；这里只做读取、翻译和排版，不做科学计算。
字段说明见 src/modulea/api/AGENTS.md（前端接口契约）。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from ..core import modules as registry
from ..core.source_catalog import source_intro
from ..core.source_uploads import context as upload_context
from ..core.kernel import ContractError, Kernel, read_json, verified_file
from ..core.identity_workflow import plan_view
from ..core.enrichment_workflow import display_context
from ..core.docking_workflow import candidate_context
from ..core.two_pass_workflow import selection_context, preparation_context
from ..core.status import LABELS, map_state, unavailable
from ..presenters import present
from ..tasks.manager import TaskManager
from .errors import ApiError, from_contract, not_found

# 当前KEGG范围未确认或未应用时，专属展示不发送旧图和排名；原归档仍可追溯。
def hide_pending_kegg(special, info):
    if info and not info["kegg_ready"]:
        special.get("enrichment_graphs",{}).pop("kegg",None)
        for key in ("kegg_p_top10","kegg_count_top10"):
            special.get("enrichment_display_tables",{}).pop(key,None)


# 来源规则确认已独立归档后，当前页不再显示旧的“来源未定”提示。
def apply_candidate_context(parts,info):
    if not info or not info.get("data"):
        return
    parts["focus"]=[r for r in parts["focus"] if r["title_zh"]!="对接候选来源待确认"]
    dual=parts["special"].get("ppi_dual")
    if dual:
        dual["network_note_zh"]=dual["network_note_zh"].replace("对接候选另行确认。","对接候选按已归档A/B两梯队使用；结构质控另行核查。")

PREUPLOAD_PROFILES = ("A00.preupload.1", "A00.preupload.2")
PURPOSE_BANNERS = {
    "workflow_test": "流程测试：本研究结果不作为正式研究结论",
}
NEXT_PRIORITY = ["review", "returned", "waiting", "failed", "hold", "incomplete", "stale", "ready"]
NEXT_TEXT = {
    "review": "请复核 {m}",
    "returned": "{m} 已退回，请按意见修改",
    "waiting": "{m} 等待资料或待决事项",
    "failed": "{m} 执行失败，请查看原因后重试",
    "hold": "{m} 暂存待定，请完成复核",
    "incomplete": "{m} 尚未完整提交，请检查后台任务",
    "stale": "{m} 已失效，需要用新的上游重新生成",
    "ready": "{m} 可以开始",
}
INLINE_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class Views:
    def __init__(self, kernel: Kernel, tasks: TaskManager):
        self.kernel = kernel
        self.tasks = tasks

    # ------------------------------------------------------------------ 基础读取
    def _snapshot(self, study_id: str):
        """读取一项研究的完整状态；归档核验失败时返回 (None, 错误说明)。"""
        workflow = self.kernel.display_workflow()
        try:
            return workflow, workflow.view(study_id), None
        except ContractError as error:
            return workflow, None, str(error)
        except FileNotFoundError:
            raise not_found("研究 " + study_id)

    def _manifest(self, study_id: str) -> dict:
        try:
            return self.kernel.workflow().load(study_id)
        except (ContractError, FileNotFoundError):
            raise not_found("研究 " + study_id)

    def _intake(self, study_id: str, manifest: dict) -> dict:
        """读取当前登记原文（用于研究卡片；归档未就绪时也能显示名称）。"""
        run_id = manifest.get("current", {}).get("A00")
        path = self.kernel.settings.studies_dir / study_id / "intake" / f"{run_id}.json"
        try:
            return read_json(path)
        except Exception:
            return {}

    @staticmethod
    def _purpose(view: dict | None, intake: dict | None = None) -> dict | None:
        """研究用途：优先取各模块结果中传播的标记；归档未就绪时回退到登记原文。"""
        values = []
        for item in (view or {}).get("modules", []):
            summary = (item.get("result") or {}).get("summary") or {}
            values.append(summary.get("analysis_purpose") or summary.get("分析用途"))
        values.append((intake or {}).get("analysis_purpose"))
        value = next((v for v in values if v), None)
        if not value:
            return None
        return {"analysis_purpose": value, "banner_zh": PURPOSE_BANNERS.get(value, "研究用途：" + str(value)),
                "severity": "info" if value == "formal_research" else "warning"}

    def _states(self, study_id: str, view: dict | None, error: str | None, trashed: bool = False) -> dict[str, dict]:
        active = self.tasks.active_for(study_id)
        states = {}
        for module_id in registry.ORDER:
            if view is None:
                states[module_id] = unavailable(error or "归档未就绪").as_dict()
                continue
            raw = next(m for m in view["modules"] if m["module_id"] == module_id)
            states[module_id] = map_state(module_id, raw, task_active=bool(active)).as_dict()
            if trashed:
                states[module_id]["can_review"] = False
                states[module_id]["reason_zh"] = "研究在回收站中，只读；恢复后才能复核或运行"
        return states

    # ------------------------------------------------------------------ 首页与研究
    def study_cards(self, trashed: bool = False) -> list[dict]:
        cards = []
        for manifest in self.kernel.workflow().studies(trashed=trashed):
            cards.append(self.study_card(manifest["study_id"]))
        cards.sort(key=lambda c: c["study"]["updated_at"] or "", reverse=True)
        return cards

    def study_card(self, study_id: str, with_states: bool = False) -> dict:
        _, view, error = self._snapshot(study_id)
        manifest = self._manifest(study_id)  # 真实索引（含回收站标记）
        states = self._states(study_id, view, error, bool(manifest.get("trashed")))
        approved = sum(1 for s in states.values() if s["code"] in ("approved", "published"))
        next_step = self._next_step(states)
        card = {
            "study": self._study_info(study_id, manifest),
            "purpose": self._purpose(view, self._intake(study_id, manifest)),
            "archive_ok": view is not None,
            "archive_error_zh": error,
            "progress": {"approved": approved, "total": len(states),
                         "segments": [{"module_id": m, "code": states[m]["code"], "label_zh": states[m]["label_zh"]} for m in registry.ORDER]},
            "next_step": next_step,
            "todo_count": sum(1 for s in states.values() if s["code"] in ("review", "hold", "returned", "waiting", "failed")),
            "active_task": self.tasks.active_for(study_id),
        }
        if with_states:
            card["_states"] = states
        return card

    def _study_info(self, study_id: str, manifest: dict) -> dict:
        intake = self._intake(study_id, manifest)
        herbs = intake.get("herbs")
        if isinstance(herbs, str):
            herbs = [h for h in herbs.replace("，", "、").replace(",", "、").split("、") if h]
        return {
            "study_id": study_id,
            "formula_zh": intake.get("formula"),
            "herbs_zh": herbs or [],
            "disease": {"name_zh": intake.get("disease"), "mesh_term": intake.get("mesh_term"), "mesh_ui": intake.get("mesh_id")},
            "title_zh": " · ".join(x for x in (intake.get("formula"), intake.get("disease")) if x) or study_id,
            "kind": manifest.get("kind"),
            "workflow_profile": manifest.get("workflow_profile"),
            "trashed": bool(manifest.get("trashed", False)),
            "created_at": manifest.get("created_at"),
            "updated_at": manifest.get("updated_at"),
        }

    @staticmethod
    def _next_step(states: dict[str, dict]) -> dict | None:
        for code in NEXT_PRIORITY:
            for module_id in registry.ORDER:
                if states[module_id]["code"] == code:
                    title = registry.SPECS[module_id].title_zh
                    text=NEXT_TEXT[code].format(m=f"{module_id} {title}")
                    if module_id=="A05" and code=="waiting" and states[module_id]["label_zh"]!="等待资料":
                        text=f"{module_id} {title}："+states[module_id]["label_zh"]+"，请查看页面标题下方确认区"
                    return {"module_id": module_id, "code": code, "text_zh": text}
        if all(s["code"] in ("approved", "published") for s in states.values()):
            return {"module_id": None, "code": "done", "text_zh": "全部模块已通过，本研究流程完成"}
        return None

    def study(self, study_id: str) -> dict:
        workflow, view, error = self._snapshot(study_id)
        manifest = self._manifest(study_id)  # 真实索引（含回收站标记）
        states = self._states(study_id, view, error, bool(manifest.get("trashed")))
        nav = []
        for group in registry.GROUP_ORDER:
            items = [{"module_id": m, "title_zh": registry.SPECS[m].title_zh, "sub": registry.SPECS[m].sub,
                      "code": states[m]["code"], "label_zh": states[m]["label_zh"]}
                     for m in registry.ORDER if registry.SPECS[m].group_zh == group]
            if items:
                nav.append({"group_zh": group, "modules": items})
        approved = sum(1 for s in states.values() if s["code"] in ("approved", "published"))
        return {
            "study": self._study_info(study_id, manifest),
            "purpose": self._purpose(view, self._intake(study_id, manifest)),
            "archive_ok": view is not None,
            "archive_error_zh": error,
            "progress": {"approved": approved, "total": len(states)},
            "nav": nav,
            "next_step": self._next_step(states),
            "inbox": [{"module_id": m, "code": states[m]["code"], "label_zh": states[m]["label_zh"],
                       "text_zh": NEXT_TEXT.get(states[m]["code"], "{m}").format(m=f"{m} {registry.SPECS[m].title_zh}")}
                      for m in registry.ORDER if states[m]["code"] in ("review", "hold", "returned", "waiting", "failed")],
            "active_tasks": self.tasks.list(study_id, active_only=True),
            "management": {"expected_action_id": self._last_action(self.kernel.workflow(), study_id, manifest)},
        }

    def _last_action(self, workflow, study_id: str, manifest: dict) -> str | None:
        events = manifest.get("management_events") or []
        if not events:
            return None
        try:
            return read_json(verified_file(workflow.location(study_id), events[-1]))["action_id"]
        except Exception:
            return None

    def inbox(self) -> list[dict]:
        items = []
        for manifest in self.kernel.workflow().studies(trashed=False):
            card = self.study_card(manifest["study_id"], with_states=True)
            states = card.pop("_states")
            for m in registry.ORDER:
                if states[m]["code"] in ("review", "hold", "returned", "waiting", "failed"):
                    items.append({"study_id": card["study"]["study_id"], "study_title_zh": card["study"]["title_zh"], "module_id": m,
                                  "code": states[m]["code"], "label_zh": states[m]["label_zh"],
                                  "text_zh": NEXT_TEXT[states[m]["code"]].format(m=f"{m} {registry.SPECS[m].title_zh}")})
        return items

    # ------------------------------------------------------------------ 模块视图
    def module(self, study_id: str, module_id: str, run_id: str | None = None) -> dict:
        if module_id not in registry.SPECS:
            raise not_found("模块 " + module_id)
        workflow, view, error = self._snapshot(study_id)
        if view is None:
            raise ApiError(503, "ARCHIVE_UNAVAILABLE", "研究归档未通过指纹核验，暂不能显示：" + str(error), retryable=True)
        manifest = view["manifest"]
        real = self._manifest(study_id)
        states = self._states(study_id, view, error, bool(real.get("trashed")))
        raw = next(m for m in view["modules"] if m["module_id"] == module_id)
        spec = registry.SPECS[module_id]

        # 查看历史版本：只读，不提供复核
        historical = bool(run_id and run_id != manifest["current"].get(module_id))
        if historical:
            if run_id not in manifest["runs"] or workflow.run(manifest, run_id)["module_id"] != module_id:
                raise not_found("运行 " + run_id)
            run = workflow.run(manifest, run_id)
            result = workflow.result(manifest, run_id)
            review = workflow.latest_review(manifest, result["artifact_id"]) if result else None
        else:
            run, result, review = raw["run"], raw["result"], raw["review"]

        state = states[module_id]
        results = {m["module_id"]: m["result"] for m in view["modules"] if m.get("result")}
        ctx = {"workflow_profile": manifest.get("workflow_profile"), "state_code": state["code"], "results": results, "study_id": study_id}
        parts = present(module_id, result, ctx) if result else {"kpis": [], "flow": [], "flow_note_zh": "", "focus": [], "params": [], "table": None, "special": {}}

        history = self.runs(study_id, module_id, workflow=workflow, manifest=manifest)
        files = self._files(run, result)
        self._link_report_files(parts, files, result)
        dual = parts.get("special", {}).get("ppi_dual")
        network = ((result or {}).get("tables") or {}).get("degree_network")
        if dual and network:
            network = network[0]
            record = {k: network["png_" + k] for k in ("path", "bytes", "sha256")}
            key = next((f["key"] for f in files if f["path"] == record["path"] and f["sha256"] == record["sha256"]), None)
            if key:
                dual["network"] = {"url": f"/api/v1/studies/{study_id}/files/{key}?inline=1", "caption_zh": network["caption_zh"]}
        # A05图片只链接本运行索引中的指纹文件，历史不会借用当前新图。
        display_figures = ((result or {}).get("tables") or {}).get("display_figures") or []
        if display_figures:
            parts["special"]["enrichment_graphs"] = {}
            for row in display_figures:
                key = next((f["key"] for f in files if f["path"] == row["png_path"] and f["sha256"] == row["png_sha256"]),None)
                if key:
                    parts["special"]["enrichment_graphs"][row["group"]] = {"url":f"/api/v1/studies/{study_id}/files/{key}?inline=1","caption_zh":"GO三类各前八；中英文名称，柱长与深浅表示Count。" if row["group"]=="go" else "KEGG统计显著性前十五；横轴RichFactor，面积Count，颜色为−log10(BH校正后P值)。"}
        enrichment_info = display_context(workflow, real, run, result, historical, bool(self.tasks.active_for(study_id))) if module_id == "A05" else None
        hide_pending_kegg(parts["special"],enrichment_info)
        candidates_info = candidate_context(workflow,real,historical,bool(self.tasks.active_for(study_id))) if module_id in ("A04","A06_PREP","A06") else None
        if module_id == "A04":
            apply_candidate_context(parts,candidates_info)
        a03_id = real.get("current", {}).get("A03", "")
        ppi_enabled = bool(module_id == "A04" and a03_id and not historical and not real.get("trashed") and workflow.active(real, a03_id) and workflow.approved(real, a03_id) and not self.tasks.active_for(study_id))
        if run:
            parts["params"] = parts["params"] + self._config_params(run, parts["params"])
        return {
            "module": {"module_id": module_id, "title_zh": spec.title_zh, "group_zh": spec.group_zh, "purpose_zh": source_intro(module_id, real, result) + ("STRING人类功能关联网络；两分支独立两轮；Degree图展示第二轮候选，Degree表展示第一轮前十，BC＋CC表展示第二轮前十五。" if module_id == "A04" and result and result.get("summary", {}).get("selection_version") == "A04.dual.3" else ("STRING人类功能关联网络；Degree与BC＋CC两分支独立进行两轮筛选，Degree图表显示第一轮前十，BC＋CC表显示第二轮前十五。" if module_id == "A04" and result and result.get("summary", {}).get("selection_version") == "A04.dual.2" else ("STRING人类功能关联网络；双分支独立两轮，显示第二轮排名。" if module_id == "A04" and result and result.get("summary", {}).get("selection_version") == "A04.dual.1" else spec.purpose_zh))),
                       "sub": spec.sub, "depends_on": list(spec.depends_on)},
            "state": state if not historical else {**state, "code": "history", "label_zh": "历史版本（只读）", "can_review": False},
            "purpose": self._purpose(view),
            "run": self._run_info(workflow, manifest, run, result, history) if run else None,
            "outcome": (result or {}).get("outcome"),
            **parts,
            "review": self._review_info(workflow, real, module_id, state, result, review, historical),
            "downstream": {"note_zh": registry.downstream_note(module_id),
                           "modules": [{"module_id": m, "title_zh": registry.SPECS[m].title_zh, "code": states[m]["code"], "label_zh": states[m]["label_zh"]}
                                       for m in registry.dependents(module_id)]},
            "trace": self._trace(study_id, run, result, review),
            "files": files,
            "tables": self._table_index(result),
            "history": history,
            "tasks": self.tasks.list(study_id, active_only=True),
            "historical": historical,
            "ppi_run": {"enabled": ppi_enabled, "disabled_reason_zh": "" if ppi_enabled else "请先通过当前A03，并等待本研究活动任务结束；历史及回收站只读。", "expected_a03": a03_id, "expected_a04": real.get("current", {}).get("A04", "")} if module_id == "A04" and not historical else None,
            "identity_plan": plan_view(workflow, real, run, result, ppi_enabled and bool(run) and workflow.active(real, run["run_id"]), historical) if module_id == "A04" else None,
            "enrichment_display": enrichment_info,
            "docking_candidates": candidates_info,
            "compound_selection": selection_context(workflow,real,historical,bool(self.tasks.active_for(study_id))) if module_id=="A03_SELECT" else None,
            "docking_preparation": preparation_context(workflow,real,historical,bool(self.tasks.active_for(study_id))) if module_id=="A06_PREP" else None,
            "source_uploads": upload_context(workflow, real, module_id, result, historical, bool(self.tasks.active_for(study_id))) if not historical else None,
        }

    @staticmethod
    def _run_info(workflow, manifest, run, result, history) -> dict:
        order = next((h["order_zh"] for h in history if h["run_id"] == run["run_id"]), None)
        return {"run_id": run["run_id"], "artifact_id": run["artifact_id"], "order_zh": order, "created_at": run.get("created_at"),
                "reason_zh": run.get("reason"), "parent_runs": run.get("parent_runs", {}),
                "is_current": manifest["current"].get(run["module_id"]) == run["run_id"],
                "is_active": workflow.active(manifest, run["run_id"]),
                "finished_at": (result or {}).get("created_at")}

    @staticmethod
    def _config_params(run: dict, existing: list[dict]) -> list[dict]:
        """把 run.json 中记录的简单配置项列为参数（来源：运行记录）。"""
        seen = {p["label_zh"] for p in existing}
        params = []
        config=run.get("config") or {}
        display_rule=config.get("display_rule")
        if display_rule:
            for key,label in (("go_graph","GO图各类名额"),("go_table","GO表各类名额"),("kegg_graph","KEGG图名额"),("kegg_tables","KEGG两表各名额")):
                params.append({"label_zh":label,"value":str(display_rule[key]),"origin":"run_config"})
        for key, value in config.items():
            if display_rule and key in ("show_GO","show_KEGG"):
                continue  # 这是冻结统计基线的旧展示字段，当前名额读取版本化display_rule。
            if isinstance(value, (str, int, float, bool)) and key not in seen and len(params) < 30:
                params.append({"label_zh": key, "value": value if isinstance(value, str) else str(value), "origin": "run_config"})
        return params

    def _review_info(self, workflow, manifest, module_id, state, result, review, historical) -> dict:
        reviews = self._reviews_for(workflow, manifest, result["artifact_id"]) if result else []
        blocked = state.get("handoff_blocked")
        can = bool(state.get("can_review")) and not historical and not manifest.get("trashed") and bool(result) and result.get("outcome") != "failed"
        batch = None
        if module_id in ("A01", "A02") and manifest.get("workflow_profile") in PREUPLOAD_PROFILES:
            batch = "A02" if module_id == "A01" else "A01"
        return {
            "current": ({k: review.get(k) for k in ("review_id", "decision", "reviewer", "note", "created_at", "batch")} if review else None),
            "history": reviews,
            "can_review": can,
            "allowed_decisions": [d for d in ("approved", "rejected", "pending") if not (d == "approved" and blocked)],
            "blocked_reason_zh": state.get("reason_zh") if blocked else None,
            "expected_review_id": review["review_id"] if review else None,
            "run_id": result["run_id"] if result else None,
            "batch_with": batch,
            "continue": {"available": can and not blocked and module_id != "A07",
                         "note_zh": ("A07 是最后一步，通过后两份正式报告即发布，没有下一关口。" if module_id == "A07"
                                     else "仍有待处理事项，暂不能通过，只能保存决定。" if blocked
                                     else "通过后将按既定规则在后台自动生成下一批结果，并停在下一个人工关口；程序不会代签任何模块。")},
            "already_approved": state.get("code") in ("approved", "published"),
        }

    @staticmethod
    def _reviews_for(workflow, manifest, artifact_id) -> list[dict]:
        out = []
        root = workflow.location(manifest["study_id"])
        for record in manifest.get("reviews", []):
            try:
                item = read_json(verified_file(root, record))
            except Exception:
                continue
            if item.get("artifact_id") == artifact_id:
                out.append({k: item.get(k) for k in ("review_id", "decision", "reviewer", "note", "created_at", "previous_review_id", "batch")})
        return out

    @staticmethod
    def _trace(study_id, run, result, review) -> list[dict]:
        if not run:
            return [{"label_zh": "研究编号", "value": study_id}]
        rows = [("研究编号", study_id), ("运行编号", run.get("run_id")), ("产物编号", run.get("artifact_id")),
                ("复核编号", review.get("review_id") if review else "待复核"), ("输入指纹", run.get("input_hash")),
                ("配置指纹", run.get("config_hash")), ("代码版本", run.get("code_version")), ("环境版本", run.get("environment_version")),
                ("开始时间", run.get("created_at")), ("完成时间", (result or {}).get("created_at"))]
        for module, parent in (run.get("parent_runs") or {}).items():
            rows.append(("上游 " + module, parent))
        return [{"label_zh": k, "value": v} for k, v in rows if v]

    # ------------------------------------------------------------------ 历史、表格、文件
    def runs(self, study_id: str, module_id: str, workflow=None, manifest=None) -> list[dict]:
        workflow = workflow or self.kernel.workflow()
        manifest = manifest or self._manifest(study_id)
        items = []
        for run_id in manifest["runs"]:
            try:
                run = workflow.run(manifest, run_id)
            except Exception:
                continue
            if run["module_id"] != module_id:
                continue
            outcome, decision = None, None
            record = manifest["runs"][run_id].get("result_file")
            if record:
                # 历史列表只核验 result.json 本身，不逐个核验全部附件，保证列表打开速度
                try:
                    result = read_json(verified_file(workflow.location(study_id), record))
                    outcome = result["outcome"]
                    latest = workflow.latest_review(manifest, result["artifact_id"])
                    decision = latest["decision"] if latest else None
                except Exception:
                    outcome = "unavailable"
            items.append({"run_id": run_id, "created_at": run.get("created_at"), "reason_zh": run.get("reason"), "outcome": outcome,
                          "review_decision": decision, "is_current": manifest["current"].get(module_id) == run_id})
        items.sort(key=lambda r: r["created_at"] or "")
        for index, item in enumerate(items, start=1):
            item["order_zh"] = f"第 {index} 次运行"
        return list(reversed(items))

    @staticmethod
    def _table_index(result) -> list[dict]:
        out = []
        for name, rows in ((result or {}).get("tables") or {}).items():
            if isinstance(rows, list):
                columns = list(dict.fromkeys(k for row in rows[:200] for k in row))
                out.append({"name": name, "kind": "rows", "row_count": len(rows), "columns": columns})
            else:
                out.append({"name": name, "kind": "object", "row_count": None, "columns": []})
        return out

    def table(self, study_id: str, module_id: str, name: str, run_id: str | None, page: int, size: int, q: str) -> dict:
        workflow = self.kernel.workflow()
        manifest = self._manifest(study_id)
        run_id = run_id or manifest["current"].get(module_id)
        if not run_id or run_id not in manifest["runs"]:
            raise not_found("运行")
        try:
            result = workflow.result(manifest, run_id)
        except ContractError as error:
            raise from_contract(str(error))
        if not result or workflow.run(manifest, run_id)["module_id"] != module_id:
            raise not_found("结果")
        rows = (result.get("tables") or {}).get(name)
        if rows is None:
            raise not_found("表格 " + name)
        if isinstance(rows, dict):
            return {"name": name, "kind": "object", "data": rows}
        if q:
            needle = q.lower()
            rows = [r for r in rows if any(needle in str(v).lower() for v in r.values())]
        size = max(1, min(size, 500))
        page = max(1, page)
        columns = list(dict.fromkeys(k for row in rows[:200] for k in row))
        return {"name": name, "kind": "rows", "columns": columns, "total": len(rows), "page": page, "size": size,
                "items": rows[(page - 1) * size: page * size]}

    @staticmethod
    def _files(run, result) -> list[dict]:
        """结果索引中的全部归档文件。下载键为 <run_id>.<序号>，只能指向索引内文件。"""
        if not result:
            return []
        out = []
        for index, record in enumerate(result.get("files") or []):
            path = record.get("path", "")
            suffix = Path(path).suffix.lower()
            out.append({"key": f"{result['run_id']}.{index}", "role": record.get("role"), "name": Path(path).name, "path": path,
                        "bytes": record.get("bytes"), "sha256": record.get("sha256"), "inline": suffix in INLINE_TYPES})
        return out

    @staticmethod
    def _link_report_files(parts: dict, files: list[dict], result: dict | None) -> None:
        """A07 的两份 Word：优先用结果文件索引的下载键；报告登记在 report_files 表中时用 <run_id>.r<行号>。"""
        by_path = {f["path"]: f["key"] for f in files}
        for item in parts.get("special", {}).get("report_files", []) or []:
            key = by_path.get(item.get("path"))
            if key is None and result is not None and item.get("row") is not None:
                key = f"{result['run_id']}.r{item['row']}"
            item["key"] = key

    def file(self, study_id: str, key: str) -> tuple[Path, str, str]:
        run_id, _, index = key.rpartition(".")
        from_report_table = index.startswith("r") and index[1:].isdigit()
        if not run_id.startswith("run_") or not (index.isdigit() or from_report_table):
            raise ApiError(400, "BAD_REQUEST", "文件编号格式不正确")
        workflow = self.kernel.workflow()
        manifest = self._manifest(study_id)
        if run_id not in manifest["runs"]:
            raise not_found("文件")
        try:
            result = workflow.result(manifest, run_id)
        except ContractError as error:
            raise from_contract(str(error))
        if from_report_table:
            # A07 报告登记在 report_files 表中：同样要求含路径、大小和指纹，并逐字节核验
            records = ((result or {}).get("tables") or {}).get("report_files") or []
            position = int(index[1:])
        else:
            records = (result or {}).get("files") or []
            position = int(index)
        if position >= len(records) or not all(k in records[position] for k in ("path", "sha256", "bytes")):
            raise not_found("文件")
        record = records[position]
        try:
            path = verified_file(workflow.location(study_id), record)
        except ContractError as error:
            raise from_contract(str(error))
        suffix = Path(record["path"]).suffix.lower()
        mime = INLINE_TYPES.get(suffix) or mimetypes.guess_type(record["path"])[0] or "application/octet-stream"
        return Path(path), Path(record["path"]).name, mime


__all__ = ["Views", "LABELS", "PREUPLOAD_PROFILES"]
