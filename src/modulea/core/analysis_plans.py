"""新方案草稿的Workflow公开入口；只追加版本，不切换运行、不批准或计算。"""

from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock
from science_modules.analysis_protocol import VERSION, checked_plan, compile_plan
from .automatic_experience import AutomaticExperienceWorkflow


class AnalysisPlanConflict(ContractError):
    """方案草稿已更新或提交编号被用于不同内容。"""


class AnalysisPlanWorkflow(AutomaticExperienceWorkflow):
    """旧研究继承原行为；只有显式新方案登记支持草稿写入。"""

    def publish_analysis_plan_a01(self, study_id, payload):
        """科学子进程显式发布绑定方案的A01；不自动批准或开始下游。"""
        from science_modules.a01.plan_flow import publish
        return publish(self, study_id, payload)

    def acquire_analysis_plan_a01_sources(self, study_id, payload, *, progress=None):
        """科学子进程显式采集方案来源，只暂存原件，不批准或启动下游。"""
        from science_modules.a01.plan_flow import acquire_sources
        return acquire_sources(self, study_id, payload, progress=progress)

    def fetch_analysis_plan_a04_network(self, targets, plan, *, opener=None):
        """按已编译方案请求STRING；只返回来源包，不写研究、不启动任务。"""
        from science_modules.a04.plan_flow import fetch
        return fetch(targets, plan, opener=opener)

    def evaluate_analysis_plan_a04_network(self, targets, bundle, plan):
        """用同一方案复算A04网络，供发布前指纹校验与后续任务接入。"""
        from science_modules.a04.plan_flow import evaluate
        return evaluate(targets, bundle, plan)

    def _analysis_plan_records(self, manifest):
        """逐件核验本研究索引，不从任意目录猜测最新草稿。"""
        root = self.location(manifest["study_id"])
        records = []
        for reference in manifest.get("analysis_plan_records", []):
            record = read_json(verified_file(root, reference))
            require(record.get("study_id") == manifest["study_id"] and record.get("schema_version") == VERSION,
                    "方案草稿归属或版本不一致")
            safe_id(record.get("plan_id"), "plan")
            checked_plan(record["plan"])
            records.append(record)
        return records

    def analysis_plan_info(self, study_id):
        """只读呈现草稿能力；不初始化文件、不激活方案或调度任务。"""
        manifest = self.load(study_id)
        a00 = manifest["current"].get("A00")
        intake = (self.result(manifest, a00) or {}).get("summary", {}) if a00 else {}
        enabled = intake.get("analysis_plan_profile") == VERSION
        records = self._analysis_plan_records(manifest) if enabled else []
        latest = records[-1] if records else None
        current = latest if latest and latest["expected_a00"] == a00 else None
        return {"supported": enabled, "expected_a00": a00,
                "expected_draft_id": latest["plan_id"] if latest else "", "draft": current,
                "history_count": len(records), "execution_available": False,
                "message_zh": "方案修改仅保存新草稿，不影响正在执行的批次；全流程执行接入尚未完成。" if enabled else "历史固定流程保持；不向旧研究追加新自动方案。"}

    def save_analysis_plan_draft(self, study_id, payload):
        """同编号重试幂等，版本冲突拒绝；不改变current、runs、reviews及活动方案。"""
        fields = {"request_id", "expected_a00", "expected_draft_id", "specification", "author", "note"}
        require(isinstance(payload, dict) and set(payload) == fields, "方案草稿字段不完整或含不支持选项")
        safe_id(payload["request_id"], "planreq")
        safe_id(payload["expected_a00"], "run")
        if payload["expected_draft_id"]:
            safe_id(payload["expected_draft_id"], "plan")
        require(isinstance(payload["expected_draft_id"], str), "草稿版本格式不合法")
        require(isinstance(payload["author"], str) and 0 < len(payload["author"].strip()) <= 2000,
                "请填写方案登记人")
        require(isinstance(payload["note"], str) and len(payload["note"]) <= 2000, "方案说明过长或格式不合法")
        plan = compile_plan(payload["specification"])
        request_hash = fingerprint({key: (plan if key == "specification" else value) for key, value in payload.items()})
        with write_lock(self.root):
            manifest = self.load(study_id)
            require(not manifest.get("trashed"), "回收站研究只读，不能保存方案草稿")
            if manifest["current"].get("A00") != payload["expected_a00"]:
                raise AnalysisPlanConflict("研究登记已更新，请刷新后重新保存方案")
            intake = self.result(manifest, payload["expected_a00"])["summary"]
            require(intake.get("analysis_plan_profile") == VERSION, "历史固定研究不支持追加新自动方案")
            records = self._analysis_plan_records(manifest)
            for old in records:
                if old["request_id"] == payload["request_id"]:
                    if old["request_hash"] != request_hash:
                        raise AnalysisPlanConflict("方案提交编号已用于其他内容，请刷新后重试")
                    return {"draft": old, "created": False, "execution_available": False}
            expected = records[-1]["plan_id"] if records else ""
            if expected != payload["expected_draft_id"]:
                raise AnalysisPlanConflict("方案草稿已更新，请刷新后重新保存")
            record = {"schema_version": VERSION, "study_id": study_id, "plan_id": new_id("plan"),
                      "expected_a00": payload["expected_a00"], "parent_draft_id": expected,
                      "request_id": payload["request_id"], "request_hash": request_hash,
                      "created_at": now(), "author": payload["author"].strip(), "note": payload["note"],
                      "state": "draft", "plan": plan, "applies_to_running_batch": False}
            root = self.location(study_id)
            folder = within(root, "decisions/analysis_plans")
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (record["plan_id"] + ".json")
            write_json(target, record)
            manifest.setdefault("analysis_plan_records", []).append(file_record(root, target, "analysis_plan_draft"))
            self.save(manifest)
            return {"draft": record, "created": True, "execution_available": False}
