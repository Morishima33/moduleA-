"""试算交接专用Workflow；替代输入链只适用于明确的新扩展结果协议。"""

from contextlib import contextmanager
from copy import deepcopy

from contracts import SCHEMA_VERSION, fingerprint, require
from science_modules.a06.trial_handoff import NOTE, VERSION, matrix_rows, setup_rows
from storage import (
    file_record,
    new_id,
    now,
    read_json,
    verified_file,
    write_json,
    write_lock,
)

from .trial_workflow import TrialWorkflow


class TrialHandoffWorkflow(TrialWorkflow):
    """原严格准备指针保持；A06结果通过一次正式复核后供A07引用。"""

    @contextmanager
    def handoff_read_cache(self):
        """一次交接内重复只读核验复用；操作结束清除，写入前在锁内重建。"""
        previous = getattr(self, "_view_cache", None)
        self.reset_handoff_cache()
        try:
            yield
        finally:
            if previous is None:
                self.__dict__.pop("_view_cache", None)
            else:
                self._view_cache = previous

    def reset_handoff_cache(self):
        self._view_cache = {
            "runs": {},
            "results": {},
            "reviews": {},
            "active": {},
            "approved": {},
        }

    def review(self, *args, **kwargs):
        # 原review先获取写锁再读取；缓存开始时为空，操作后清除，不沿用旧页面判断。
        with self.handoff_read_cache():
            return super().review(*args, **kwargs)

    def handoff_binding(self, manifest, inputs):
        sid = manifest["study_id"]
        records = manifest.get("docking_trial_records", [])
        require(
            records
            and records[-1]["trial_id"] == inputs["trial_id"]
            and records[-1]["state"] == "completed",
            "试算已更新或未完成",
        )
        self.trial_binding(sid, records[-1]["payload"], manifest)
        require(records[-1]["packet"] == inputs["trial_packet"], "试算评分版本改变")
        reviews = [
            r
            for r in manifest.get("docking_trial_review_records", [])
            if read_json(verified_file(self.location(sid), r))["trial_id"]
            == inputs["trial_id"]
        ]
        require(
            reviews and reviews[-1] == inputs["trial_review"],
            "试算核查已改变，请重新接入",
        )
        require(
            read_json(verified_file(self.location(sid), reviews[-1]))["confirmed"],
            "请先确认本批试算核查",
        )
        return records[-1]

    def _active(self, manifest, run_id):
        if not super()._active(manifest, run_id):
            return False
        run = self.run(manifest, run_id)
        if run.get("config", {}).get("schema_version") == VERSION:
            from contracts import ContractError

            try:
                self.handoff_binding(manifest, run["inputs"])
            except ContractError:
                return False
        return True

    def _begin(self, manifest, module, inputs, config, reason):
        if module != "A06" or config.get("schema_version") != VERSION:
            return super()._begin(manifest, module, inputs, config, reason)
        # 已完成且人工确认的扩展试算走独立输入链；不批准或解除旧严格准备的阻断。
        self.handoff_binding(manifest, inputs)
        parents, reviews, artifacts = {}, {}, []
        for mid in ("A03", "A03_SELECT", "A04"):
            rid = manifest["current"].get(mid)
            require(rid and self.approved(manifest, rid), "试算上游未通过：" + mid)
            parent = self.run(manifest, rid)
            parents[mid] = rid
            reviews[mid] = self.latest_review(manifest, parent["artifact_id"])[
                "review_id"
            ]
            artifacts.append(parent["artifact_id"])
        run = {
            "schema_version": SCHEMA_VERSION,
            "study_id": manifest["study_id"],
            "run_id": new_id("run"),
            "module_id": module,
            "artifact_id": new_id("artifact"),
            "parent_runs": parents,
            "parent_review_ids": reviews,
            "parent_artifact_ids": artifacts,
            "inputs": inputs,
            "config": config,
            "input_hash": fingerprint({"inputs": inputs, "parents": artifacts}),
            "config_hash": fingerprint(config),
            "code_version": self.code_version,
            "environment_version": fingerprint(self.environment),
            "environment": self.environment,
            "created_at": now(),
            "reason": reason,
        }
        folder = self.location(manifest["study_id"]) / "runs/A06" / run["run_id"]
        write_json(folder / "run.json", run)
        manifest["runs"][run["run_id"]] = {
            "run_file": file_record(
                self.location(manifest["study_id"]), folder / "run.json", "run"
            ),
            "result_file": None,
        }
        manifest["current"][module] = run["run_id"]
        return run

    def publish_trial_handoff(self, sid, trial_id, reason):
        """只引用真实评分产生待正式复核A06；不复制科研审批、不运行Vina。"""
        with write_lock(self.root), self.handoff_read_cache():
            manifest = self.load(sid)
            record = manifest["docking_trial_records"][-1]
            require(record["trial_id"] == trial_id, "试算已改变")
            root = self.location(sid)
            reviews = [
                r
                for r in manifest.get("docking_trial_review_records", [])
                if read_json(verified_file(root, r))["trial_id"] == trial_id
            ]
            require(bool(reviews), "当前试算尚未核查")
            inputs = {
                "trial_id": trial_id,
                "trial_packet": deepcopy(record["packet"]),
                "trial_review": deepcopy(reviews[-1]),
                "strict_preparation_history": manifest["current"].get("A06_PREP"),
            }
            self.handoff_binding(manifest, inputs)
            current = manifest["current"].get("A06")
            if current:
                old = self.run(manifest, current)
                if (
                    old.get("config", {}).get("schema_version") == VERSION
                    and old["inputs"] == inputs
                    and self.active(manifest, current)
                ):
                    return self.result(manifest, current)
            packet = read_json(verified_file(root, record["packet"]))
            summary = {
                "science_version": VERSION,
                "interpretation_scope": "extended_trial",
                "all_receptors_strict_passed": False,
                "handoff_blocked": False,
                "成功组合数": packet["summary"]["completed"],
                "失败组合数": packet["summary"]["NA"],
                "成分数": 15,
                "受体数": 15,
                "结果用途": NOTE,
                "trial_id": trial_id,
            }
            run = self._begin(
                manifest,
                "A06",
                inputs,
                {"schema_version": VERSION, "interpretation_scope": "extended_trial"},
                reason,
            )
            result = self._finish(
                manifest,
                run["run_id"],
                summary,
                {
                    "score_matrix": matrix_rows(packet),
                    "receptor_setup": setup_rows(packet),
                },
                [NOTE],
                "success",
                sources=[record["packet"], reviews[-1]],
                attachments=record["files"],
            )
            self.save(manifest)
            return result
