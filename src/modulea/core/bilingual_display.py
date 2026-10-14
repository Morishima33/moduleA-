"""A06第四版中英图表的独立附件账本，不更换评分、历史运行和人工批准。"""

from copy import deepcopy
from pathlib import Path

from contracts import require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from .compound_names import compound_names
from .docking_artifacts import DockingArtifactWorkflow

VERSION = "A06.bilingual.display.artifacts.1"


class BilingualDisplayWorkflow(DockingArtifactWorkflow):
    """后台生成后在同一研究锁内再次核验来源，只追加可下载显示版本。"""

    def bilingual_display_binding(self, sid, expected_a06):
        """沿用原A06失效和回收站保护，将名称证据纳入显示绑定。"""
        manifest, binding, _ = self.artifact_source(sid, expected_a06)
        require(binding.get("trial_packet"), "本显示版本需要完整试算包")
        packet = read_json(verified_file(self.location(sid), binding["trial_packet"]))
        run = self.run(manifest, expected_a06)
        names = compound_names(self, manifest, run.get("parent_runs", {}).get("A03"), packet)
        binding = deepcopy(binding)
        binding["names"] = names
        return manifest, binding, packet, names

    def prepare_bilingual_display(self, sid, expected_a06):
        """仅后台调用Pillow/openpyxl；同一绑定复用已校验输出，不运行Vina。"""
        from science_modules.a06.bilingual_heatmap import export_heatmap, matrix
        from science_modules.a06.bilingual_workbook import export_workbook

        with write_lock(self.root):
            manifest, binding, packet, names = self.bilingual_display_binding(sid, expected_a06)
            for row in reversed(manifest.get("bilingual_display_records", [])):
                if row["binding"] == binding and row.get("schema_version") == VERSION:
                    for record in row["files"]:
                        verified_file(self.location(sid), record)
                    return row
            display_id = new_id("bilingual_display")
            directory = self.location(sid) / "task_packages" / display_id
            directory.mkdir(parents=True, exist_ok=False)
        view = matrix(packet, names)
        outputs = export_heatmap(view, directory)
        outputs.update(export_workbook(view, directory))
        with write_lock(self.root):
            manifest, current, _, _ = self.bilingual_display_binding(sid, expected_a06)
            require(current == binding, "生成期间A06或名称来源已改变，请刷新")
            row = {
                "schema_version": VERSION,
                "display_id": display_id,
                "created_at": now(),
                "binding": binding,
                "display_version": view["display_version"],
                "files": [
                    file_record(self.location(sid), path, "bilingual_" + kind)
                    for kind, path in outputs.items()
                ],
            }
            write_json(directory / "display.json", row)
            manifest.setdefault("bilingual_display_records", []).append(row)
            self.save(manifest)
            return row

    def bilingual_display_downloads(self, manifest, packet):
        """只读附件始终绑定对应trial_packet和A06，旧来源不冒充当前显示。"""
        sid = manifest["study_id"]
        a06 = manifest["current"].get("A06")
        if not a06:
            return []
        run = self.run(manifest, a06)
        packet_record = run.get("inputs", {}).get("trial_packet")
        if run.get("inputs", {}).get("trial_id") != packet.get("trial_id"):
            return []
        for row in reversed(manifest.get("bilingual_display_records", [])):
            bind = row["binding"]
            if bind.get("a06_run") != a06 or bind.get("trial_packet") != packet_record:
                continue
            require(
                bind.get("study_id") == sid and row["schema_version"] == VERSION,
                "中英显示索引绑定错误",
            )
            return [
                {
                    "name": Path(r["path"]).name,
                    "url": f"/api/v1/studies/{sid}/files/{row['display_id']}.{i}",
                }
                for i, r in enumerate(row["files"])
                if verified_file(self.location(sid), r)
            ]
        return []
