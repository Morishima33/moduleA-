"""启动进程与实际服务的只读归属核验；不改解释器、权限或服务生命周期。"""
import os
from .tasks.process_identity import identity


def _windows_parent(pid):
    """用公开Toolhelp快照查询父PID；不发送信号，不依赖PowerShell或第三方库。"""
    import ctypes as c
    from ctypes import wintypes as w
    class Entry(c.Structure):
        """对应公开PROCESSENTRY32W，堆指针使用本进程指针宽度。"""
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                    ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD), ('cntThreads', w.DWORD),
                    ('th32ParentProcessID', w.DWORD), ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD),
                    ('szExeFile', w.WCHAR*260)]
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.Process32FirstW.restype = w.BOOL
    kernel.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.Process32NextW.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS。
    if snapshot == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        entry = Entry(); entry.dwSize = c.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, c.byref(entry))
        while present:
            if entry.th32ProcessID == pid:
                return int(entry.th32ParentProcessID)
            present = kernel.Process32NextW(snapshot, c.byref(entry))
        if c.get_last_error() not in (0, 18):  # ERROR_NO_MORE_FILES。
            raise c.WinError(c.get_last_error())
        return None
    finally:
        kernel.CloseHandle(snapshot)


def owns_service_process(process, started, service_pid):
    """同一出生的启动进程或其稳定Windows直接子进程才可认领健康接口PID。"""
    try:
        if (type(service_pid) is not int or service_pid <= 0 or not isinstance(started, dict)
                or started.get('pid') != process.pid or process.poll() is not None
                or identity(process.pid) != started):
            return False
        if service_pid == process.pid:
            return identity(process.pid) == started and process.poll() is None
        if os.name != 'nt':
            return False
        child = identity(service_pid)
        return bool(child and child.get('platform') == started.get('platform') == 'windows'
                    and type(child.get('birth')) is int and type(started.get('birth')) is int
                    and child['birth'] >= started['birth'] and _windows_parent(service_pid) == process.pid
                    and identity(process.pid) == started and identity(service_pid) == child
                    and process.poll() is None)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
