"""指定JSON读取的一次性证据范围：原函数字节不变，返回前再次完整核验SHA。"""
from __future__ import annotations

import builtins
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib
import json
import marshal
from pathlib import Path
import threading
from types import FunctionType, MethodType, ModuleType

from contracts import require, ContractError
from storage import read_json as original_read_json, verified_file as original_verified_file
from .read_archive import ReadArchive


_current = ContextVar('modulea_read_evidence_scope', default=None)

# 仅登记无写入入口；原code、默认值和closure均复用，不改模块globals/sys.modules。
READ_FUNCTIONS = {
    'modulea.api.views': {'Views.module','Views.study','Views.study_card'},
    'modulea.api.plan_reports': {'info', '_info'},
    'modulea.api.system_validation': {'info'},
    'modulea.api.display_revisions': {'info', '_info'},
    'modulea.core.display_revisions': {'_json', 'sources', 'binding', 'read_request', 'read_record', 'info'},
    'modulea.core.analysis_plans': {'AnalysisPlanWorkflow._active', 'AnalysisPlanWorkflow._view_snapshot'},
    'modulea.core.report_registry': {'current', 'info'},
    'modulea.core.plan_reports': {'binding', 'scientific_binding', 'read_receipt', 'info', '_info', 'checked_inputs', 'is_active'},
    'modulea.core.plan_reports_v2': {'binding', 'scientific_binding', 'read_receipt', 'info', '_info', '_info_base', 'checked_inputs', 'is_active'},
    'modulea.core.system_validation': {'read_receipt', 'scientific_status', 'binding', 'request', 'info',
                                       'same_binding_after_first_approval', '_existing_evidence_binding'},
    'modulea.core.system_execution': {'scientific_version', 'read_batch', 'require_batch', 'parent_records', '_parent_records', 'is_active', 'bound_parent_records'},
    'modulea.core.system_decisions': {'read_record', 'active', 'current', 'info'},
    'modulea.core.system_disease_sources': {'resolve', 'read'},
    'modulea.core.historical_disease_sources': {'context', 'guard', 'read_record', 'require_current', 'is_active'},
    'modulea.core.system_component_sources': {'read_record'},
    'modulea.core.system_acquisition': {'read_record'},
    'modulea.core.system_disease_acquisition': {'read_record'},
    'modulea.core.identity_exceptions': {'read_record', 'for_batch', 'guard'},
    'modulea.core.ppi_identity_scope': {'context', 'guard', 'checked_proposal', 'scope', 'read_record'},
    'intake_sources': {'current', 'identity'},
    'modulea.core.plan_report_contract': {'validate_receipts'},
    'modulea.core.report_archive_repair': {'document_evidence', '_source', 'read_request', 'read_receipt'},
    'science_modules.a07.plan_payload': {'method_references', 'enrichment_source', 'input_reference', 'build', '_build', 'validate'},
    'science_modules.a07.plan_payload_v2': {'method_references', 'enrichment_source', 'input_reference', 'build', '_build', '_build_base', 'network_facts', 'validate'},
    'science_modules.a07.plan_figures': {'validate'},
    'science_modules.a07.plan_figures_v2': {'validate'},
}


def current_evidence(root=None):
    """只在所属线程、同一数据根内生效；context复制到其他线程也不能复用。"""
    value = _current.get()
    if value is None or not value.active or not value.enabled or value.owner != threading.get_ident():
        return None
    if root is not None:
        candidate = Path(root)
        if candidate not in (value.root, value.logical_root) and candidate.resolve() != value.root:
            return None
    return value


def read_call(function, *args, **kwargs):
    """ReadResultMixin只分派原super方法；未显式启用时完全沿原方法。"""
    evidence = current_evidence()
    return evidence.call(function, *args, **kwargs) if evidence else function(*args, **kwargs)


def _object_root(value):
    """只识别已有Workflow/Views/App的固定根，不从请求字段推断数据目录。"""
    root = getattr(value, 'root', None)
    if root is None:
        settings = getattr(getattr(value, 'kernel', None), 'settings', None)
        root = getattr(settings, 'data_root', None)
    return root


