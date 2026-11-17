"""只补统一启动子进程缺失的真实Windows架构元数据，不修改父进程或系统。"""
import sys


def _native_windows_architecture():
    """独立读GetNativeSystemInfo；不能用缺失环境变量或Python位数猜测主机。"""
    import ctypes
    class SystemInfo(ctypes.Structure):
        _fields_=[('architecture',ctypes.c_ushort),('reserved',ctypes.c_ushort),('page_size',ctypes.c_ulong),
            ('minimum',ctypes.c_void_p),('maximum',ctypes.c_void_p),('mask',ctypes.c_size_t),
            ('processors',ctypes.c_ulong),('processor_type',ctypes.c_ulong),('allocation',ctypes.c_ulong),
            ('level',ctypes.c_ushort),('revision',ctypes.c_ushort)]
    info=SystemInfo()
    read=ctypes.WinDLL('kernel32',use_last_error=True).GetNativeSystemInfo
    read.argtypes=[ctypes.POINTER(SystemInfo)];read.restype=None
    read(ctypes.byref(info))
    if info.processors<=0 or info.page_size<=0:
        raise ValueError('无法完整核实Windows主机架构，未启动工作台')
    names={0:'x86',5:'ARM',9:'AMD64',12:'ARM64'}
    if info.architecture not in names:
        raise ValueError('Windows主机架构编号未支持：'+str(info.architecture)+'；未猜测或启动工作台')
    return names[info.architecture]


def child_environment(base,*,platform_name=None):
    """返回独立副本；已有值保持，只有Windows缺失/空白时补回实测值。"""
    result=dict(base)
    if (sys.platform if platform_name is None else platform_name)!='win32':return result
    value=result.get('PROCESSOR_ARCHITECTURE')
    if value and value.strip():return result
    result['PROCESSOR_ARCHITECTURE']=_native_windows_architecture()
    return result
