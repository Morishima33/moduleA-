"""全覆盖试算的独立版本账本；不回写正式准备、科研批准及历史结果。"""

from uuid import uuid4

from contracts import require
from storage import file_record, now, read_json, verified_file, write_json, write_lock

from .coverage_workflow import CoverageWorkflow


class TrialWorkflow(CoverageWorkflow):
    """所有试算写入沿用研究锁；上游或展示名单变化后旧任务不能发布。"""

    def trial_binding(self, sid, payload, manifest=None):
        """重新检查研究、批准来源、准备版本和名单，不以网页状态代替事实。"""
        manifest = manifest or self.load(sid)
        require(not manifest.get("trashed"), "回收站研究只读")
        _, context, _, _, _ = self.coverage_binding(sid, payload, manifest)
        require(bool(manifest.get("matrix_display_records")), "没有已确认展示名单")
        record = manifest["matrix_display_records"][-1]
        display = read_json(verified_file(self.location(sid), record))
        require(
            display["study_id"] == sid
            and display["source_key"] == context["source_key"]
            and display["display_id"] == payload.get("expected_display_id"),
            "试算名单版本已改变，请刷新",
        )
        require(
            len(display["config"]["table_compounds"]) == 15
            and len(display["config"]["table_targets"]) == 15,
            "试算必须为15×15",
        )
        return manifest, context, display, record

    def begin_trial(self, sid, payload):
        """用户已授权的真实试算建立独立运行，不更换current及批准记录。"""
        with write_lock(self.root):
            manifest, context, display, display_record = self.trial_binding(
                sid, payload
            )
            require(payload.get("authorization_zh", "").strip(), "缺少真实试算授权说明")
            trial_id = "trial_" + uuid4().hex
            folder = self.location(sid) / "runs/A06_TRIAL" / trial_id
            folder.mkdir(parents=True, exist_ok=False)
            authorization = {
                "schema_version": "A06.full_coverage_trial.authorization.1",
                "trial_id": trial_id,
                "study_id": sid,
                "created_at": now(),
                "payload": payload,
                "source_key": context["source_key"],
                "display": display,
                "display_record": display_record,
                "formal_approval": None,
                "batch_docking_allowed": True,
            }
            write_json(folder / "authorization.json", authorization)
            manifest.setdefault("docking_trial_records", []).append(
                {
                    "trial_id": trial_id,
                    "created_at": now(),
                    "state": "running",
                    "source_key": context["source_key"],
                    "payload": payload,
                    "authorization": file_record(
                        self.location(sid),
                        folder / "authorization.json",
                        "trial_authorization",
                    ),
                    "progress_path": (folder / "progress.json")
                    .relative_to(self.location(sid))
                    .as_posix(),
                }
            )
            self.save(manifest)
            return trial_id, folder, context, display

    def finish_trial(self, sid, trial_id, packet_path, files):
        """完成包索引化；仅追加试算记录，不自动科研验收。"""
        with write_lock(self.root):
            manifest = self.load(sid)
            rows = [
                r
                for r in manifest.get("docking_trial_records", [])
                if r["trial_id"] == trial_id
            ]
            require(
                len(rows) == 1 and rows[0]["state"] == "running", "试算运行状态非法"
            )
            row = rows[0]
            self.trial_binding(sid, row["payload"], manifest)
            packet = read_json(packet_path)
            require(
                packet.get("study_id") == sid
                and packet.get("trial_id") == trial_id
                and packet.get("source_key") == row["source_key"],
                "试算完成包绑定不一致",
            )
            from science_modules.a06.trial_evidence import audit_outputs

            audit_outputs(self.location(sid), packet)
            for rec in files:
                verified_file(self.location(sid), rec)
            row.update(
                state="completed",
                finished_at=now(),
                files=files,
                packet=file_record(self.location(sid), packet_path, "trial_packet"),
            )
            self.save(manifest)
            return row

    def save_trial_review(self, sid, trial_id, note, reviewer, confirmed=False):
        """试算核查单独保存，刷新可恢复；不会签署正式A06或严格质控。"""
        with write_lock(self.root):
            manifest = self.load(sid)
            rows = [
                r
                for r in manifest.get("docking_trial_records", [])
                if r["trial_id"] == trial_id
            ]
            require(len(rows) == 1, "试算版本不存在")
            require(
                manifest["docking_trial_records"][-1]["trial_id"] == trial_id,
                "试算已产生新版本，旧窗口只能查看，请刷新",
            )
            self.trial_binding(sid, rows[0]["payload"], manifest)
            require(
                isinstance(note, str) and isinstance(reviewer, str), "核查信息格式非法"
            )
            require(
                not confirmed
                or (
                    note.strip()
                    and reviewer.strip()
                    and rows[0]["state"] == "completed"
                ),
                "确认需完整试算及核查人和说明",
            )
            value = {
                "review_id": "trial_review_" + uuid4().hex,
                "trial_id": trial_id,
                "note": note,
                "reviewer": reviewer,
                "confirmed": bool(confirmed),
                "created_at": now(),
                "formal_approval": None,
            }
            path = (
                self.location(sid)
                / "decisions/A06_trial_review"
                / (value["review_id"] + ".json")
            )
            write_json(path, value)
            manifest.setdefault("docking_trial_review_records", []).append(
                file_record(self.location(sid), path, "trial_review")
            )
            self.save(manifest)
            return value

    def stop_trial(self, sid, trial_id, reason):
        """中断仅记录状态和原因，原文件与当前正式结果均保留。"""
        with write_lock(self.root):
            manifest = self.load(sid)
            rows = [
                r
                for r in manifest.get("docking_trial_records", [])
                if r["trial_id"] == trial_id
            ]
            require(len(rows) == 1, "试算记录不存在")
            if rows[0]["state"] == "running":
                rows[0].update(state="interrupted", finished_at=now(), reason_zh=reason)
                self.save(manifest)

    def attach_trial_exports(self, sid, trial_id, records):
        """追加同批展示产物索引，原评分包与既有专业报告不回写。"""
        with write_lock(self.root):
            manifest = self.load(sid)
            rows = [
                r
                for r in manifest.get("docking_trial_records", [])
                if r["trial_id"] == trial_id
            ]
            require(len(rows) == 1 and rows[0]["state"] == "completed", "试算尚未完成")
            self.trial_binding(sid, rows[0]["payload"], manifest)
            names = {r["path"] for r in rows[0]["files"]}
            for rec in records:
                verified_file(self.location(sid), rec)
                require(
                    rec["path"] not in names
                    and rec["path"].startswith(
                        "runs/A06_TRIAL/" + trial_id + "/exports/"
                    ),
                    "展示产物不属于当前试算或重复",
                )
                names.add(rec["path"])
            rows[0]["files"].extend(records)
            validations = [
                r for r in records if r["path"].endswith("/export_validation.json")
            ]
            require(len(validations) == 1, "展示产物必须绑定唯一核验版本")
            version = read_json(verified_file(self.location(sid), validations[0]))[
                "display_version"
            ]
            require(
                version in {"A06.trial.display.1", "A06.trial.display.2"},
                "未知展示版本",
            )
            rows[0]["display_version"] = version
            self.save(manifest)
