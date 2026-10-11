"""A05运行适配：定位本仓库R脚本，复用冻结ORA、来源归档与校验，不改统计规则。"""

import json
from pathlib import Path
import subprocess
import tempfile
from types import FunctionType

from contracts import ContractError, require
from storage import read_json
import enrichment_flow as legacy

# 工具环境保持现状；脚本属于代码根，输入输出仅位于调用方的数据根。
CONFIG = legacy.CONFIG
RSCRIPT = legacy.RSCRIPT
R_SOURCE = Path(legacy.__file__).resolve().with_name("enrichment.R")
RUNTIME_RULE = "A05.separate_roots.1"


# 用绝对代码路径启动R；版本检查和ORA始终由原R文件执行。
def r_call(root, mode, value):
    require(mode in ("export", "analyze"), "未知A05运行模式")
    require(R_SOURCE.is_file(), "本仓库A05 R脚本缺失，请核对代码安装")
    work = Path(root).resolve() / "environments"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="a05_", dir=work) as folder:
        directory = Path(folder)
        source, dest = directory / "input.json", directory / "output.json"
        source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        try:
            process = subprocess.run(
                [str(RSCRIPT), "--vanilla", str(R_SOURCE), mode, "input.json", "output.json"],
                cwd=directory, capture_output=True, timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ContractError("A05的R计算未完成；请核对本机固定环境或稍后重试") from error
        # 部分R启动错误写在标准输出，两路均保留，不能只给出空白失败提示。
        log = process.stdout.decode("utf-8", errors="replace") + process.stderr.decode("utf-8", errors="replace")
        require(process.returncode == 0 and dest.is_file(), "A05计算失败：" + (log[-1500:] or "R未生成完整输出文件"))
        return read_json(dest), log


# 仅替换每次调用的R启动函数，冻结模块的全局函数和统计配置不修改。
def _bound():
    context = dict(vars(legacy), r_call=r_call)
    for name in ("source_snapshot", "evaluate", "validator", "run_enrichment"):
        original = getattr(legacy, name)
        context[name] = FunctionType(original.__code__, context, original.__name__, original.__defaults__, original.__closure__)
    return context


# 首次来源发布确保参考目录存在；既有来源索引仍按原规则核验并复用。
def source_snapshot(root):
    root = Path(root)
    (root / "references").mkdir(parents=True, exist_ok=True)
    return _bound()["source_snapshot"](root)


# 生产及复算使用同一绝对路径R入口，统计结果仍按冻结evaluate生成。
def evaluate(root, targets, source, hgnc_raw, purpose):
    return _bound()["evaluate"](Path(root), targets, source, hgnc_raw, purpose)


# 已归档A05.1仍按原配置、原始注释和原输入独立复算。
def validator(root):
    return _bound()["validator"](Path(root))


# 发布链复用冻结实现；补齐首次来源目录，结果依旧待人工复核。
def run_enrichment(workflow, sid, a03, a05, reason):
    context = _bound()
    context["source_snapshot"] = source_snapshot
    return context["run_enrichment"](workflow, sid, a03, a05, reason)
