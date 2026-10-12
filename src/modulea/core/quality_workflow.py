"""A06真实质控授权与版本保护；授权执行与人工结果批准分别留存。"""
from uuid import uuid4
from contracts import require
from storage import write_lock, write_json, read_json, verified_file, file_record, now
from science_modules.a06.plan_adapter import source_context
from .two_pass_workflow import TwoPassWorkflow

STAGES = ["ligand_preparation", "receptor_preparation", "p2rank", "reference_redocking"]


class QualityWorkflow(TwoPassWorkflow):
    """新执行方法仍通过唯一Workflow管理研究、写锁及版本。"""

    def quality_binding(self, sid, payload, manifest=None):
        """每次启动或发布都绑定已确认方案和原件，不接受批量对接授权。"""
        manifest = manifest or self.load(sid)
        context = source_context(self, sid, manifest)
        plan, record = self.latest_two_pass(manifest, context)
        source = self.current_source_review(manifest, context)
        require(plan and source, "请先确认当前完整方案及来源原件")
        require(payload.get("expected_plan_id") == plan["plan_id"]
                and payload.get("expected_source") == context["source_key"]
                and payload.get("expected_source_review_id") == source["review_id"],
                "方案或原件版本已更新，旧质控任务不可执行或发布")
        require(self.current_two_pass_draft(manifest, context, plan) is None,
                "当前有未确认草案，请先完成方案确认")
        require(self.check_two_pass(sid, {
            "expected_source": context["source_key"],
            "expected_source_review_id": source["review_id"], "plan": plan["plan"]
        })["confirmation"]["ready"], "完整方案当前校验未通过")
        return manifest, context, plan, record, source

    def authorize_quality(self, sid, payload):
        """记录用户在对话或页面给出的执行范围，不代签科学结果。"""
        require(set(payload) == {"expected_plan_id", "expected_source",
                "expected_source_review_id", "stages", "authorization_zh"},
                "质控授权字段不完整或包含批量对接参数")
        require(payload["stages"] == STAGES, "本轮仅允许结构准备、口袋预测及参考配体重对接")
        require(isinstance(payload["authorization_zh"], str)
                and payload["authorization_zh"].strip(), "缺少用户执行授权说明")
        with write_lock(self.root):
            manifest, _, _, _, _ = self.quality_binding(sid, payload)
            aid = "quality_" + uuid4().hex
            data = {"schema_version": "A06.quality.authorization.1", "authorization_id": aid,
                    "study_id": sid, "created_at": now(), **payload,
                    "batch_docking_allowed": False, "approval": None}
            path = self.location(sid) / "decisions/A06_quality_authorization" / (aid + ".json")
            write_json(path, data)
            manifest.setdefault("quality_authorization_records", []).append(
                file_record(self.location(sid), path, "quality_authorization"))
            self.save(manifest)
            return data

    def quality_authorization(self, sid, payload):
        """后台只读取研究索引登记的授权，拒绝伪造、跨研究与过期调用。"""
        manifest, context, plan, plan_record, source = self.quality_binding(sid, payload)
        matches = []
        for record in manifest.get("quality_authorization_records", []):
            data = read_json(verified_file(self.location(sid), record))
            if data["authorization_id"] == payload.get("authorization_id"):
                matches.append((data, record))
        require(len(matches) == 1, "质控授权未登记在当前研究")
        authorization, auth_record = matches[0]
        require(authorization["study_id"] == sid and authorization["stages"] == STAGES
                and authorization["batch_docking_allowed"] is False,
                "质控授权范围或研究不符")
        require(all(authorization.get(k) == payload.get(k) for k in (
            "expected_plan_id", "expected_source", "expected_source_review_id")),
            "质控授权与当前任务版本不符")
        return context, plan, plan_record, source, auth_record

    def finish_quality(self, sid, run_id, payload, summary, tables, attachments):
        """发布时在同一写锁内复核授权版本，沿用内核归档且从不代签。"""
        with write_lock(self.root):
            self.quality_authorization(sid, payload)
            manifest = self.load(sid)
            result = self._finish(manifest, run_id, summary, tables, [], "success",
                                  attachments=attachments)
            self.save(manifest)
            return result

    def quality_phase(self, manifest, plan, busy=False):
        """只显示当前方案实际归档的执行情况，不推算模块批准状态。"""
        rid = manifest["current"].get("A06_PREP")
        if not rid or not plan:
            return ""
        run = self.run(manifest, rid)
        if run.get("config", {}).get("version") != "A06.two_pass.execution.1":
            return ""
        actual = read_json(verified_file(self.location(manifest["study_id"]),
                                        run["inputs"]["two_pass_plan"]))
        if actual["plan_id"] != plan["plan_id"]:
            return "此前质控绑定旧方案；当前新方案仍待实际准备与质控"
        result = self.result(manifest, rid)
        if not result:
            return ("真实结构准备与质控进行中；未运行批量结合能" if busy else
                    "本轮质控未完整提交，请查看任务日志；不能用于批量计算")
        summary = result["summary"]
        return ("本轮实际质控已归档：严格通过"
                + str(summary["严格质控通过受体数"]) + "个，待集中核查"
                + str(summary["等待集中核查受体数"]) + "个；未运行批量结合能")
