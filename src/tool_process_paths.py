"""工具进程的同文件系统路径映射；不复制输入、不修改系统设置。"""
import ctypes
import os
from pathlib import Path

WINDOWS = os.name == 'nt'
LIMIT = 240


# 工具边界预留文件名空间；短路径与普通平台保持原样。
def needs_short_name(path):
    return WINDOWS and len(str(path)) >= LIMIT


# 只请求系统已有的短名；未启用短名时明确失败，不另建链接或副本。
def _short_name(path):
    function = ctypes.windll.kernel32.GetShortPathNameW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    count = function(str(path), buffer, len(buffer))
    if not 0 < count < len(buffer):
        raise ValueError('工具长路径无法取得系统已有短名')
    return buffer.value


# 每个已存在输入和工作目录必须映射回同一物理对象，不能只比较字符串。
def existing(path):
    original = Path(path).resolve()
    if not original.exists():
        raise ValueError('工具输入或工作目录不存在：' + str(original))
    if not needs_short_name(original):
        return str(original)
    short = _short_name(original)
    if len(short) >= LIMIT or Path(short).resolve() != original or not os.path.samefile(short, original):
        raise ValueError('工具短路径未缩短或不对应同一原始对象')
    return short


# 单个输出名必须保持精确文件名，拒绝路径穿越和Windows歧义名称。
def filename(name):
    if (not isinstance(name, str) or not name or name in ('.', '..') or
            name[-1:] in ('.', ' ') or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)):
        raise ValueError('工具输出文件名不合法')
    return name


# 尚不存在的输出只映射已存在父目录，文件名不变且不提前创建文件。
def output(path):
    original = Path(path).absolute()
    filename(original.name)
    if original.exists():
        return existing(original)
    parent = original.parent.resolve()
    mapped = Path(existing(parent)) / original.name
    if mapped.parent.resolve() != parent or (WINDOWS and len(str(mapped)) >= LIMIT):
        raise ValueError('工具输出路径未缩短或离开原输出目录')
    return str(mapped)
