"""新方案草稿的Workflow公开入口；只追加版本，不切换运行、不批准或计算。"""

from contracts import ContractError, fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock
from science_modules.analysis_protocol import VERSION, checked_plan, compile_plan
from .automatic_experience import AutomaticExperienceWorkflow


A04_SELECTION_VERSION = "A04.plan_selection.1"
A04_SELECTION_REVIEW_VERSION = "A04.plan_selection_review.1"
A06_INPUT_RECORD_VERSION = "A06.plan_preparation_record.1"


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

    def publish_analysis_plan_a04_network(self, study_id, payload):
        """绑定A03、方案和STRING来源，追加A04运行；不自动批准。"""
        from science_modules.a04.plan_flow import publish
        return publish(self, study_id, payload)

    def select_analysis_plan_a04_receptors(self, network_run_id, network_summary, network_tables, plan):
        """按同一方案从A04完整指标表选择受体；不改网络运行。"""
        from science_modules.a04.selection_flow import select_from_network
        return select_from_network(network_run_id, network_summary, network_tables, plan)

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

    def _analysis_plan_selection_records(self, manifest):
        """逐件核验A04受体选择决定；选择记录不是新的科学运行。"""
        root = self.location(manifest["study_id"])
        records = []
        for reference in manifest.get("analysis_plan_selection_records", []):
            record = read_json(verified_file(root, reference))
            require(record.get("study_id") == manifest["study_id"]
                    and record.get("schema_version") == A04_SELECTION_VERSION,
                    "A04选择决定归属或版本不一致")
            safe_id(record.get("selection_id"), "selection")
            safe_id(record.get("expected_a00"), "run")
            safe_id(record.get("expected_a04"), "run")
            safe_id(record.get("plan_id"), "plan")
            require(isinstance(record.get("selection"), dict), "A04选择决定内容缺失")
            records.append(record)
        return records

    def _analysis_plan_selection_reviews(self, manifest):
        """审核单独追加，不借用A04科学运行的reviews替代选择审核。"""
        root = self.location(manifest["study_id"])
        records = []
        for reference in manifest.get("analysis_plan_selection_reviews", []):
            record = read_json(verified_file(root, reference))
            require(record.get("schema_version") == A04_SELECTION_REVIEW_VERSION
                    and record.get("study_id") == manifest["study_id"],
                    "A04选择复核归属或版本不一致")
            safe_id(record.get("review_id"), "selectionreview")
            safe_id(record.get("selection_id"), "selection")
            require(record.get("decision") in ("approved", "rejected", "pending"),
                    "A04选择复核决定不合法")
            records.append(record)
        return records

    def _analysis_plan_a06_input_records(self, manifest):
        """逐件核验新版准备输入索引，历史记录不随当前指针覆盖。"""
        root = self.location(manifest["study_id"])
        records = []
        for reference in manifest.get("analysis_plan_a06_input_records", []):
            record = read_json(verified_file(root, reference))
            require(record.get("schema_version") == A06_INPUT_RECORD_VERSION
                    and record.get("study_id") == manifest["study_id"],
                    "A06准备输入归属或版本不一致")
            safe_id(record.get("input_id"), "input")
            require(isinstance(record.get("packet"), dict), "A06准备输入内容缺失")
            records.append(record)
        return records

    def analysis_plan_info(self, study_id):
        """只读呈现草稿能力；不初始化文件、不激活方案或调度任务。"""
        manifest = self.load(study_id)
        a00 = manifest["current"].get("A00")
        intake = (self.result(manifest, a00) or {}).get("summary", {}) if a00 else {}
        enabled = intake.get("analysis_plan_profile") == VERSION
        records = self._analysis_plan_records(manifest) if enabled else []
        selections = self._analysis_plan_selection_records(manifest) if enabled else []
        selection_reviews = self._analysis_plan_selection_reviews(manifest) if enabled else []
        a06_inputs = self._analysis_plan_a06_input_records(manifest) if enabled else []
        latest = records[-1] if records else None
        current = latest if latest and latest["expected_a00"] == a00 else None
        latest_selection = selections[-1] if selections else None
        if latest_selection and (latest_selection["expected_a00"] != a00
                                 or latest_selection["expected_a04"] != manifest["current"].get("A04")
                                 or not self.approved(manifest, latest_selection["expected_a04"])):
            latest_selection = None
        current_selection_review = next((row for row in reversed(selection_reviews)
                                         if latest_selection and row["selection_id"] == latest_selection["selection_id"]), None)
        latest_a06_input = a06_inputs[-1] if a06_inputs else None
        if (not latest_a06_input or not current_selection_review
                or current_selection_review["decision"] != "approved"
                or latest_a06_input["packet"]["runs"].get("A03_SELECT") != manifest["current"].get("A03_SELECT")
                or latest_a06_input["packet"]["runs"].get("A04") != manifest["current"].get("A04")
                or latest_a06_input["selection_review_id"] != current_selection_review["review_id"]
                or any(manifest["current"].get(module) != run_id
                       or not self.approved(manifest, run_id)
                       or self.latest_review(manifest, self.run(manifest, run_id)["artifact_id"])["review_id"]
                       != latest_a06_input["packet"]["reviews"].get(module)
                       for module, run_id in latest_a06_input["packet"]["runs"].items())):
            latest_a06_input = None
        return {"supported": enabled, "expected_a00": a00,
                "expected_draft_id": latest["plan_id"] if latest else "", "draft": current,
                "history_count": len(records), "a04_selection_history_count": len(selections),
                "a04_selection": latest_selection, "a04_selection_review": current_selection_review,
                "a06_preparation_input_history_count": len(a06_inputs),
                "a06_preparation_input": latest_a06_input, "execution_available": False,
                "message_zh": "方案修改仅保存新草稿，不影响正在执行的批次；全流程执行接入尚未完成。" if enabled else "历史固定流程保持；不向旧研究追加新自动方案。"}

    def save_analysis_plan_a04_selection(self, study_id, payload):
        """从当前已批准A04按绑定方案复算并留存选择；不改变运行或批准。"""
        fields = {"request_id", "expected_a00", "expected_a04", "expected_plan_id", "author", "note"}
        require(isinstance(payload, dict) and set(payload) == fields,
                "A04选择字段不完整或含不支持选项")
        safe_id(payload["request_id"], "planreq")
        safe_id(payload["expected_a00"], "run")
        safe_id(payload["expected_a04"], "run")
        safe_id(payload["expected_plan_id"], "plan")
        require(isinstance(payload["author"], str) and 0 < len(payload["author"].strip()) <= 2000,
                "请填写A04选择登记人")
        require(isinstance(payload["note"], str) and len(payload["note"]) <= 2000,
                "A04选择说明过长或格式不合法")
        request_hash = fingerprint(payload)
        with write_lock(self.root):
            manifest = self.load(study_id)
            require(not manifest.get("trashed"), "回收站研究只读，不能保存A04选择")
            require(manifest["current"].get("A00") == payload["expected_a00"]
                    and manifest["current"].get("A04") == payload["expected_a04"],
                    "A00或A04版本已更新，请刷新")
            require(self.approved(manifest, payload["expected_a04"]),
                    "请先通过当前A04，再保存方案受体选择")
            a04_run = self.run(manifest, payload["expected_a04"])
            require(a04_run.get("module_id") == "A04"
                    and a04_run.get("config", {}).get("version") == "A04.plan_network.1",
                    "当前A04不是新方案网络运行")
            a04_result = self.result(manifest, payload["expected_a04"])
            require(a04_result and isinstance(a04_result.get("summary"), dict)
                    and isinstance(a04_result.get("tables"), dict), "A04结果不完整")
            plan_record = next((row for row in self._analysis_plan_records(manifest)
                                if row["plan_id"] == payload["expected_plan_id"]
                                and row["expected_a00"] == payload["expected_a00"]), None)
            require(plan_record is not None, "A04方案不属于本研究当前A00")
            plan = checked_plan(plan_record["plan"])
            require(a04_run["config"].get("analysis_plan_id") == plan_record["plan_id"]
                    and a04_run["config"].get("analysis_parameter_hash") == plan["parameter_hash"]
                    and a04_result["summary"].get("analysis_plan_id") == plan_record["plan_id"]
                    and a04_result["summary"].get("analysis_parameter_hash") == plan["parameter_hash"],
                    "当前A04未绑定指定方案")
            selection = self.select_analysis_plan_a04_receptors(
                payload["expected_a04"], a04_result["summary"], a04_result["tables"], plan)
            for old in self._analysis_plan_selection_records(manifest):
                if old["request_id"] == payload["request_id"]:
                    if old["request_hash"] != request_hash:
                        raise AnalysisPlanConflict("A04选择提交编号已用于其他内容，请刷新后重试")
                    return {"selection": old["selection"], "record": old, "created": False,
                            "execution_available": False}
            root = self.location(study_id)
            plan_ref = next(ref for ref in manifest["analysis_plan_records"]
                            if read_json(verified_file(root, ref))["plan_id"] == plan_record["plan_id"])
            record = {"schema_version": A04_SELECTION_VERSION, "study_id": study_id,
                      "selection_id": new_id("selection"), "expected_a00": payload["expected_a00"],
                      "expected_a04": payload["expected_a04"], "plan_id": plan_record["plan_id"],
                      "analysis_parameter_hash": plan["parameter_hash"], "request_id": payload["request_id"],
                      "request_hash": request_hash, "created_at": now(),
                      "author": payload["author"].strip(), "note": payload["note"],
                      "state": "draft", "execution_available": False,
                      "selection": selection,
                      "source": {"a04_result": manifest["runs"][payload["expected_a04"]]["result_file"],
                                 "a04_run": manifest["runs"][payload["expected_a04"]]["run_file"],
                                 "analysis_plan": plan_ref}}
            target = within(root, "decisions/analysis_plans/a04_selection/" + record["selection_id"] + ".json")
            write_json(target, record)
            manifest.setdefault("analysis_plan_selection_records", []).append(
                file_record(root, target, "analysis_plan_a04_selection"))
            self.save(manifest)
            return {"selection": selection, "record": record, "created": True,
                    "execution_available": False}

    def _validated_current_plan_selection(self, manifest, selection_id):
        """在当前批准链上复算选择，供独立复核和A06准备输入共同使用。"""
        records = self._analysis_plan_selection_records(manifest)
        require(records and records[-1]["selection_id"] == selection_id,
                "A04选择已更新，请刷新")
        selection = records[-1]
        a00, a04 = selection["expected_a00"], selection["expected_a04"]
        require(manifest["current"].get("A00") == a00
                and manifest["current"].get("A04") == a04
                and self.approved(manifest, a04), "A04选择来源已失效，请刷新")
        run = self.run(manifest, a04)
        require(run["module_id"] == "A04" and run["config"].get("version") == "A04.plan_network.1",
                "A04选择来源不是新方案运行")
        plan_records = self._analysis_plan_records(manifest)
        plan_index = next((index for index, row in enumerate(plan_records)
                           if row["plan_id"] == selection["plan_id"] and row["expected_a00"] == a00), None)
        require(plan_index is not None, "A04选择方案与当前研究登记不一致")
        plan_record = plan_records[plan_index]
        plan = checked_plan(plan_record["plan"])
        require(plan["parameter_hash"] == selection["analysis_parameter_hash"]
                and run["config"].get("analysis_plan_id") == plan_record["plan_id"]
                and run["config"].get("analysis_parameter_hash") == plan["parameter_hash"],
                "A04选择方案指纹与网络运行不一致")
        result = self.result(manifest, a04)
        from science_modules.a04.selection_flow import validate_selection
        validate_selection(selection["selection"], a04, result["summary"], result["tables"], plan)
        root = self.location(manifest["study_id"])
        for reference in selection["source"].values():
            verified_file(root, reference)
        return selection, manifest["analysis_plan_selection_records"][-1], \
            plan_record, manifest["analysis_plan_records"][plan_index]

    def review_analysis_plan_a04_selection(self, study_id, payload):
        """选择复核单独留存；不代签A04运行、不启动结构准备。"""
        fields = {"request_id", "expected_a00", "expected_a04", "selection_id",
                  "expected_review_id", "decision", "reviewer", "note"}
        require(isinstance(payload, dict) and set(payload) == fields,
                "A04选择复核字段不完整或含不支持选项")
        safe_id(payload["request_id"], "planreq")
        safe_id(payload["expected_a00"], "run")
        safe_id(payload["expected_a04"], "run")
        safe_id(payload["selection_id"], "selection")
        require(payload["expected_review_id"] is None or
                safe_id(payload["expected_review_id"], "selectionreview"), "复核版本不合法")
        require(payload["decision"] in ("approved", "rejected", "pending"), "请选择A04选择复核决定")
        require(all(isinstance(payload[key], str) and 0 < len(payload[key].strip()) <= 2000
                    for key in ("reviewer", "note")), "请填写复核人与依据")
        request_hash = fingerprint(payload)
        with write_lock(self.root):
            manifest = self.load(study_id)
            require(not manifest.get("trashed"), "回收站研究只读")
            require(manifest["current"].get("A00") == payload["expected_a00"]
                    and manifest["current"].get("A04") == payload["expected_a04"],
                    "A00或A04版本已更新，请刷新")
            selection, selection_ref, _, _ = self._validated_current_plan_selection(
                manifest, payload["selection_id"])
            history = self._analysis_plan_selection_reviews(manifest)
            for old in history:
                if old["request_id"] == payload["request_id"]:
                    if old["request_hash"] != request_hash:
                        raise AnalysisPlanConflict("A04选择复核提交编号已用于其他内容")
                    latest = next((row for row in reversed(history)
                                   if row["selection_id"] == old["selection_id"]), None)
                    return {"review": old, "created": False,
                            "current": latest["review_id"] == old["review_id"]}
            previous = next((row for row in reversed(history)
                             if row["selection_id"] == selection["selection_id"]), None)
            if (previous["review_id"] if previous else None) != payload["expected_review_id"]:
                raise AnalysisPlanConflict("A04选择复核已更新，请刷新")
            record = {"schema_version": A04_SELECTION_REVIEW_VERSION,
                      "study_id": study_id, "review_id": new_id("selectionreview"),
                      "selection_id": selection["selection_id"], "selection_ref": selection_ref,
                      "expected_a00": payload["expected_a00"], "expected_a04": payload["expected_a04"],
                      "previous_review_id": payload["expected_review_id"],
                      "request_id": payload["request_id"], "request_hash": request_hash,
                      "decision": payload["decision"], "reviewer": payload["reviewer"].strip(),
                      "note": payload["note"].strip(), "created_at": now()}
            root = self.location(study_id)
            target = within(root, "decisions/analysis_plans/a04_selection_reviews/" + record["review_id"] + ".json")
            write_json(target, record)
            manifest.setdefault("analysis_plan_selection_reviews", []).append(
                file_record(root, target, "analysis_plan_a04_selection_review"))
            self.save(manifest)
            return {"review": record, "created": True, "current": True}

    def save_analysis_plan_a06_preparation_input(self, study_id, payload):
        """归档两份已复核选择的同批准备输入；不生成A06_PREP运行或计算授权。"""
        fields = {"request_id", "expected_a00", "expected_a03", "expected_a03_select",
                  "expected_a04", "expected_selection_id", "expected_selection_review_id",
                  "expected_plan_id", "author", "note"}
        require(isinstance(payload, dict) and set(payload) == fields,
                "A06准备输入字段不完整或含不支持选项")
        safe_id(payload["request_id"], "planreq")
        for key in ("expected_a00", "expected_a03", "expected_a03_select", "expected_a04"):
            safe_id(payload[key], "run")
        safe_id(payload["expected_selection_id"], "selection")
        safe_id(payload["expected_selection_review_id"], "selectionreview")
        safe_id(payload["expected_plan_id"], "plan")
        require(all(isinstance(payload[key], str) and 0 < len(payload[key].strip()) <= 2000
                    for key in ("author", "note")), "请填写A06准备输入登记人与依据")
        request_hash = fingerprint(payload)
        with write_lock(self.root):
            manifest = self.load(study_id)
            require(not manifest.get("trashed"), "回收站研究只读")
            runs = {module: payload[field] for module, field in
                    (("A00", "expected_a00"), ("A03", "expected_a03"),
                     ("A03_SELECT", "expected_a03_select"), ("A04", "expected_a04"))}
            require(all(manifest["current"].get(module) == run_id for module, run_id in runs.items()),
                    "A06准备上游版本已更新，请刷新")
            require(all(self.approved(manifest, run_id) for run_id in runs.values()),
                    "A06准备上游须逐项复核通过")
            require(self.run(manifest, runs["A03_SELECT"])["parent_runs"].get("A03") == runs["A03"]
                    and self.run(manifest, runs["A04"])["parent_runs"].get("A03") == runs["A03"],
                    "成分选择与A04网络不属于同一A03交集")
            selection, selection_ref, plan_record, plan_ref = self._validated_current_plan_selection(
                manifest, payload["expected_selection_id"])
            require(selection["plan_id"] == payload["expected_plan_id"],
                    "A06准备方案与受体选择不一致")
            history = self._analysis_plan_selection_reviews(manifest)
            review_index = next((index for index in range(len(history) - 1, -1, -1)
                                 if history[index]["selection_id"] == selection["selection_id"]), None)
            require(review_index is not None
                    and history[review_index]["review_id"] == payload["expected_selection_review_id"]
                    and history[review_index]["decision"] == "approved",
                    "A04受体选择尚未独立复核通过或复核已改变")
            selection_review_ref = manifest["analysis_plan_selection_reviews"][review_index]
            selected = self.result(manifest, runs["A03_SELECT"])["tables"].get("selected")
            require(isinstance(selected, list) and selected, "A03_SELECT成分选择为空")
            reviews = {module: self.latest_review(manifest, self.run(manifest, run_id)["artifact_id"])["review_id"]
                       for module, run_id in runs.items()}
            result_refs = {module: manifest["runs"][run_id]["result_file"] for module, run_id in runs.items()}
            from science_modules.a06.plan_input import build
            packet = build(study_id, runs, reviews, result_refs, selection_ref,
                           selection_review_ref, plan_ref, selection["selection"], selected)
            for old in self._analysis_plan_a06_input_records(manifest):
                if old["request_id"] == payload["request_id"]:
                    if old["request_hash"] != request_hash:
                        raise AnalysisPlanConflict("A06准备输入提交编号已用于其他内容")
                    return {"record": old, "created": False, "execution_available": False}
            record = {"schema_version": A06_INPUT_RECORD_VERSION, "study_id": study_id,
                      "input_id": new_id("input"), "selection_id": selection["selection_id"],
                      "selection_review_id": history[review_index]["review_id"],
                      "plan_id": plan_record["plan_id"], "packet": packet,
                      "request_id": payload["request_id"], "request_hash": request_hash,
                      "created_at": now(), "author": payload["author"].strip(),
                      "note": payload["note"].strip(), "state": "pending_structure_preparation",
                      "execution_available": False}
            root = self.location(study_id)
            target = within(root, "decisions/analysis_plans/a06_preparation_inputs/" + record["input_id"] + ".json")
            write_json(target, record)
            manifest.setdefault("analysis_plan_a06_input_records", []).append(
                file_record(root, target, "analysis_plan_a06_preparation_input"))
            self.save(manifest)
            return {"record": record, "created": True, "execution_available": False}

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
