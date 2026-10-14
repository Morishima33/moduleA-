"""A05排名首位命中定位图的独立归档；保留统计、运行和机制审批。"""

from copy import deepcopy

from contracts import require
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from science_modules.a05.display import metadata, english
from .bilingual_display import BilingualDisplayWorkflow

VERSION = "A05.ranked_pathway_maps.1"
SEMANTICS = "红色仅表示本批A05命中基因，不表示表达上调、通路激活、作用强弱或疗效；灰色未命中不等于生物学无关。"


def ranked_source(workflow, manifest, a05):
    """只取同运行确认范围的两个首位，不重新排序或进行富集计算。"""
    result = workflow.result(manifest, a05)
    require(result is not None and result["module_id"] == "A05", "通路定位图须绑定A05")
    tables = result["tables"]
    meta = metadata(tables)
    require(
        meta and meta["exclusions_confirmed"] and meta["layout_confirmed"],
        "请先确认A05展示范围和版式",
    )
    require(not meta["missing_translations"], "A05中文名称尚未核齐")
    binding = {
        "study_id": manifest["study_id"],
        "a05_run": a05,
        "result": deepcopy(manifest["runs"][a05]["result_file"]),
        "display_metadata": deepcopy(tables["display_metadata"]),
    }
    mapping = {str(r["entrez_id"]): r["symbol"] for r in tables["identity_mapping"]}
    items = []
    for ranking, key in (
        ("statistical_significance", "kegg_p_top10"),
        ("count", "kegg_count_top10"),
    ):
        if not tables.get(key):
            continue
        row = tables[key][0]
        ids = str(row["geneID"]).split("/")
        require(len(ids) == len(set(ids)) == int(row["Count"]), "KEGG命中数与基因身份不一致")
        require(all(g in mapping for g in ids), "KEGG命中基因缺少A05身份映射")
        items.append(
            {
                "ranking": ranking,
                "id": row["ID"],
                "name_en": english(row),
                "name_zh": row["description_zh"],
                "count": int(row["Count"]),
                "adjusted_p": row["p.adjust"],
                "entrez_ids": ids,
                "symbols": [mapping[g] for g in ids],
            }
        )
    return binding, items


class RankedPathwayWorkflow(BilingualDisplayWorkflow):
    """公开写入口锁内重验，图件作为补充资料不改变审批状态。"""

    def ranked_map_source(self, study_id, expected_a05, writable=True):
        manifest = self.load(study_id)
        require(expected_a05 in manifest["runs"], "A05版本不存在，请刷新")
        if writable:
            require(not manifest.get("trashed"), "回收站中的研究只读")
            require(manifest["current"].get("A05") == expected_a05, "A05已改变，请刷新")
            require(self.active(manifest, expected_a05), "A05已失效，请刷新")
        binding, items = ranked_source(self, manifest, expected_a05)
        if writable:
            meta = metadata(self.result(manifest, expected_a05)["tables"])
            latest, _ = self.display_decision(
                manifest, manifest["current"].get("A03"), meta["base_run"]
            )
            require(
                not latest or latest["decision_id"] == meta["decision_id"],
                "A05展示确认正在应用，请完成后重试",
            )
        return manifest, binding, items

    def ranked_pathway_records(self, manifest):
        root = self.location(manifest["study_id"])
        rows = []
        for record in manifest.get("ranked_pathway_map_records", []):
            row = read_json(verified_file(root, record))
            require(
                row["schema_version"] == VERSION
                and row["binding"]["study_id"] == manifest["study_id"],
                "通路图归档归属或版本不一致",
            )
            for item in row["files"]:
                verified_file(root, item)
            rows.append(dict(row, record=deepcopy(record)))
        return rows

    def ranked_maps_for(self, manifest, a05):
        binding, _ = ranked_source(self, manifest, a05)
        return next(
            (r for r in reversed(self.ranked_pathway_records(manifest)) if r["binding"] == binding),
            None,
        )

    def ranked_map_workspace(self, study_id, expected_a05):
        with write_lock(self.root):
            self.ranked_map_source(study_id, expected_a05)
            folder = self.location(study_id) / "reports" / new_id("ranked_maps")
            folder.mkdir(parents=True, exist_ok=False)
            return folder

    def publish_ranked_maps(self, study_id, expected_a05, binding, items, files):
        with write_lock(self.root):
            manifest, current, facts = self.ranked_map_source(study_id, expected_a05)
            require(binding == current, "A05来源已改变，请刷新")
            require(
                [{k: r[k] for k in f} for r, f in zip(items, facts)] == facts
                and len(items) == len(facts),
                "通路图与当前排名命中不一致",
            )
            root = self.location(study_id)
            for record in files:
                verified_file(root, record)
            for item in items:
                require(
                    item["png"] in files and item["node_mapping"] in files, "通路图或节点映射未登记"
                )
            row = {
                "schema_version": VERSION,
                "map_id": new_id("ranked_maps"),
                "created_at": now(),
                "binding": deepcopy(binding),
                "items": deepcopy(items),
                "files": deepcopy(files),
                "semantics_zh": SEMANTICS,
                "pathview_version": "1.46.0",
            }
            path = root / "decisions" / "A05_ranked_pathway_maps" / (row["map_id"] + ".json")
            write_json(path, row)
            manifest.setdefault("ranked_pathway_map_records", []).append(
                file_record(root, path, "ranked_pathway_maps")
            )
            self.save(manifest)
            return dict(row, record=file_record(root, path, "ranked_pathway_maps"))

    def ranked_map_context(self, manifest, a05, historical=False, busy=False):
        if not a05:
            return None
        result = self.result(manifest, a05)
        meta = metadata(result["tables"])
        if (
            not meta
            or not meta["exclusions_confirmed"]
            or not meta["layout_confirmed"]
            or meta["missing_translations"]
        ):
            return None
        binding, facts = ranked_source(self, manifest, a05)
        row = self.ranked_maps_for(manifest, a05)
        enabled = (
            not historical
            and not manifest.get("trashed")
            and not busy
            and self.active(manifest, a05)
        )
        items = []
        if row:
            for item in row["items"]:
                index = row["files"].index(item["png"])
                items.append(
                    {
                        k: item[k]
                        for k in (
                            "ranking",
                            "id",
                            "name_en",
                            "name_zh",
                            "count",
                            "adjusted_p",
                            "not_in_current_kgml",
                            "caption_zh",
                        )
                    }
                    | {
                        "png_url": f"/api/v1/studies/{manifest['study_id']}/files/{row['map_id']}.{index}?inline=1"
                    }
                )
        return {
            "enabled": enabled and bool(facts),
            "expected_a05": a05,
            "disabled_reason_zh": "" if enabled else "历史、失效、回收站或后台忙碌时只读。",
            "semantics_zh": SEMANTICS,
            "items": items,
        }

    def ranked_map_file(self, manifest, map_id, index):
        row = next(
            (r for r in self.ranked_pathway_records(manifest) if r["map_id"] == map_id), None
        )
        require(row is not None and 0 <= index < len(row["files"]), "通路图文件不存在")
        return verified_file(self.location(manifest["study_id"]), row["files"][index])
