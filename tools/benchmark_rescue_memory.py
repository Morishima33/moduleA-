"""隔离合成检查点内存/读取基准；不读取或写入真实研究，不执行科学工具。"""
import argparse
import gc
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from contracts import fingerprint
import storage
from modulea.core import bounded_evidence as bounded
from modulea.core.read_evidence import read_evidence_scope
from modulea.core.system_receptor_rescue_v2 import read_checkpoint, CHECKPOINTS, VERSION
from modulea.core.worker_io import WorkerIO


def peak_rss():
    """报告实际平台峰值常驻内存，Windows使用只读进程统计，Unix单位显式转换。"""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        process = ctypes.WinDLL('kernel32').GetCurrentProcess
        process.restype = wintypes.HANDLE
        value = Counters();value.cb=ctypes.sizeof(value)
        function=ctypes.WinDLL('psapi').GetProcessMemoryInfo
        function.argtypes=(wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD)
        if not function(process(),ctypes.byref(value),value.cb):raise ctypes.WinError()
        return value.PeakWorkingSetSize
    import resource
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform=='darwin' else value*1024)


def main(argv=None):
    """每次一个独立进程测一种模式，输出可审计JSON；GC保持默认启用。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('binary-old','binary-bounded','scope-old','scope-bounded','checkpoint-old','checkpoint-bounded'))
    parser.add_argument('--objects',type=int,default=111)
    parser.add_argument('--payload-kib',type=int,default=256)
    parser.add_argument('--binary-mib',type=int,default=64)
    args=parser.parse_args(argv)
    with TemporaryDirectory(prefix='ModuleA_memory_fixture_') as temp:
        root=Path(temp);sid='study_'+'a'*32;rid='run_'+'b'*32
        home=root/'studies'/sid;home.mkdir(parents=True)
        (home/'manifest.json').write_text('{}')
        refs=[];run={'run_id':rid,'module_id':'A06','config':{'version':VERSION},'config_hash':fingerprint({})}
        for i in range(args.objects if not args.mode.startswith('binary') else 0):
            key=f'pair_{i+1:06d}_region_0001'
            p=home/f'runs/A06/{rid}/rescue_checkpoints/{key}/checkpoint.json'
            storage.write_json(p,dict(schema_version=VERSION,study_id=sid,run_id=rid,key=key,
                config_hash=run['config_hash'],payload={'state':'completed','padding':'x'*(args.payload_kib*1024)},
                files=[],previous=None,human_review_written=False))
            refs.append(storage.file_record(home,p,'checkpoint'))
        manifest={'study_id':sid,CHECKPOINTS:refs}
        workflow=SimpleNamespace(root=root,load=lambda _:manifest,run=lambda *_:run,location=lambda _:home)
        binary=home/'large.bin'
        if args.mode.startswith('binary'):
            with binary.open('wb') as stream:
                for _ in range(args.binary_mib):stream.write(b'x'*1024*1024)
            reference=bounded.file_record(home,binary,'large')
        gc.collect()
        parses=0
        old_loads=json.loads
        def counted(*a,**kw):
            """仅统计JSON解析次数；不替代内容或结果。"""
            nonlocal parses
            parses+=1;return old_loads(*a,**kw)
        tracemalloc.start();start=time.perf_counter();stats={}
        with patch('json.loads',counted):
            if args.mode.startswith('binary'):
                (storage.verified_file if args.mode.endswith('old') else bounded.verified_file)(home,reference)
            elif args.mode.startswith('scope'):
                context=read_evidence_scope if args.mode.endswith('old') else bounded.bounded_scope
                with context(root,sid) as evidence:
                    for ref in refs:evidence.reader.read(home,ref)
                    stats={'cached_raw_bytes':sum(map(len,evidence.json_bytes.values())),
                           'cached_marshal_bytes':sum(map(len,evidence.parsed.values())),
                           'bounded_cache_bytes':getattr(evidence,'cache_size',None)}
            else:
                adapter=WorkerIO()
                for i in range(args.objects):
                    key=f'pair_{i+1:06d}_region_0001'
                    if args.mode.endswith('old'):read_checkpoint(workflow,sid,rid,key)
                    else:adapter.read_checkpoint(workflow,sid,rid,key,VERSION,CHECKPOINTS)
                stats=dict(adapter.stats);adapter.close()
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        print(json.dumps(dict(mode=args.mode,objects=args.objects,payload_kib=args.payload_kib,
            binary_mib=args.binary_mib,json_parses=parses,python_peak_bytes=peak,rss_peak_bytes=peak_rss(),
            seconds=time.perf_counter()-start,python=sys.version,platform=sys.platform,pointer_bits=8*struct.calcsize('P'),
            gc_enabled=gc.isenabled(),stats=stats,synthetic_only=True,scientific_tools_executed=False),ensure_ascii=False))


if __name__=='__main__':main()
