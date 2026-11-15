"""有界的完整原件读取：独立适配，不修改被历史运行绑定的存储和读取实现。"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
import marshal
import os
from pathlib import Path

from contracts import ContractError, require
from . import read_evidence as frozen
from .rescue_read_evidence import RescueReadEvidence

VERSION = 'ModuleA.bounded_evidence.1'
CHUNK = 1024 * 1024


def digest_file(path):
    """单句柄分块核完整长度和SHA；句柄与路径身份前后必须一致。"""
    path = Path(path)
    before = path.stat()
    signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        require(signature(opened) == signature(before), '原件打开期间发生变化')
        for raw in iter(lambda: stream.read(CHUNK), b''):
            size += len(raw)
            digest.update(raw)
        require(signature(os.fstat(stream.fileno())) == signature(opened), '原件读取期间发生变化')
    require(signature(path.stat()) == signature(before), '原件路径读取期间发生变化')
    return size, digest.hexdigest()


def verified_file(root, record):
    """完整核验的流式等价实现；无TTL、mtime快捷通过或跨调用指纹缓存。"""
    from storage import within
    require(isinstance(record, dict), '文件索引缺失')
    path = within(root, record.get('path', ''))
    require(path.is_file(), '归档文件缺失')
    size, digest = digest_file(path)
    require((size, digest) == (record.get('bytes'), record.get('sha256')),
            '归档文件校验失败，暂停使用')
    return path


def file_record(root, path, role):
    """归档记录只改变内存占用，路径、字节数、SHA和角色与冻结实现一致。"""
    path = Path(path).resolve()
    relative = path.relative_to(Path(root).resolve()).as_posix()
    size, digest = digest_file(path)
    return {'path': relative, 'sha256': digest, 'bytes': size, 'role': role}


def read_verified_json(root, record):
    """解析的必须是SHA对应的同份字节；不把先核后读的另一份数据当原件。"""
    path = verified_file(root, record)
    raw = path.read_bytes()
    require(len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'],
            'JSON解析期间原件已改变')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ContractError('数据文件缺失或损坏：' + path.name) from error


class BoundedEvidence(RescueReadEvidence):
    """原首次/退出全SHA和路径规则照用；JSON缓存只留固定预算的marshal字节。"""
    def __init__(self, *args, cache_bytes=2 * 1024 * 1024, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_limit = cache_bytes
        self.cache = OrderedDict()
        self.cache_size = self.cache_peak = 0
        self.stats.update(json_parses=0, json_cache_hits=0)

    def _capture(self, home, record, *, force_json=False):
        """核验JSON也采用流式SHA，避免只为验证就保留全部JSON原文。"""
        key = self._key(home, record)
        path = self.raw_reader.verify(home, record)
        with self.lock:
            self.proofs[key] = (home, dict(record), path)
            self.by_path[path] = key
            self.request_paths[home / record['path']] = path
            self.stats['first_sha_checks'] += 1
            self.stats['first_bytes_hashed'] += record['bytes']
        return path

    def read_json(self, path):
        """逐文档解析，缓存有界；即使已核过路径，解析字节也再次匹配原SHA。"""
        if not self._owned():
            return frozen.original_read_json(path)
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root):
            return frozen.original_read_json(path)
        key = self.by_path.get(resolved)
        if key is None:
            record = file_record(self.root, resolved, 'request_json')
            self._capture(self.root, record)
            key = self.by_path[resolved]
        if key in self.cache:
            self.stats['json_cache_hits'] += 1
            self.cache.move_to_end(key)
            return marshal.loads(self.cache[key])
        # 标准库JSON解析的瞬时上界仍与单件JSON大小有关，绝不长期持有全部文档。
        try:
            raw = resolved.read_bytes()
            require(len(raw) == key[2] and hashlib.sha256(raw).hexdigest() == key[3],
                    'JSON解析期间原件已改变')
            value = json.loads(raw)
        except (OSError, ValueError, UnicodeError) as error:
            raise ContractError('数据文件缺失或损坏：' + resolved.name) from error
        self.stats['json_parses'] += 1
        packed = marshal.dumps(value)
        if len(packed) <= self.cache_limit:
            while self.cache and self.cache_size + len(packed) > self.cache_limit:
                _, evicted = self.cache.popitem(last=False)
                self.cache_size -= len(evicted)
            self.cache[key] = packed
            self.cache_size += len(packed)
            self.cache_peak = max(self.cache_peak, self.cache_size)
        return value

    def close(self):
        """解除reader/函数namespace闭环，结束即释放内容，不等循环GC触发。"""
        self.cache.clear()
        self.cache_size = 0
        for name in ('json_bytes', 'parsed', 'functions', 'namespaces', 'modules',
                     'preparation_records', 'proofs', 'by_path', 'request_paths',
                     'locations', 'home_cache'):
            getattr(self, name).clear()
        self.raw_reader.json.clear()
        self.active = False

    def bind(self, function):
        """绑定事实不另留无上限副本，原只读白名单仍负责函数分派。"""
        return frozen.ReadEvidence.bind(self, function)


@contextmanager
def bounded_scope(data_root, study_id, *, cache_bytes=2 * 1024 * 1024):
    """范围结束前重核所有原件及登记；无论成功失败均释放内容缓存。"""
    root = Path(data_root).resolve()
    prior = frozen.current_evidence(root)
    if prior is not None and prior.study_id == study_id:
        yield prior
        return
    evidence = BoundedEvidence(root, study_id, logical_root=Path(data_root).absolute(),
                               cache_bytes=cache_bytes)
    token = frozen._current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.close()
        frozen._current.reset(token)
