"""同批试算导出及实际渲染入口；运行时路径来自独立配置，不写死个人环境。"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))


def execute(command, folder, name, environment=None):
    """外部导出和渲染完整留日志，失败不发布不完整产物。"""
    result = subprocess.run(
        command,
        cwd=folder,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    (folder / (name + ".log")).write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    if result.returncode:
        raise ValueError(name + "失败，详见独立核验日志")


def main():
    """Excel/CSV/PNG/专业版补充来自同一包，发布前核对225格和报告原值。"""
    parser = argparse.ArgumentParser()
    for name in ("data-root", "runtime-config", "qa-directory", "processing-evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--trial", required=True)
    args = parser.parse_args()
    from uuid import uuid4

    from contracts import safe_id
    from modulea.config import Settings
    from modulea.core.kernel import Kernel
    from science_modules.a06.trial_exports import (
        append_professional_trial,
        create_export_data,
    )
    from storage import file_record, read_json, verified_file, write_json

    safe_id(args.study, "study")
    safe_id(args.trial, "trial")
    config = read_json(args.runtime_config)
    workflow = Kernel(Settings(data_root=args.data_root)).workflow()
    manifest = workflow.load(args.study)
    records = [
        r
        for r in manifest.get("docking_trial_records", [])
        if r["trial_id"] == args.trial
    ]
    if len(records) != 1 or records[0]["state"] != "completed":
        raise ValueError("必须为已完成的独立试算")
    root = workflow.location(args.study)
    original = read_json(verified_file(root, records[0]["packet"]))
    packet = deepcopy(original)
    scopes = read_json(args.processing_evidence)
    if {r["target_id"] for r in scopes} != {
        r["target_id"] for r in packet["receptors"]
    }:
        raise ValueError("处理核验资料与同批十五受体不一致")
    scope_map = {s["target_id"]: s for s in scopes}
    for row in packet["receptors"]:
        scope = scope_map[row["target_id"]]
        if scope.get("source"):
            verified_file(root, scope["source"])
        observed = scope.get("canonical_observed_positions", [])
        range_note = (
            "；所选结构已解析UniProt位置"
            + str(min(observed))
            + "～"
            + str(max(observed))
            if observed
            else ""
        )
        row["processing_zh"] = (
            row.get("processing_zh", row.get("reason_zh", "")) + range_note
        )
    qa = args.qa_directory.resolve()
    qa.mkdir(parents=True, exist_ok=True)
    export_dir = (
        root / "runs/A06_TRIAL" / args.trial / "exports" / ("display_" + uuid4().hex)
    )
    create_export_data(packet, export_dir)
    write_json(export_dir / "processing_review.json", scopes)
    builder = qa / "exporter.mjs"
    shutil.copy2(CODE / "tools/export_a06_trial.mjs", builder)
    junction = qa / "node_modules"
    if not junction.exists():
        if os.name == "nt":
            execute(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(Path(config["artifact_modules"]).resolve()),
                ],
                qa,
                "node-junction",
            )
        else:
            junction.symlink_to(config["artifact_modules"], target_is_directory=True)
    if config.get("xlsx_marker") and not (qa / "xlsx-marker.done").exists():
        execute(
            [
                config["node"],
                config["xlsx_marker"],
                "--operation-kind",
                "create",
                "--expected-output-count",
                "1",
                "--output-format",
                "xlsx",
            ],
            qa,
            "xlsx-marker",
        )
        (qa / "xlsx-marker.done").write_text("success", encoding="ascii")
    xlsx = export_dir / "15×15结合能试算表.xlsx"
    execute(
        [
            config["node"],
            str(builder),
            str(export_dir / "excel_input.json"),
            str(xlsx),
            str(qa),
        ],
        qa,
        "xlsx-author",
    )

    # openpyxl仅核读Artifact Tool输出，不用于创建或编辑工作簿。
    from openpyxl import load_workbook

    book = load_workbook(xlsx, data_only=True)
    data = read_json(export_dir / "excel_input.json")
    actual = [
        [book["15×15试算"].cell(i + 6, j + 1).value for j in range(16)]
        for i in range(15)
    ]
    if actual != data["matrix_rows"]:
        raise ValueError("保存后的Excel与实际225格原值不一致")
    book.close()
    if config.get("docx_marker") and not (qa / "docx-marker.done").exists():
        execute(
            [
                config["node"],
                config["docx_marker"],
                "--operation-kind",
                "create",
                "--expected-output-count",
                "1",
                "--output-format",
                "docx",
            ],
            qa,
            "docx-marker",
        )
        (qa / "docx-marker.done").write_text("success", encoding="ascii")
    from docx import Document
    from docx.shared import Pt, RGBColor

    document = Document()
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        document.styles[name].font.name = "Microsoft YaHei"
        document.styles[name].font.color.rgb = RGBColor(0, 0, 0)
    document.styles["Normal"].font.size = Pt(10)
    document.styles["Normal"].paragraph_format.space_after = Pt(5)
    append_professional_trial(
        document, packet, export_dir / "A06_01_重点结合能热图.png"
    )
    docx = export_dir / "A06扩展试算专业报告补充.docx"
    document.save(docx)
    saved = Document(docx)
    score_tables = [t for t in saved.tables if len(t.columns) == 16]
    expected = [
        [r[0]] + ["NA" if v == "NA" else f"{v:.2f}" for v in r[1:]]
        for r in data["matrix_rows"]
    ]
    if (
        len(score_tables) != 1
        or [[c.text for c in r.cells] for r in score_tables[0].rows[1:]] != expected
    ):
        raise ValueError("专业版横向表与同批225格不一致")
    env = dict(
        os.environ,
        PATH=config["soffice_directory"]
        + os.pathsep
        + config["poppler_directory"]
        + os.pathsep
        + os.environ.get("PATH", ""),
        TEMP=str(qa),
        TMP=str(qa),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    execute(
        [
            sys.executable,
            "-B",
            config["document_renderer"],
            str(docx),
            "--output_dir",
            str(qa / "document-pages"),
            "--emit_pdf",
        ],
        qa,
        "docx-render",
        env,
    )
    proof = {
        "trial_id": args.trial,
        "display_version": "A06.trial.display.1",
        "matrix_cells_checked": 225,
        "xlsx_raw_precision_matches": True,
        "professional_table_matches": True,
        "source_packet": records[0]["packet"],
        "visual_inspection_pending": True,
    }
    write_json(export_dir / "export_validation.json", proof)
    (qa / "export-result.json").write_text(
        json.dumps(
            {
                "directory": str(export_dir),
                "xlsx": str(xlsx),
                "docx": str(docx),
                "csv": str(export_dir / "15×15结合能试算表.csv"),
                "proof": proof,
                "publishing_pending_visual_review": True,
                "files": [
                    file_record(root, p, "trial_export")
                    for p in export_dir.iterdir()
                    if p.is_file()
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"export_directory": str(export_dir), "cells_checked": 225},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
