"""A06出图附件的版本绑定、独立归档和下载索引；不改变科研运行或批准。"""

from copy import deepcopy
from hashlib import sha256
import math
from pathlib import Path

from contracts import require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from .trial_preparation_workflow import TrialPreparationWorkflow
from .compound_names import compound_names

VERSION = "A06.drawing.artifacts.1"


def pair_key(compound_id, target_id):
    """组合键由稳定身份生成，避免名称冲突和路径输入。"""
    return "pair_" + sha256((compound_id + "|" + target_id).encode()).hexdigest()[:24]


def catalog(workflow, manifest, a06):
    """从当前归档提取原始评分及姿势引用，支持扩展试算和通用结果。"""
    root = workflow.location(manifest["study_id"])
    run = workflow.run(manifest, a06)
    result = workflow.result(manifest, a06)
    binding = {
        "study_id": manifest["study_id"],
        "a06_run": a06,
        "result": deepcopy(manifest["runs"][a06]["result_file"]),
    }
    # 运行中或失败且尚未提交结果时，没有可供出图的最终评分；进度由任务区展示。
    if result is None:
        return binding, []
    packet_record = run.get("inputs", {}).get("trial_packet")
    automatic_record = next(iter(result.get("tables", {}).get("automatic_packet", [])), None)
    pairs = []
    if automatic_record:
        # 自动批次只信同研究同运行的归档包；不引用旧试算、其他研究或客户端姿势。
        packet = read_json(verified_file(root, automatic_record))
        require(packet.get("study_id") == manifest["study_id"] and packet.get("run_id") == a06,
                "自动出图来源研究或运行不一致")
        binding["automatic_packet"] = deepcopy(automatic_record)
        names = compound_names(workflow, manifest, run.get("parent_runs", {}).get("A03"), packet)
        compounds = {c["compound_id"]: c for c in packet["compounds"]}
        receptors = {r["target_id"]: r for r in packet["receptors"]}
        for pair in packet["pairs"]:
            compound, receptor = compounds[pair["compound_id"]], receptors[pair["target_id"]]
            region = pair.get("execution")
            if pair["state"] != "completed":
                region = None
            if region:
                require(region.get("state") == "completed" and region.get("score") == pair["score"],
                        "自动组合与采用区域原始评分不一致")
                require(region.get("region_id") == pair.get("region_id", region.get("region_id")),
                        "自动组合采用区域不一致")
            label = names.get(pair["compound_id"], {})
            # 附件清单只带本组合所需字段；全量候选/补救历史按绑定packet回溯，不复制80次。
            compact_compound = {k: deepcopy(compound[k]) for k in ("compound_id", "name", "name_zh", "files") if k in compound}
            compact_receptor = {k: deepcopy(receptor[k]) for k in ("target_id", "symbol", "quality", "mode", "receptor", "structure_id", "spec") if k in receptor}
            if "receptor" not in compact_receptor and receptor.get("evidence", {}).get("receptor"):
                compact_receptor["receptor"] = deepcopy(receptor["evidence"]["receptor"])
            pairs.append({"compound_id": pair["compound_id"], "target_id": pair["target_id"],
                          "compound_name_zh": label.get("name_zh") or compound.get("name_zh") or compound.get("name") or pair["compound_id"],
                          "compound_name_en": label.get("name_en") or compound.get("name") or "",
                          "target_zh": receptor["symbol"], "score": pair["score"] if region else None,
                          "region": deepcopy(region), "compound": compact_compound,
                          "receptor": compact_receptor, "mode": pair.get("mode", receptor.get("mode", "")),
                          "scope_zh": f"自动对接；{pair.get('quality', receptor.get('quality', ''))}；评分不代表严格验证或药效",
                          "automatic": True, "state": pair["state"], "reason_zh": pair.get("reason_zh", "")})
    elif packet_record:
        packet = read_json(verified_file(root, packet_record))
        binding["trial_packet"] = deepcopy(packet_record)
        names = compound_names(workflow, manifest, run.get("parent_runs", {}).get("A03"), packet)
        compounds = {c["compound_id"]: c for c in packet["compounds"]}
        receptors = {r["target_id"]: r for r in packet["receptors"]}
        for pair in packet["pairs"]:
            compound, receptor = compounds[pair["compound_id"]], receptors[pair["target_id"]]
            region = next(
                (
                    r
                    for r in pair.get("regions", [])
                    if r["region_id"] == pair.get("selected_region_id")
                    and r["state"] == "completed"
                ),
                None,
            )
            pairs.append(
                {
                    "compound_id": pair["compound_id"],
                    "target_id": pair["target_id"],
                    "compound_name_zh": compound["name_zh"],
                    "compound_name_en": names.get(pair["compound_id"], {}).get("name_en", ""),
                    "target_zh": receptor["symbol"],
                    "score": pair["score"],
                    "region": deepcopy(region),
                    "compound": deepcopy(compound),
                    "receptor": deepcopy(receptor),
                    "mode": pair.get("mode", receptor["mode"]),
                    "scope_zh": "扩展试算；保留严格质控限制",
                }
            )
    else:
        generic = result.get("tables", {}).get("generic_docking")
        if not isinstance(generic, dict):
            return binding, []
        receptors = {r["target"]: r for r in generic["receptors"]}
        for row in generic["completed_pairs"]:
            pairs.append(
                {
                    "compound_id": row["compound_id"],
                    "target_id": row["target"],
                    "compound_name_zh": row.get("compound_name") or row["compound_id"],
                    "compound_name_en": row.get("compound_name_en", ""),
                    "target_zh": row["target"],
                    "score": row["score_kcal_mol"],
                    "generic_row": deepcopy(row),
                    "receptor": deepcopy(receptors[row["target"]]),
                    "scope_zh": receptors[row["target"]].get("structure_limitation", ""),
                }
            )
    for row in pairs:
        row["pair_key"] = pair_key(row["compound_id"], row["target_id"])
        score = row["score"]
        row["eligible"] = (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
            and score <= -8
        )
    return binding, pairs