@contextmanager
def read_evidence_scope(data_root, study_id):
    """HTTP必须在本范围成功退出后才发送JSON；文件流和写入口不得采用。"""
    root = Path(data_root).resolve()
    prior = current_evidence(root)
    if prior is not None and prior.study_id == study_id:
        yield prior
        return
    evidence = ReadEvidence(root, study_id, logical_root=Path(data_root).absolute())
    token = _current.set(evidence)
    try:
        yield evidence
        evidence.finish()
    finally:
        evidence.active = False
        _current.reset(token)


class _ScopedArchive(ReadArchive):
    """仅当前请求的Workflow I/O使用范围；普通ReadArchive仍逐次强核验。"""
    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence

    def verify(self, root, record):
        return self.evidence.verified_file(root, record)

    def read(self, root, record):
        return self.evidence.read_json(self.evidence.verified_file(root, record))

    def verify_all(self, root, records):
        return self.evidence.verify_all(root, records)


class ReadEvidence:
    """首次与退出各做全SHA；范围内只复用同一引用的已核验不可变证据。"""
    def __init__(self, root, study_id, *, logical_root=None):
        self.root, self.study_id = root, study_id
        self.logical_root = logical_root or root
        self.owner, self.active = threading.get_ident(), True
        self.manifest = self.logical_root / 'studies' / study_id / 'manifest.json'
        self.manifest_path = self.manifest.resolve()
        require(self.manifest_path.is_relative_to(root), '读取研究路径超出数据根')
        # 不存在研究仍由原API给404；不能因加速入口先读manifest而变成500。
        try:
            self.manifest_bytes = self.manifest.read_bytes()
        except FileNotFoundError:
            self.manifest_bytes = None
        self.enabled = self.manifest_bytes is not None
        self.raw_reader = ReadArchive()
        self.reader = _ScopedArchive(self)
        self.proofs, self.by_path, self.json_bytes, self.parsed = {}, {}, {}, {}
        self.home_cache, self.request_paths, self.locations = {}, {}, {}
        self.lock = threading.RLock()
        self.functions, self.namespaces, self.modules = {}, {}, {}
        self.allowed = None
        self.stats = {'first_sha_checks': 0, 'first_bytes_hashed': 0, 'exit_sha_checks': 0,
                      'exit_bytes_hashed': 0, 'duplicate_references': 0, 'manifest_checks': 1,
                      'location_resolutions': 0, 'location_cache_hits': 0}

    def _owned(self):
        """显式对象被传往其他线程或范围结束后，也不能使用旧证明。"""
        return self.active and self.owner == threading.get_ident() and current_evidence() is self

    def _home(self, root):
        """仅加速同一数据根内的研究/来源，其他根继续原读取实现。"""
        if not self._owned():
            return None
        lexical = Path(root)
        if lexical not in self.home_cache:
            resolved = lexical.resolve()
            self.home_cache[lexical] = resolved if resolved.is_relative_to(self.root) else None
        return self.home_cache[lexical]

    def _key(self, home, record):
        """同路径不同声明SHA不能混用；角色别名不改变原始字节身份。"""
        require(isinstance(record, dict), '文件索引缺失')
        return home, record.get('path'), record.get('bytes'), record.get('sha256')

    def location(self, original, study_id):
        """首次照原within校验，结束再照原方法核对；不跨请求保存目录位置。"""
        if not self._owned() or current_evidence(original.__self__.root) is not self:
            return original(study_id)
        key = (Path(original.__self__.root), study_id)
        if key in self.locations:
            self.stats['location_cache_hits'] += 1
            return self.locations[key][2]
        path = original(study_id)
        self.locations[key] = original, study_id, path
        self.stats['location_resolutions'] += 1
        return path

    def _capture(self, home, record, *, force_json=False):
        """工作线程仅执行已指定原件I/O；不传播函数绑定或科学上下文。"""
        key = self._key(home, record)
        content = force_json or str(record.get('path', '')).lower().endswith('.json')
        try:
            verified = self.raw_reader._verify(home, record, content=content)
        except OSError as error:
            raise ContractError('归档文件缺失') from error
        path, raw = verified if content else (verified, None)
        with self.lock:
            self.proofs[key] = (home, dict(record), path)
            self.by_path[path] = key
            self.request_paths[home / record['path']] = path
            if raw is not None:
                self.json_bytes[path] = raw
            self.stats['first_sha_checks'] += 1
            self.stats['first_bytes_hashed'] += record['bytes']
        return path

    def verified_file(self, root, record):
        """重复引用复用本次首次核验；任何变化由退出完整SHA再次阻断。"""
        home = self._home(root)
        if home is None:
            return original_verified_file(root, record)
        key = self._key(home, record)
        if key in self.proofs:
            self.stats['duplicate_references'] += 1
            return self.proofs[key][2]
        return self._capture(home, record)

    def verify_all(self, root, records):
        """按原引用去重后至多8线程完整读取，等待所有核验和任何异常。"""
        rows = list(records)
        home = self._home(root)
        if home is None:
            for record in rows:
                original_verified_file(root, record)
            return
        pending = {}
        for record in rows:
            key = self._key(home, record)
            if key in self.proofs or key in pending:
                self.stats['duplicate_references'] += 1
            else:
                pending[key] = record
        if len(pending) < 32:
            for record in pending.values():
                self._capture(home, record)
        else:
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix='request-evidence') as pool:
                list(pool.map(lambda record: self._capture(home, record), pending.values()))

    def read_json(self, path):
        """只解析已核验的不可变bytes，绝不在verified_file后读取未验新内容。"""
        if not self._owned():
            return original_read_json(path)
        lexical = Path(path)
        resolved = self.request_paths.get(lexical) or lexical.resolve()
        if not resolved.is_relative_to(self.root):
            return original_read_json(path)
        if resolved not in self.json_bytes:
            prior = self.by_path.get(resolved)
            if prior is not None:
                # 没有.json后缀的已索引JSON也必须重新取通过原SHA的不可变bytes。
                home, record, _ = self.proofs[prior]
                self._capture(home, record, force_json=True)
            else:
            # 原read_json允许直接读manifest等无外部SHA索引的JSON；固定当次字节并退出复验。
                raw = resolved.read_bytes()
                record = {'path': resolved.relative_to(self.root).as_posix(), 'bytes': len(raw),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'role': 'request_json'}
                key = self._key(self.root, record)
                self.proofs[key] = (self.root, record, resolved)
                self.by_path[resolved] = key
                self.request_paths[resolved] = resolved
                self.json_bytes[resolved] = raw
                self.stats['first_sha_checks'] += 1
                self.stats['first_bytes_hashed'] += len(raw)
        if resolved not in self.parsed:
            try:
                self.parsed[resolved] = json.loads(self.json_bytes[resolved].decode('utf-8'))
            except (ValueError, UnicodeError) as error:
                raise ContractError('数据文件缺失或损坏：' + resolved.name) from error
        # 跟原read_json一样，每次返回独立容器，调用方不能污染另一次读取。
        return marshal.loads(marshal.dumps(self.parsed[resolved]))

    def finish(self):
        """JSON发送前重新完整读遍全部不同原件，mtime恢复也不能掩盖内容变化。"""
        if not self.enabled:
            return
        require(self._owned(), '读取证据范围已退出或线程不同')
        self._anchors()
        require(self.manifest.read_bytes() == self.manifest_bytes, '读取期间研究登记已改变，请刷新')
        rows = list(self.proofs.values())
        def verify(row):
            home, record, _ = row
            self.raw_reader.verify(home, record)
            with self.lock:
                self.stats['exit_sha_checks'] += 1
                self.stats['exit_bytes_hashed'] += record['bytes']
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix='request-final-sha') as pool:
            list(pool.map(verify, rows))
        self._anchors()
        require(self.manifest.read_bytes() == self.manifest_bytes, '读取期间研究登记已改变，请刷新')
        self.stats['manifest_checks'] += 2

    def _anchors(self):
        """退出不用旧resolved位置自证：重新展开每个逻辑根、目录和原location。"""
        require(self.logical_root.resolve() == self.root and self.manifest.resolve() == self.manifest_path
                and self.manifest_path.is_relative_to(self.root),
                '读取期间研究目录位置已改变，请刷新')
        for lexical, expected in self.home_cache.items():
            if expected is not None:
                require(lexical.resolve() == expected, '读取期间归档根目录已改变，请刷新')
        for original, study_id, expected in self.locations.values():
            require(original(study_id) == expected, '读取期间研究目录位置已改变，请刷新')

    def _allowed_functions(self):
        """按精确模块/属性白名单定位函数对象，兼容旧版克隆函数的原__module__。"""
        if self.allowed is None:
            self.allowed = set()
            for module_name, names in READ_FUNCTIONS.items():
                try:
                    module = importlib.import_module(module_name)
                except ModuleNotFoundError as error:
                    if error.name == module_name:
                        continue
                    raise
                for name in names:
                    value = module
                    try:
                        for part in name.split('.'):
                            value = getattr(value, part)
                    except AttributeError:
                        continue
                    if isinstance(value, FunctionType):
                        self.allowed.add(value)
        return self.allowed

    def _value(self, value):
        """只换明确读函数/模块代理；写函数、类、状态算法及其他值原样。"""
        if isinstance(value, FunctionType):
            return self.bind(value)
        if isinstance(value, ModuleType) and (value.__name__ in READ_FUNCTIONS or value.__name__ == 'storage'
                or value.__name__ in ('modulea', 'modulea.api', 'modulea.core', 'science_modules', 'science_modules.a07')):
            if value not in self.modules:
                self.modules[value] = _BoundModule(value, self)
            return self.modules[value]
        if isinstance(value, tuple) and any(isinstance(item, ModuleType) for item in value):
            return tuple(self._value(item) for item in value)
        return value

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        """仅此克隆函数的builtins代理局部import，绝不改全局__import__/sys.modules。"""
        return self._value(builtins.__import__(name, globals, locals, fromlist, level))

    def bind(self, function):
        """复用原code和closure，只在请求私有globals绑定读取I/O。"""
        if not self._owned():
            return function
        if isinstance(function, MethodType):
            root = _object_root(function.__self__)
            if root is not None and current_evidence(root) is not self:
                return function
            return MethodType(self.bind(function.__func__), function.__self__)
        if not isinstance(function, FunctionType) or function not in self._allowed_functions():
            return function
        if function in self.functions:
            return self.functions[function]
        original_globals = function.__globals__
        fresh = id(original_globals) not in self.namespaces
        if fresh:
            original_builtins = original_globals.get('__builtins__', builtins)
            local_builtins = dict(original_builtins if isinstance(original_builtins, dict) else vars(original_builtins))
            local_builtins['__import__'] = self._import
            # FunctionType创建时固定builtins指针，必须先放私有builtins再创建任何clone。
            self.namespaces[id(original_globals)] = {'__name__': original_globals.get('__name__'),
                                                     '__builtins__': local_builtins}
        namespace = self.namespaces[id(original_globals)]
        clone = FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
        clone.__kwdefaults__ = deepcopy(function.__kwdefaults__)
        clone.__annotations__ = dict(function.__annotations__)
        self.functions[function] = clone
        if fresh:
            # 函数缓存先登记，避免原函数互相引用递归；原模块namespace始终不改。
            for key, value in original_globals.items():
                if key != '__builtins__':
                    namespace[key] = self._value(value)
            namespace['verified_file'] = self.verified_file
            namespace['read_json'] = self.read_json
        return clone

    def call(self, function, *args, **kwargs):
        """只有白名单只读入口会绑定；其他函数仍原样调用，不能借此批准或写入。"""
        owner = function.__self__ if isinstance(function, MethodType) else args[0] if args else None
        root = _object_root(owner)
        if root is not None and current_evidence(root) is not self:
            # 不让显式其他数据根的调用继承当前请求；完成后恢复原范围。
            token = _current.set(None)
            try:
                return function(*args, **kwargs)
            finally:
                _current.reset(token)
        return self.bind(function)(*args, **kwargs)


class _BoundModule(ModuleType):
    """请求内模块外观，函数属性按精确白名单绑定，未改任何真实模块属性。"""
    def __init__(self, original, evidence):
        super().__init__(original.__name__)
        self._original, self._evidence = original, evidence

    def __getattr__(self, name):
        if self._original.__name__ == 'storage':
            if name == 'verified_file': return self._evidence.verified_file
            if name == 'read_json': return self._evidence.read_json
        return self._evidence._value(getattr(self._original, name))
