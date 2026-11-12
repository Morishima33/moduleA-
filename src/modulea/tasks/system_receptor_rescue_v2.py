"""第二轮受体补救隔离worker；共享队列和资源登记由后续显式集成。"""
from types import FunctionType
from . import system_receptor_rescue as frozen


def run(settings, task, manager):
    """原预算和进程取消实现照用，仅选择独立第二轮脚本及runtime目录。"""
    return _run(_SettingsView(settings), task, manager)


class _ProjectView:
    """只在本worker选择新脚本，避免改变已固定第一轮工具或配置对象。"""
    def __init__(self, root):
        self.root = root

    def __truediv__(self, relative):
        return self.root / ('tools/run_system_receptor_rescue_v2.py' if relative == 'tools/run_system_receptor_rescue.py' else relative)


class _SettingsView:
    """服务器原配置只读透传；第二轮请求目录与第一轮独立。"""
    def __init__(self, settings):
        self.original = settings
        self.project_root = _ProjectView(settings.project_root)
        self.runtime_dir = settings.runtime_dir / 'receptor_rescue_v2'

    def __getattr__(self, name):
        return getattr(self.original, name)


# 只复用第一轮函数原code和真实依赖，不改其globals、不替换模块或任务表。
_run = FunctionType(frozen.run.__code__, dict(vars(frozen)), frozen.run.__name__, frozen.run.__defaults__)
