"""本机配置读取。

所有路径都从这里取得，代码其他地方不写死盘符、用户名或工具位置。
读取顺序（后者覆盖前者）：
1. 默认值：数据根目录 = 项目根目录；
2. config/local.toml（不提交到 git，记录本机路径）；
3. 环境变量 MODULEA_DATA_ROOT、MODULEA_SCIENCE_PYTHON、MODULEA_ALLOWED_ORIGINS；
4. 命令行参数（由 __main__ 传入）。
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# 项目根目录：本文件位于 <根>/src/modulea/config.py。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 旧科学内核所在目录（扁平模块），新架构通过它调用科学计算。
LEGACY_SRC = PROJECT_ROOT / "src"


@dataclass
class Settings:
    """一次启动使用的全部配置。"""

    project_root: Path = PROJECT_ROOT
    data_root: Path = PROJECT_ROOT  # studies/ 与 references/ 所在目录
    runtime_dir: Path = PROJECT_ROOT / ".runtime"  # 任务索引和服务日志，可删除
    science_python: str = sys.executable  # 后台科学任务使用的解释器
    allowed_origins: list[str] = field(default_factory=list)  # 允许跨源访问的前端开发地址
    static_dir: Path | None = None  # 预构建前端所在目录；为空时不提供静态页面

    @property
    def studies_dir(self) -> Path:
        return self.data_root / "studies"


def _read_local_toml(project_root: Path) -> dict:
    """读取 config/local.toml；文件不存在时返回空配置。"""
    path = project_root / "config" / "local.toml"
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_settings(**overrides) -> Settings:
    """按“默认值 → local.toml → 环境变量 → 命令行”的顺序合成配置。"""
    settings = Settings()
    local = _read_local_toml(settings.project_root)
    paths = local.get("paths", {})
    server = local.get("server", {})

    # local.toml 中的本机路径
    if paths.get("data_root"):
        settings.data_root = Path(paths["data_root"]).expanduser()
    if paths.get("science_python"):
        settings.science_python = paths["science_python"]
    if paths.get("static_dir"):
        settings.static_dir = Path(paths["static_dir"]).expanduser()
    settings.allowed_origins = list(server.get("allowed_origins", []))

    # 环境变量
    if os.environ.get("MODULEA_DATA_ROOT"):
        settings.data_root = Path(os.environ["MODULEA_DATA_ROOT"]).expanduser()
    if os.environ.get("MODULEA_SCIENCE_PYTHON"):
        settings.science_python = os.environ["MODULEA_SCIENCE_PYTHON"]
    if os.environ.get("MODULEA_ALLOWED_ORIGINS"):
        settings.allowed_origins = [o.strip() for o in os.environ["MODULEA_ALLOWED_ORIGINS"].split(",") if o.strip()]

    # 命令行参数（值为 None 表示未指定）
    for key, value in overrides.items():
        if value is None:
            continue
        if key in ("data_root", "static_dir", "runtime_dir"):
            value = Path(value).expanduser()
        if key == "allowed_origins" and isinstance(value, str):
            value = [o.strip() for o in value.split(",") if o.strip()]
        setattr(settings, key, value)

    settings.data_root = settings.data_root.resolve()
    settings.runtime_dir = settings.runtime_dir.resolve()
    return settings
