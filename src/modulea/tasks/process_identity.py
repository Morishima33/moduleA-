"""任务进程出生标识与受限取消；PID复用或身份未知时不发送信号。"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def identity(pid):
    """只读操作系统出生标识；未知或权限不足返回None，不用PID猜测归属。"""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        if os.name == 'nt':
            import ctypes as c
            from ctypes import wintypes as w
            kernel=c.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
            kernel.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)];kernel.GetProcessTimes.restype=w.BOOL
            kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:return None
            try:
                created,exited,kernel_time,user_time=(w.FILETIME() for _ in range(4))
                if not kernel.GetProcessTimes(handle,c.byref(created),c.byref(exited),c.byref(kernel_time),c.byref(user_time)):
                    return None
                return {'platform':'windows','pid':pid,'birth':(created.dwHighDateTime<<32)|created.dwLowDateTime}
            finally:kernel.CloseHandle(handle)
        if sys.platform=='darwin':
            import ctypes as c
            # Apple公开proc_bsdinfo ABI；按完整结构大小读取，启动时间精确到微秒。
            class BSD(c.Structure):
                _fields_=[('prefix',c.c_uint32*12),('comm',c.c_char*16),('name',c.c_char*32),
                          ('nfiles',c.c_uint32),('pgid',c.c_uint32),('jobc',c.c_uint32),
                          ('tdev',c.c_uint32),('tpgid',c.c_uint32),('nice',c.c_int32),
                          ('seconds',c.c_uint64),('microseconds',c.c_uint64)]
            lib=c.CDLL('/usr/lib/libproc.dylib',use_errno=True)
            lib.proc_pidinfo.argtypes=[c.c_int,c.c_int,c.c_uint64,c.c_void_p,c.c_int]
            lib.proc_pidinfo.restype=c.c_int
            value=BSD()
            if lib.proc_pidinfo(pid,3,0,c.byref(value),c.sizeof(value))!=c.sizeof(value):return None
            if value.prefix[3]!=pid:return None
            return {'platform':'posix','pid':pid,'birth':[value.seconds,value.microseconds],'pgid':value.pgid}
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return {'platform':'posix','pid':pid,'birth':fields[19],'pgid':int(fields[2])}
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):
        return None


def group_members(pgid):
    """实际枚举独立组成员；macOS不以killpg(0)的EPERM猜测空组仍存活。"""
    if sys.platform=='darwin':
        import ctypes as c
        lib=c.CDLL('/usr/lib/libproc.dylib',use_errno=True)
        lib.proc_listpids.argtypes=[c.c_uint32,c.c_uint32,c.c_void_p,c.c_int]
        lib.proc_listpids.restype=c.c_int
        capacity=64
        while capacity<=1048576:
            pids=(c.c_int*capacity)()
            count=lib.proc_listpids(2,pgid,pids,c.sizeof(pids))
            if count<0:raise OSError(c.get_errno(),'无法枚举本任务进程组')
            if count<c.sizeof(pids):
                members=[]
                lib.proc_pidinfo.argtypes=[c.c_int,c.c_int,c.c_uint64,c.c_void_p,c.c_int]
                lib.proc_pidinfo.restype=c.c_int
                for pid in pids[:count//c.sizeof(c.c_int)]:
                    if pid<=0:continue
                    raw=c.create_string_buffer(136)
                    used=lib.proc_pidinfo(pid,3,0,raw,len(raw))
                    if used==136:
                        # BSD SZOMB=5；已退出但尚待父进程wait的僵尸不占计算资源，也不能再发信号。
                        if c.cast(raw,c.POINTER(c.c_uint32))[1]!=5:members.append(pid)
                    elif c.get_errno() not in (0,3):
                        raise OSError(c.get_errno(),'无法核对本任务组成员')
                return members
            capacity*=2
        raise ValueError('任务组成员数量异常')
    values=[]
    for folder in Path('/proc').iterdir():
        if folder.name.isdigit():
            value=identity(int(folder.name))
            if value and value.get('pgid')==pgid:values.append(int(folder.name))
    return values


def terminate_owned(pid, expected):
    """只结束身份仍一致的任务树；POSIX先TERM再处理拒绝退出的本组后代。"""
    if not expected or identity(pid)!=expected:
        raise ValueError('无法核对本任务进程身份，未发送取消信号；请检查本任务日志')
    if os.name=='nt':
        result=subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=10)
        if result.returncode and identity(pid)==expected:
            raise ValueError('Windows未能确认本任务进程树已结束')
        return
    if expected.get('pgid')!=pid or os.getpgid(pid)!=pid or pid==os.getpgrp():
        raise ValueError('本任务没有独立进程组，拒绝取消可能涉及其他进程')
    os.killpg(pid,signal.SIGTERM)
    until=time.monotonic()+2
    while time.monotonic()<until:
        if not group_members(pid):return
        time.sleep(.05)
    try:os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError:pass
