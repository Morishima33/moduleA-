"""试算只读展示；完整精度与配色来自同批服务端归档，网页不计算科学评分。"""

from pathlib import Path

from contracts import ContractError, require
from science_modules.a06.matrix_palette import color as palette_color
from science_modules.a06.matrix_palette import text_color
from science_modules.a06.trial_presentation import (
    LEGEND,
    PALETTE,
    THRESHOLD,
    VERSION,
    highlighted,
    score_label,
)
from science_modules.a06.trial_rules import validate_matrix
from storage import read_json, verified_file, within


def color(score, low, high):
    """恢复上一版蓝色渐变；无真实评分使用灰色。"""
    if score is None:
        return PALETTE["na_color"]
    return palette_color(score, low, high, PALETTE)


def trial_info(workflow, manifest, busy=False):
    """运行时只显示进度；完整完成包通过225格校验才展示评分。"""
    records = manifest.get("docking_trial_records", [])
    if not records:
        return None
    record = records[-1]
    sid = manifest["study_id"]
    root = workflow.location(sid)
    stale = False
    try:
        workflow.trial_binding(sid, record["payload"], manifest)
    except ContractError:
        stale = True
    path = within(root, record["progress_path"])
    progress = (
        read_json(path)
        if path.is_file()
        else {
            "state": "preparing",
            "pairs_done": 0,
            "pairs_total": 225,
            "regions_done": 0,
            "regions_total": 0,
            "step_zh": "正在固定准备输入",
        }
    )
    info = {
        "trial_id": record["trial_id"],
        "state": record["state"],
        "stale": stale,
        "enabled": not stale and not busy and not manifest.get("trashed"),
        "progress": progress,
        "matrix": None,
        "receptors": [],
        "downloads": [],
        "review": None,
        "note_zh": "独立扩展试算；Vina对接评分（kcal/mol），不是实测结合自由能。正式A06结果及批准保持。",
    }
    for rec in manifest.get("docking_trial_review_records", []):
        value = read_json(verified_file(root, rec))
        if value["trial_id"] == record["trial_id"]:
            info["review"] = value
    if record["state"] != "completed":
        return info
    for rec in record.get("files", []):
        verified_file(root, rec)
    packet = read_json(verified_file(root, record["packet"]))
    require(
        packet["study_id"] == sid and packet["trial_id"] == record["trial_id"],
        "试算研究绑定不一致",
    )
    for compound in packet["compounds"]:
        for rec in compound["files"]:
            verified_file(root, rec)
    for receptor in packet["receptors"]:
        if receptor["state"] == "ready":
            verified_file(root, receptor["receptor"])
            if receptor.get("source"):
                verified_file(root, receptor["source"])
    validate_matrix(packet)
    values = [p["score"] for p in packet["pairs"] if p["state"] == "completed"]
    low, high = (min(values), max(values)) if values else (None, None)
    pairmap = {(p["compound_id"], p["target_id"]): p for p in packet["pairs"]}
    info["summary"] = packet["summary"]
    info["receptors"] = [
        {
            k: r.get(k)
            for k in (
                "target_id",
                "symbol",
                "candidate_grade",
                "structure_id",
                "state",
                "mode",
                "processing_zh",
                "history_quality_zh",
                "history_rmsd_A",
                "repair",
                "reason_zh",
                "source",
                "spec",
                "regions",
                "environment",
                "attempts",
            )
        }
        for r in packet["receptors"]
    ]
    scope_records = [
        r
        for r in record.get("files", [])
        if r["path"].endswith("/processing_review.json")
    ]
    if scope_records:
        scope_map = {
            s["target_id"]: s for s in read_json(verified_file(root, scope_records[-1]))
        }
        for row in info["receptors"]:
            scope = scope_map.get(row["target_id"], {})
            if scope.get("source"):
                row["source"] = scope["source"]
            row["environment"] = {"original": row["environment"], "trial_scope": scope}
    info["matrix"] = {
        "columns": [
            {"id": r["target_id"], "label": r["symbol"], "grade": r["candidate_grade"]}
            for r in packet["receptors"]
        ],
        "rows": [],
        "score_range": [low, high] if values else None,
        "heatmap_compounds": packet["display"]["config"]["heatmap_compounds"],
        "heatmap_targets": packet["display"]["config"]["heatmap_targets"],
        "palette": PALETTE,
        "display_version": VERSION,
        "annotation_legend": LEGEND,
        "annotation_threshold": THRESHOLD,
    }
    for compound in packet["compounds"]:
        row = {"id": compound["compound_id"], "label": compound["name_zh"], "cells": []}
        for receptor in packet["receptors"]:
            pair = pairmap[(compound["compound_id"], receptor["target_id"])]
            row["cells"].append(
                {
                    "target_id": receptor["target_id"],
                    "score": pair["score"],
                    "display_score": score_label(pair["score"]),
                    "highlight": highlighted(pair["score"]),
                    "state": pair["state"],
                    "color": color(pair["score"], low, high),
                    "text_color": text_color(color(pair["score"], low, high)),
                    "reason_zh": pair["reason_zh"],
                    "region_id": pair["selected_region_id"],
                    "mode": pair["mode"],
                    "partial_regions": pair["partial_regions"],
                }
            )
        info["matrix"]["rows"].append(row)
    latest_export = next(
        (
            str(Path(r["path"]).parent)
            for r in reversed(record.get("files", []))
            if r["path"].endswith("/export_validation.json")
        ),
        None,
    )
    for i, rec in enumerate(record.get("files", [])):
        suffix = Path(rec["path"]).suffix.lower()
        if str(Path(rec["path"]).parent) == latest_export and suffix in {
            ".xlsx",
            ".csv",
            ".png",
            ".svg",
            ".docx",
        }:
            info["downloads"].append(
                {
                    "name": Path(rec["path"]).name,
                    "url": f"/api/v1/studies/{sid}/files/{record['trial_id']}.{i}",
                }
            )
    return info
