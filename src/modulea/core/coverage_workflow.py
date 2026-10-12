"""A06扩大覆盖的唯一工作流：技术核查、草案保存、采用确认和结果复核分别留存。"""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
from contracts import require
from storage import write_lock, write_json, read_json, verified_file, file_record, now
from science_modules.a06.plan_adapter import source_context
from .quality_workflow import QualityWorkflow


class CoverageWorkflow(QualityWorkflow):
    """研究版本、锁与状态沿用原Workflow；集中确认不启动批量评分。"""

    def coverage_binding(self, sid, payload, manifest=None, check_base=True):
        """校验来源、人工方案与原件，拒绝跨研究、过期任务及回收站写入。"""
        manifest = manifest or self.load(sid)
        require(not manifest.get("trashed"), "回收站研究只读")
        context = source_context(self, sid, manifest)
        plan, plan_record = self.latest_two_pass(manifest, context)
        source = self.current_source_review(manifest, context)
        require(plan and source, "请先完成来源核查和原始完整方案确认")
        require(
            payload.get("expected_source") == context["source_key"]
            and payload.get("expected_plan_id") == plan["plan_id"]
            and payload.get("expected_source_review_id") == source["review_id"],
            "来源、方案或原件已更新，请刷新",
        )
        require(
            self.current_two_pass_draft(manifest, context, plan) is None,
            "有未确认原始方案草案，先核对后再执行",
        )
        if check_base:
            require(
                payload.get("expected_base_run") == manifest["current"].get("A06_PREP"),
                "当前质控版本已改变，请刷新",
            )
        return manifest, context, plan, plan_record, source

    def authorize_coverage(self, sid, payload):
        """只登记用户已明确授权的技术补救，不把授权登记为研究批准。"""
        require(
            set(payload)
            == {
                "expected_source",
                "expected_plan_id",
                "expected_source_review_id",
                "expected_base_run",
                "authorization_zh",
            },
            "扩大覆盖授权字段非法",
        )
        require(
            isinstance(payload["authorization_zh"], str)
            and payload["authorization_zh"].strip(),
            "缺少用户扩大覆盖技术核查授权",
        )
        with write_lock(self.root):
            manifest, *_ = self.coverage_binding(sid, payload)
            data = {
                "schema_version": "A06.coverage.authorization.2",
                "study_id": sid,
                "authorization_id": "coverage_" + uuid4().hex,
                "created_at": now(),
                **payload,
                "batch_docking_allowed": False,
                "approval": None,
            }
            path = (
                self.location(sid)
                / "decisions/A06_coverage_authorization"
                / (data["authorization_id"] + ".json")
            )
            write_json(path, data)
            manifest.setdefault("coverage_authorization_records", []).append(
                file_record(self.location(sid), path, "coverage_authorization")
            )
            self.save(manifest)
            return data

    def coverage_authorization(self, sid, payload, check_base=True):
        """私有任务只能读取当前研究登记授权，失败重试仍绑定原请求。"""
        manifest, context, plan, record, source = self.coverage_binding(
            sid, payload, check_base=check_base
        )
        matches = [
            (read_json(verified_file(self.location(sid), r)), r)
            for r in manifest.get("coverage_authorization_records", [])
            if read_json(verified_file(self.location(sid), r))["authorization_id"]
            == payload.get("authorization_id")
        ]
        require(len(matches) == 1, "技术补救授权未登记在本研究")
        authorization, auth_record = matches[0]
        require(
            authorization["study_id"] == sid
            and authorization["batch_docking_allowed"] is False
            and all(
                authorization.get(k) == payload.get(k)
                for k in (
                    "expected_source",
                    "expected_plan_id",
                    "expected_source_review_id",
                    "expected_base_run",
                )
            ),
            "补救任务与授权研究或版本不符",
        )
        return context, plan, record, source, auth_record

    def finish_coverage(self, sid, run_id, payload, summary, tables, files):
        """慢任务发布前再核对授权、上游和当前运行，禁止回写旧窗口。"""
        with write_lock(self.root):
            self.coverage_authorization(sid, payload, check_base=False)
            manifest = self.load(sid)
            require(
                manifest["current"]["A06_PREP"] == run_id,
                "当前准备运行已更新，旧任务不能发布",
            )
            result = self._finish(
                manifest, run_id, summary, tables, [], "success", attachments=files
            )
            self.save(manifest)
            return result

    def current_coverage(self, manifest):
        """只展示当前有效资料；旧规则或过期归档不冒充本轮可确认结果。"""
        rid = manifest["current"].get("A06_PREP")
        if not rid:
            return None
        run = self.run(manifest, rid)
        if run.get("config", {}).get("version") not in (
            "A06.coverage.execution.4",
            "A06.coverage.confirmed.4",
        ):
            return None
        result = self.result(manifest, rid)
        if not result or not result.get("tables", {}).get("coverage_packet"):
            return None
        cache = getattr(self, "_view_cache", None)
        key = (manifest["study_id"], rid)
        if cache is not None and key in cache.get("coverage_packets", {}):
            return cache["coverage_packets"][key]
        context = source_context(self, manifest["study_id"], manifest)
        packet = read_json(
            verified_file(
                self.location(manifest["study_id"]),
                result["tables"]["coverage_packet"][0],
            )
        )
        plan, _ = self.latest_two_pass(manifest, context)
        source = self.current_source_review(manifest, context)
        if (
            not plan
            or not source
            or packet["source_key"] != context["source_key"]
            or (
                packet["plan_id"] != plan["plan_id"]
                or packet["source_review_id"] != source["review_id"]
            )
        ):
            return None
        require(self.active(manifest, rid), "本轮补救证据已失效")
        for file in packet["files"]:
            verified_file(self.location(manifest["study_id"]), file)
        if cache is not None:
            cache.setdefault("coverage_packets", {})[key] = packet
        return packet

    def coverage_info(self, manifest, busy=False):
        """服务端统一给出同页资格、覆盖数量与草案状态，不让前端推算科学通过。"""
        if manifest.get("trashed"):
            return None
        packet = self.current_coverage(manifest)
        if not packet:
            return None
        records = manifest.get("coverage_selection_records", [])
        latest = None
        if records:
            candidate = read_json(
                verified_file(self.location(manifest["study_id"]), records[-1])
            )
            if (
                candidate["campaign_id"] == packet["campaign_id"]
                and candidate["source_key"] == packet["source_key"]
            ):
                latest = candidate
        rows = []
        selected = set((latest or {}).get("selected_target_ids", []))
        for r in packet["receptors"]:
            chosen = r.get("selected") or {}
            rows.append(
                {
                    k: deepcopy(r[k])
                    for k in (
                        "target_id",
                        "symbol",
                        "candidate_grade",
                        "eligible",
                        "quality_zh",
                        "status_zh",
                        "reason_zh",
                        "pdb_id",
                        "ppi_order",
                        "adopted",
                    )
                }
                | {
                    "rmsd_A": chosen.get("top1_rmsd"),
                    "spec": chosen.get("spec"),
                    "attempts": [
                        {
                            k: deepcopy(a[k])
                            for k in (
                                "round",
                                "spec",
                                "reason_zh",
                                "top1_rmsd",
                                "pocket",
                                "confidence_facts",
                                "environment_audit",
                                "site_coverage",
                            )
                            if k in a
                        }
                        for a in r["attempts"]
                    ],
                    "selected": r["target_id"] in selected,
                }
            )
        return {
            "enabled": not busy,
            "disabled_reason_zh": "请等待当前研究任务结束" if busy else "",
            "expected_run": manifest["current"]["A06_PREP"],
            "campaign_id": packet["campaign_id"],
            "expected_decision_id": latest["decision_id"] if latest else None,
            "expected_source": packet["source_key"],
            "confirmed": bool(packet.get("confirmation")),
            "draft": latest,
            "rows": rows,
            "counts": packet["counts"],
            "batch_docking_allowed": False,
            "conditions": {
                "main_results": self.result(manifest, manifest["current"]["A06_PREP"])[
                    "summary"
                ]["主要结果条件满足"],
                "exploration": self.result(manifest, manifest["current"]["A06_PREP"])[
                    "summary"
                ]["探索可用条件满足"],
                "prepared_pairs": self.result(
                    manifest, manifest["current"]["A06_PREP"]
                )["summary"]["具备准备输入组合数"],
            },
            "note_zh": "只确认本轮结构与可用范围；主要五须至少五个严格受体。未解决项仅阻断对应组合，批量结合能另行授权。",
        }

    @contextmanager
    def coverage_read_scope(self):
        """一次只读核查复用完整校验；退出后清除，写入前重新核对版本。"""
        previous = getattr(self, "_view_cache", None)
        if previous is None:
            self._view_cache = {
                "runs": {},
                "results": {},
                "reviews": {},
                "active": {},
                "approved": {},
            }
        try:
            yield
        finally:
            self._view_cache = previous

    def validate_coverage_selection(self, sid, payload):
        """公开入口的只读核查不重复扫描同批原件，也不跨请求保存缓存。"""
        with self.coverage_read_scope():
            return self._validate_coverage_selection(sid, payload)

    def _validate_coverage_selection(self, sid, payload):
        """核验资格、版本与参数；旧窗口在读取大量证据之前即阻断。"""
        fields = {
            "expected_run",
            "expected_source",
            "campaign_id",
            "expected_decision_id",
            "selected_target_ids",
            "reviewer",
            "note",
            "confirmed",
        }
        require(
            isinstance(payload, dict) and set(payload) == fields,
            "范围字段不完整或含隐藏计算参数",
        )
        require(isinstance(payload["confirmed"], bool), "确认标记须为布尔值")
        manifest = self.load(sid)
        require(not manifest.get("trashed"), "回收站研究只读")
        require(
            payload["expected_run"] == manifest["current"].get("A06_PREP"),
            "质控版本已更新，请刷新",
        )
        info = self.coverage_info(manifest)
        require(
            info
            and all(
                payload[k] == info[k]
                for k in (
                    "expected_run",
                    "expected_source",
                    "campaign_id",
                    "expected_decision_id",
                )
            ),
            "质控、来源或保存版本已更新，请刷新",
        )
        require(not info["confirmed"], "本轮已确认采用；修改须新增技术质控版本")
        ids = payload["selected_target_ids"]
        allowed = {r["target_id"] for r in info["rows"] if r["eligible"]}
        require(
            isinstance(ids, list)
            and all(isinstance(i, str) for i in ids)
            and len(ids) == len(set(ids))
            and set(ids) <= allowed,
            "未解决、重复或未知项目不能确认",
        )
        require(
            all(
                isinstance(payload[k], str) and len(payload[k]) <= 2000
                for k in ("reviewer", "note")
            ),
            "核验人与依据格式非法",
        )
        if payload["confirmed"]:
            require(
                ids and payload["reviewer"].strip() and payload["note"].strip(),
                "请填写核验人、依据并选择可用受体",
            )
        return info

    def save_coverage_selection(self, sid, payload):
        """可保存未完成选择并刷新恢复；确认时同一窗口明确采用，绝不代签结果。"""
        fields = {
            "expected_run",
            "expected_source",
            "campaign_id",
            "expected_decision_id",
            "selected_target_ids",
            "reviewer",
            "note",
            "confirmed",
        }
        require(
            isinstance(payload, dict) and set(payload) == fields,
            "范围请求字段不完整或含隐藏计算参数",
        )
        require(isinstance(payload["confirmed"], bool), "确认标记须明确为布尔值")
        with write_lock(self.root):
            manifest = self.load(sid)
            require(not manifest.get("trashed"), "回收站研究只读")
            require(
                payload["expected_run"] == manifest["current"].get("A06_PREP"),
                "质控版本已更新，请刷新",
            )
            with self.coverage_read_scope():
                info = self.coverage_info(manifest)
                packet = (
                    self.current_coverage(manifest) if payload["confirmed"] else None
                )
            require(
                info
                and all(
                    payload.get(k) == info.get(k)
                    for k in (
                        "expected_run",
                        "expected_source",
                        "campaign_id",
                        "expected_decision_id",
                    )
                ),
                "质控、来源或保存版本已更新，请刷新",
            )
            require(not info["confirmed"], "本轮已确认采用；改变输入须另建质控版本")
            ids = payload["selected_target_ids"]
            eligible_ids = {r["target_id"] for r in info["rows"] if r["eligible"]}
            require(
                isinstance(ids, list)
                and all(isinstance(i, str) for i in ids)
                and len(ids) == len(set(ids))
                and set(ids) <= eligible_ids,
                "未解决、重复或未知项目不能确认采用",
            )
            require(
                all(
                    isinstance(payload[k], str) and len(payload[k]) <= 2000
                    for k in ("reviewer", "note")
                ),
                "核验人与说明格式非法",
            )
            if payload["confirmed"]:
                require(
                    ids and payload["reviewer"].strip() and payload["note"].strip(),
                    "请填写核验人、依据并选择可用受体",
                )
            decision = {
                "schema_version": "A06.coverage.selection.2",
                "study_id": sid,
                "decision_id": "coverage_decision_" + uuid4().hex,
                "created_at": now(),
                "source_key": payload["expected_source"],
                **deepcopy(payload),
            }
            path = (
                self.location(sid)
                / "decisions/A06_coverage_selection"
                / (decision["decision_id"] + ".json")
            )
            write_json(path, decision)
            manifest.setdefault("coverage_selection_records", []).append(
                file_record(self.location(sid), path, "coverage_selection")
            )
            if payload["confirmed"]:
                from science_modules.a06.coverage_flow import confirm_packet, reports

                revised = confirm_packet(packet, decision)
                run = self._begin(
                    manifest,
                    "A06_PREP",
                    {
                        "technical_result": manifest["runs"][payload["expected_run"]][
                            "result_file"
                        ],
                        "coverage_selection": file_record(
                            self.location(sid), path, "coverage_selection"
                        ),
                    },
                    {
                        "version": "A06.coverage.confirmed.4",
                        "batch_docking_allowed": False,
                    },
                    "用户集中确认本轮可用范围；批量结合能仍关闭",
                )
                revised["run_id"] = run["run_id"]
                out = (
                    self.location(sid)
                    / "runs/A06_PREP"
                    / run["run_id"]
                    / "coverage/packet.json"
                )
                write_json(out, revised)
                summary, tables = reports(revised)
                record = file_record(self.location(sid), out, "coverage_packet")
                tables["coverage_packet"] = [record]
                self._finish(
                    manifest,
                    run["run_id"],
                    summary,
                    tables,
                    [],
                    "success",
                    attachments=revised["files"] + [record],
                )
            self.save(manifest)
            return {
                "decision": decision,
                "message_zh": "本轮可用范围已确认；结果仍须独立复核，未启动批量计算"
                if payload["confirmed"]
                else "核查草案已保存，刷新可恢复；尚未确认采用",
            }

    def quality_phase(self, manifest, plan, busy=False):
        """新版覆盖归档显示实际数量，其他版本沿用旧执行状态文字。"""
        packet = self.current_coverage(manifest)
        if packet:
            c = packet["counts"]
            return (
                "本轮技术核查：严格可用"
                + str(c["strict"])
                + "个，探索候选"
                + str(c["exploration"])
                + "个，待补"
                + str(c["unavailable"])
                + "个；"
                + (
                    "已确认采用；未运行批量结合能"
                    if packet.get("confirmation")
                    else "请在集中核查窗口确认采用"
                )
            )
        return super().quality_phase(manifest, plan, busy)
