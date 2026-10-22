"""跨电脑只读预检：核对代码身份、配置路径和科学依据，不下载、安装或修改研究。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# 文件名与现有加载器一致；检查存在性和指纹不等于研究来源完整。
REFERENCE_FILES = (
    ("tcmsp", "TCMSP共享快照", "tcmsp_snapshot.tsv", "tcmsp_snapshot.json"),
    ("hgnc", "HGNC身份快照", "hgnc_complete_set_20260913.tsv", "hgnc_complete_set_20260913.json"),
    ("ncbi_info", "NCBI人类基因补充依据", "ncbi_human_gene_info_20260913.gz", "ncbi_human_gene_info_20260913.json"),
    ("ncbi_history", "NCBI历史编号补充依据", "ncbi_human_gene_history_20260913.tsv", "ncbi_human_gene_history_20260913.json"),
    ("identity_queries", "官方身份查询补充依据", "identity_queries_20260913_v3.json", "identity_queries_20260913_v3_manifest.json"),
)


def _git(root: Path, *args: str) -> str:
    """仅运行固定的只读Git命令；缺Git、超时、非仓库不伪造提交号。"""
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=3, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise ValueError("无法读取当前代码的Git身份")
    return result.stdout.strip()


def code_identity(project_root: Path) -> dict:
    """确认目标本身就是代码仓库，避免把上层其他工程的版本误报为本项目版本。"""
    root = Path(project_root).resolve()
    result = {"status": "unknown", "label_zh": "代码版本未核实", "commit": None,
              "branch": None, "dirty": None}
    try:
        if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError("代码目录不是当前仓库根目录")
        commit = _git(root, "rev-parse", "HEAD")
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise ValueError("Git提交号格式不完整")
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal"))
        result.update(status="verified", label_zh="已读取本机实际代码版本", commit=commit,
                      branch=branch, dirty=dirty)
        if dirty:
            result["note_zh"] = "工作区存在未提交内容，运行代码可能与该提交不同；应同时核对工作区。"
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        result["note_zh"] = "未取得可靠提交号（" + type(error).__name__ + "）；不会把未知版本当作已同步。"
    return result


def reference_status(data_root: Path, spec: tuple) -> dict:
    """流式校验当前配置目录中的原件及固定清单，不从代码仓库或其他研究补齐。"""
    key, label, filename, manifest_name = spec
    folder = Path(data_root) / "references"
    source, manifest = folder / filename, folder / manifest_name
    record = {"id": key, "label_zh": label, "status": "missing", "filename": filename,
              "manifest": manifest_name, "sha256": None, "bytes": None}
    missing = [path.name for path in (source, manifest) if not path.is_file()]
    if missing:
        record.update(missing_files=missing, detail_zh="缺少：" + "、".join(missing) + "；不是零条结果。")
        return record
    try:
        if manifest.stat().st_size > 1024 * 1024:
            raise ValueError("来源清单体积异常")
        meta = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if (not isinstance(meta, dict) or type(meta.get("bytes")) is not int
                or meta["bytes"] <= 0 or not isinstance(meta.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"])):
            raise ValueError("来源清单缺少有效字节数或SHA-256")
        digest, count = hashlib.sha256(), 0
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                count += len(block)
        record.update(sha256=digest.hexdigest(), bytes=count)
        if count != meta["bytes"] or record["sha256"] != meta["sha256"]:
            record.update(status="invalid", detail_zh="原件与来源清单指纹不一致，须核查，不能用于计算。")
        else:
            record.update(status="verified", detail_zh="原件与清单指纹一致；药味覆盖及科学内容仍须本研究解析核验。")
    except (OSError, ValueError, TypeError) as error:
        record.update(status="invalid", detail_zh="无法完整核验来源（" + type(error).__name__ + "），不能作为就绪依据。")
    return record


def inspect_environment(settings, *, science_probe: dict | None = None) -> dict:
    """供doctor或按需页面调用；可传入实际科学解释器探测结果，默认不启动子进程探测依赖。"""
    data_root = Path(settings.data_root).resolve()
    checks = [reference_status(data_root, spec) for spec in REFERENCE_FILES]
    dependencies = {"status": "not_checked", "detail_zh": "尚未探测配置的科学解释器；网页可只读查看，不代表后台依赖已齐备。"}
    if science_probe is not None:
        dependencies = {"status": "verified" if science_probe.get("passed") is True else "unavailable",
                        "detail_zh": "科学解释器探测通过。" if science_probe.get("passed") is True else science_probe.get("error_zh", "科学解释器或依赖未齐备，仅影响后台执行。"),
                        "probe": science_probe}
    return {
        "version": "ModuleA.environment_preflight.1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "code": code_identity(settings.project_root),
        "paths": {"project_root": str(Path(settings.project_root).resolve()), "data_root": str(data_root),
                  "runtime_dir": str(Path(settings.runtime_dir).resolve()),
                  "science_python": str(settings.science_python)},
        "studies_directory_exists": (data_root / "studies").is_dir(),
        "references": checks,
        "shared_references_verified": all(row["status"] == "verified" for row in checks),
        "science": dependencies,
        "three_source_status": "not_assessed",
        "note_zh": "GitHub代码不包含实际研究原件、个人配置及科学环境。共享参考通过不等于本研究三库完整；HERB、BATMAN和各药味覆盖须在A01逐项核验。预检不获取来源、不改A02、不改变任何复核。",
    }