class DockingArtifactWorkflow(TrialPreparationWorkflow):
    """所有新附件经过公开方法和研究写锁，不更换current/runs/reviews。"""

    def artifact_source(self, study_id, expected_a06, writable=True):
        """检查A06版本及有效性；写入前重新加载，避免旧页面绑定新运行。"""
        manifest = self.load(study_id)
        if writable:
            require(not manifest.get("trashed"), "研究在回收站中只读")
            require(manifest["current"].get("A06") == expected_a06, "A06已改变，请刷新")
            with self.handoff_read_cache():
                require(self.active(manifest, expected_a06), "A06已失效，请刷新")
        require(expected_a06 in manifest["runs"], "A06版本不存在，请刷新")
        require(self.run(manifest, expected_a06)["module_id"] == "A06", "附件必须绑定A06")
        binding, pairs = catalog(self, manifest, expected_a06)
        return manifest, binding, pairs

    def artifact_records(self, manifest):
        """只读取本研究明确登记的附件；损坏索引不能跳过核验。"""
        root = self.location(manifest["study_id"])
        rows = [
            read_json(verified_file(root, r)) for r in manifest.get("docking_artifact_records", [])
        ]
        require(
            all(
                r["schema_version"] == VERSION and r["binding"]["study_id"] == manifest["study_id"]
                for r in rows
            ),
            "出图附件索引校验失败",
        )
        return rows

    def validate_artifact_request(self, study_id, payload, ready=False):
        """验证组合选择及本轮≤−8范围；未准备组合不会隐式生成。"""
        manifest, binding, pairs = self.artifact_source(study_id, payload.get("expected_a06", ""))
        keys = payload.get("pair_keys")
        require(
            isinstance(keys, list)
            and 0 < len(keys) <= 1000
            and all(isinstance(k, str) for k in keys)
            and len(set(keys)) == len(keys),
            "请选择不重复的对接组合",
        )
        chosen = [p for p in pairs if p["pair_key"] in keys]
        require(
            len(chosen) == len(keys) and all(p["eligible"] for p in chosen),
            "本轮只整理原始评分≤−8的有效组合；其他组合请另行指定",
        )
        if ready:
            records = self.artifact_records(manifest)
            available = {
                r["pair_key"] for r in records if r["kind"] == "package" and r["binding"] == binding
            }
            require(set(keys) <= available, "所选组合包尚未准备完成，请等待后台任务")
        return manifest, binding, chosen

    def artifact_workspace(self, study_id, expected_a06):
        """为单次制作保留独立目录，失败或取消不会覆盖既有包。"""
        with write_lock(self.root):
            self.artifact_source(study_id, expected_a06)
            folder = self.location(study_id) / "task_packages" / new_id("drawing")
            folder.mkdir(parents=True, exist_ok=False)
            return folder

    def publish_artifact(self, study_id, expected_a06, binding, item):
        """再次核验来源后发布附件索引；失败草案不作为可下载成品。"""
        with write_lock(self.root):
            manifest, current, pairs = self.artifact_source(study_id, expected_a06)
            require(current == binding, "A06来源已改变，请刷新")
            require(item["kind"] in ("package", "bundle"), "未知附件类型")
            valid = {p["pair_key"] for p in pairs if p["eligible"]}
            keys = [item["pair_key"]] if item["kind"] == "package" else item["pair_keys"]
            require(set(keys) <= valid, "对接包范围与本轮授权不一致")
            root = self.location(study_id)
            for record in item["files"]:
                verified_file(root, record)
            # 相同组合复用已完成包；来源改变时独立建立新版本。
            if item["kind"] == "package":
                old = next(
                    (
                        r
                        for r in self.artifact_records(manifest)
                        if r["kind"] == "package"
                        and r["binding"] == binding
                        and r["pair_key"] == item["pair_key"]
                    ),
                    None,
                )
                if old:
                    for record in old["files"]:
                        verified_file(root, record)
                    return old
            return self._append_artifact(manifest, binding, item)

    def _append_artifact(self, manifest, binding, item):
        """在持有锁时追加文件及索引，正式批准数量保持原口径。"""
        item = deepcopy(item)
        item.update(
            schema_version=VERSION,
            artifact_id=new_id("dock_artifact"),
            created_at=now(),
            binding=deepcopy(binding),
        )
        root = self.location(manifest["study_id"])
        path = root / "decisions" / "A06_drawing_artifacts" / (item["artifact_id"] + ".json")
        write_json(path, item)
        manifest.setdefault("docking_artifact_records", []).append(
            file_record(root, path, "drawing_artifact")
        )
        self.save(manifest)
        return item

    def save_docking_figure(self, study_id, payload, data, image_info):
        """完整解码后的用户图片另存新版本，原始字节不改动。"""
        with write_lock(self.root):
            manifest, binding, pairs = self.artifact_source(
                study_id, payload.get("expected_a06", "")
            )
            key = payload.get("pair_key", "")
            require(not key or key in {p["pair_key"] for p in pairs}, "图片组合不存在，请刷新")
            caption = payload.get("caption", "")
            require(
                isinstance(caption, str) and 0 < len(caption.strip()) <= 2000,
                "请填写图片说明（最多2000字）",
            )
            require(
                isinstance(data, bytes) and 0 < len(data) <= 16 * 1024 * 1024, "图片须不超过16MiB"
            )
            require(image_info["format"] in ("PNG", "JPEG"), "仅支持PNG/JPEG图片")
            suffix = ".png" if image_info["format"] == "PNG" else ".jpg"
            root = self.location(study_id)
            path = root / "raw" / "A06_figures" / (new_id("figure") + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
            item = {
                "kind": "image",
                "pair_key": key,
                "name_zh": Path(payload.get("name", "图片").replace("\\", "/")).name[:200],
                "caption_zh": caption.strip(),
                "width": image_info["width"],
                "height": image_info["height"],
                "files": [file_record(root, path, "user_docking_figure")],
            }
            return self._append_artifact(manifest, binding, item)

    def docking_artifact_context(self, manifest, a06, historical=False, busy=False):
        """页面只展示同版本组合、已准备包和用户图片，资格由后端给出。"""
        if not a06:
            return None
        binding, pairs = catalog(self, manifest, a06)
        if not pairs:
            return None
        with self.handoff_read_cache():
            active = self.active(manifest, a06)
        enabled = not historical and not manifest.get("trashed") and active and not busy
        rows = [r for r in self.artifact_records(manifest) if r["binding"] == binding]
        packages = {r["pair_key"]: r for r in rows if r["kind"] == "package"}
        sid = manifest["study_id"]

        def url(row):
            return f"/api/v1/studies/{sid}/files/{row['artifact_id']}.0"

        visible = [
            {
                k: p[k]
                for k in (
                    "pair_key",
                    "compound_id",
                    "compound_name_zh",
                    "compound_name_en",
                    "target_id",
                    "target_zh",
                    "score",
                    "eligible",
                )
            }
            | {"package_url": url(packages[p["pair_key"]]) if p["pair_key"] in packages else None}
            for p in pairs
        ]
        return {
            "enabled": enabled,
            "expected_a06": a06,
            "disabled_reason_zh": ""
            if enabled
            else "当前只读或后台忙碌；历史、失效及回收站不能上传或制作包。",
            "eligible_count": sum(p["eligible"] for p in pairs),
            "ready_count": len(packages),
            "pairs": visible,
            "images": [
                {
                    k: r[k]
                    for k in (
                        "artifact_id",
                        "name_zh",
                        "caption_zh",
                        "pair_key",
                        "created_at",
                        "width",
                        "height",
                    )
                }
                | {"url": url(r)}
                for r in rows
                if r["kind"] == "image"
            ],
            "bundles": [
                {
                    "artifact_id": r["artifact_id"],
                    "name_zh": r["name_zh"],
                    "url": url(r),
                    "pair_keys": r["pair_keys"],
                }
                for r in rows
                if r["kind"] == "bundle"
            ],
        }

    def docking_artifact_file(self, manifest, artifact_id, index):
        """下载只查显式登记的本研究附件，历史仍逐字节核验。"""
        row = next(
            (r for r in self.artifact_records(manifest) if r["artifact_id"] == artifact_id), None
        )
        require(row is not None and 0 <= index < len(row["files"]), "附件文件不存在")
        return verified_file(self.location(manifest["study_id"]), row["files"][index])
