"""只在独立任务进程中管理其自身进程树；不操作其他任务或研究。"""
import os
import uuid

# 当前worker持有的非继承Job句柄保留到进程退出，不在Python析构时关闭并杀死自身。
_handles=[]


def _windows():
    """为64位句柄显式声明标准Windows API签名，避免默认int截断。"""
    import ctypes as c
    from ctypes import wintypes as w
    kernel=c.WinDLL('kernel32',use_last_error=True)
    signatures={
        'CreateJobObjectW':([c.c_void_p,w.LPCWSTR],w.HANDLE),
        'OpenJobObjectW':([w.DWORD,w.BOOL,w.LPCWSTR],w.HANDLE),
        'SetInformationJobObject':([w.HANDLE,c.c_int,c.c_void_p,w.DWORD],w.BOOL),
        'QueryInformationJobObject':([w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p],w.BOOL),
        'AssignProcessToJobObject':([w.HANDLE,w.HANDLE],w.BOOL),
        'GetCurrentProcess':([],w.HANDLE),'CloseHandle':([w.HANDLE],w.BOOL)}
    for name,(args,result) in signatures.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=result
    return c,w,kernel


def contain_current_worker():
    """科学执行前先约束worker及其后代；Windows异常退出由系统终止本Job后代。"""
    if os.name!='nt':
        if os.getpgrp()!=os.getpid():raise RuntimeError('任务进程必须具有独立进程组，尚未执行计算')
        return {'platform':'posix','pgid':os.getpid()}
    c,w,kernel=_windows()
    class Basic(c.Structure):
        _fields_=[('PerProcessUserTimeLimit',c.c_longlong),('PerJobUserTimeLimit',c.c_longlong),
                  ('LimitFlags',w.DWORD),('MinimumWorkingSetSize',c.c_size_t),('MaximumWorkingSetSize',c.c_size_t),
                  ('ActiveProcessLimit',w.DWORD),('Affinity',c.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
    class IO(c.Structure):
        _fields_=[(name,c.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(c.Structure):
        _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',c.c_size_t),('JobMemoryLimit',c.c_size_t),
                  ('PeakProcessMemoryUsed',c.c_size_t),('PeakJobMemoryUsed',c.c_size_t)]
    name='Local\\ModuleACompute_'+uuid.uuid4().hex
    handle=kernel.CreateJobObjectW(None,name)
    if not handle:raise c.WinError(c.get_last_error())
    try:
        limits=Extended();limits.BasicLimitInformation.LimitFlags=0x2000  # KILL_ON_JOB_CLOSE，无CPU/内存科学参数修改。
        if not kernel.SetInformationJobObject(handle,9,c.byref(limits),c.sizeof(limits)):raise c.WinError(c.get_last_error())
        if not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):raise c.WinError(c.get_last_error())
    except BaseException:
        kernel.CloseHandle(handle);raise
    _handles.append(handle)
    return {'platform':'windows','job_name':name}


def tree_alive(record):
    """只读实际进程组；权限/格式未知保守报错，不按旧PID猜测树已结束。"""
    if record.get('platform')=='posix' and os.name!='nt':
        pgid=record.get('pgid')
        if type(pgid) is not int or pgid<=0:raise ValueError('资源进程组记录无效')
        from .process_identity import group_members
        return bool(group_members(pgid))
    if record.get('platform')!='windows' or os.name!='nt':raise ValueError('无法核查原计算进程树的平台')
    name=record.get('job_name')
    import re
    if not isinstance(name,str) or not re.fullmatch(r'Local\\ModuleACompute_[0-9a-f]{32}',name):raise ValueError('资源Job记录无效')
    c,w,kernel=_windows();handle=kernel.OpenJobObjectW(4,False,name)  # 仅JOB_OBJECT_QUERY权限。
    if not handle:
        error=c.get_last_error()
        if error==2:return False
        raise c.WinError(error)
    class Accounting(c.Structure):
        _fields_=[(name,c.c_longlong) for name in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[
            (name,w.DWORD) for name in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]
    try:
        value=Accounting()
        if not kernel.QueryInformationJobObject(handle,1,c.byref(value),c.sizeof(value),None):raise c.WinError(c.get_last_error())
        return value.ActiveProcesses>0
    finally:kernel.CloseHandle(handle)
