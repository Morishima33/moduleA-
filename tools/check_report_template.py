"""只读核对第24版模板及直接排版依赖的固定指纹，不访问研究或修改文件。"""

import argparse
import hashlib
import json
from pathlib import Path


def check(root):
    """从仓库内的固定清单检查每个文件，拒绝越界路径、缺失及内容漂移。"""
    root = Path(root).resolve()
    manifest = root / "templates/A07.double_report.24.lock.json"
    lock = json.loads(manifest.read_text(encoding="utf-8"))
    errors = []
    for record in lock["files"]:
        path = (root / record["path"]).resolve()
        if not path.is_relative_to(root):
            errors.append({"path": record["path"], "reason_zh": "路径超出代码仓库"})
        elif not path.is_file():
            errors.append({"path": record["path"], "reason_zh": "固定文件缺失"})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            errors.append({"path": record["path"], "reason_zh": "内容与固定版本不同"})
    return {
        "passed": not errors,
        "template_version": lock["template_version"],
        "checked_files": len(lock["files"]),
        "errors": errors,
    }


def main():
    """默认检查工具所在仓库；--root仅用于显式指定其他只读代码副本。"""
    parser = argparse.ArgumentParser(description="检查第24版报告模板固定指纹")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
