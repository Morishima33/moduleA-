"""本机配置读取。

所有路径都从这里取得，代码其他地方不写死盘符、用户名或工具位置。
读取顺序（后者覆盖前者）：
1. 默认值：数据根目录 = 项目根目录；
2. config/local.toml（不提交到 git，记录本机路径）；
3. 环境变量 MODULEA_DATA_ROOT、MODULEA_RUNTIME_DIR、MODULEA_SCIENCE_PYTHON、MODULEA_ALLOWED_ORIGINS；
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
    science_tools_root: Path | None = None  # 只读固定对接依赖，不从浏览器接收路径
    science_repair_packages: Path | None = None  # 固定侧链修补依赖，由服务器配置
    allowed_origins: list[str] = field(default_factory=list)  # 允许跨源访问的前端开发地址
    static_dir: Path | None = None  # 预构建前端所在目录；为空时不提供静态页面
    science_rscript: Path | None = None  # 新字段追加末尾，保留旧位置参数构造兼容
    compute_slots: int = 1  # 同runtime重任务计算位，不改变各科学命令线程/参数
    compute_min_free_bytes: int = 16 * 1024 * 1024  # SQLite/日志基础运行余量，非科学产物估算

    def validate_resources(self):
        """服务器预算须为合法整数；不接受布尔值或静默截断小数。"""
        if type(self.compute_slots) is not int or not 1<=self.compute_slots<=32:
            raise ValueError('compute_slots须为1—32整数')
        if type(self.compute_min_free_bytes) is not int or self.compute_min_free_bytes<0:
            raise ValueError('compute_min_free_bytes须为非负整数字节')

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
    resources = local.get('resources', {})
    settings.compute_slots = resources.get('compute_slots', settings.compute_slots)
    settings.compute_min_free_bytes = resources.get('compute_min_free_bytes', settings.compute_min_free_bytes)

    # local.toml 中的本机路径
    if paths.get("data_root"):
        settings.data_root = Path(paths["data_root"]).expanduser()
    if paths.get("runtime_dir"):
        settings.runtime_dir = Path(paths["runtime_dir"]).expanduser()
    if paths.get("science_python"):
        settings.science_python = paths["science_python"]
    if paths.get("science_rscript"):
        settings.science_rscript = Path(paths["science_rscript"]).expanduser()
    if paths.get("science_tools_root"):
        settings.science_tools_root = Path(paths["science_tools_root"]).expanduser()
    if paths.get("science_repair_packages"):
        settings.science_repair_packages = Path(paths["science_repair_packages"]).expanduser()
    if paths.get("static_dir"):
        settings.static_dir = Path(paths["static_dir"]).expanduser()
    settings.allowed_origins = list(server.get("allowed_origins", []))

    # 环境变量
    for name,key in (('MODULEA_COMPUTE_SLOTS','compute_slots'),('MODULEA_COMPUTE_MIN_FREE_BYTES','compute_min_free_bytes')):
        if name in os.environ:setattr(settings,key,int(os.environ[name]))
    if os.environ.get("MODULEA_DATA_ROOT"):
        settings.data_root = Path(os.environ["MODULEA_DATA_ROOT"]).expanduser()
    if os.environ.get("MODULEA_RUNTIME_DIR"):
        settings.runtime_dir = Path(os.environ["MODULEA_RUNTIME_DIR"]).expanduser()
    if os.environ.get("MODULEA_SCIENCE_PYTHON"):
        settings.science_python = os.environ["MODULEA_SCIENCE_PYTHON"]
    if os.environ.get("MODULEA_RSCRIPT"):
        settings.science_rscript = Path(os.environ["MODULEA_RSCRIPT"]).expanduser()
    if os.environ.get("MODULEA_SCIENCE_TOOLS_ROOT"):
        settings.science_tools_root = Path(os.environ["MODULEA_SCIENCE_TOOLS_ROOT"]).expanduser()
    if os.environ.get("MODULEA_SCIENCE_REPAIR_PACKAGES"):
        settings.science_repair_packages = Path(os.environ["MODULEA_SCIENCE_REPAIR_PACKAGES"]).expanduser()
    if os.environ.get("MODULEA_ALLOWED_ORIGINS"):
        settings.allowed_origins = [o.strip() for o in os.environ["MODULEA_ALLOWED_ORIGINS"].split(",") if o.strip()]

    # 命令行参数（值为 None 表示未指定）
    for key, value in overrides.items():
        if value is None:
            continue
        if key in ("data_root", "static_dir", "runtime_dir", "science_tools_root", "science_repair_packages", "science_rscript"):
            value = Path(value).expanduser()
        if key == "allowed_origins" and isinstance(value, str):
            value = [o.strip() for o in value.split(",") if o.strip()]
        setattr(settings, key, value)

    settings.data_root = settings.data_root.resolve()
    settings.runtime_dir = settings.runtime_dir.resolve()
    settings.validate_resources()
    return settings
