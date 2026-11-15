"""显式科学worker I/O适配：流式原件核验、有界读取与分对象恢复，科学代码不改字节。"""
import builtins
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from types import FunctionType, MethodType, ModuleType

from contracts import fingerprint, require
import storage
from . import bounded_evidence as bounded
from . import read_evidence
from . import rescue_read_evidence
from . import system_receptor_rescue as first
from . import system_receptor_rescue_v2 as second

VERSION = 'ModuleA.science_worker_io.1'
SOURCE = Path(__file__).resolve().parents[2]


class _Module:
    """只在本适配器的函数私有namespace中转换局部import，真实模块不修改。"""
    def __init__(self, module, adapter):
        self.module, self.adapter = module, adapter

    def __getattr__(self, name):
        return self.adapter.value(getattr(self.module, name))


class WorkerIO:
    """只调整实际文件I/O；完整原规则、参数、返回值、写锁与Workflow照用。"""
    def __init__(self, *, header_entries=2048):
        self.functions, self.namespaces, self.modules = {}, {}, {}
        self.headers = OrderedDict()
        self.header_limit = header_entries
        self.adapter_binding = None
        self.stats = {'checkpoint_json_parses': 0, 'checkpoint_header_hits': 0,
                      'checkpoint_sha_checks': 0}

    def project_code(self, function):
        """只代理本仓库src的原函数；第三方库、内置函数和本适配器保持原对象。"""
        if not isinstance(function, FunctionType):
            return False
        path = Path(function.__code__.co_filename).resolve()
        return path.is_relative_to(SOURCE) and path not in (Path(__file__).resolve(), Path(bounded.__file__).resolve())

    def value(self, value):
        """按真实对象身份替换I/O，不根据相同函数名接受外部实现。"""
        if value is storage.verified_file:
            return bounded.verified_file
        if value is storage.file_record:
            return bounded.file_record
        if value is read_evidence.read_evidence_scope or value is rescue_read_evidence.json_evidence_scope:
            return bounded.bounded_scope
        if value is first.read_checkpoint:
            return lambda w, s, r, k: self.read_checkpoint(w, s, r, k, first.VERSION, first.CHECKPOINTS)
        if value is second.read_checkpoint:
            return lambda w, s, r, k: self.read_checkpoint(w, s, r, k, second.VERSION, second.CHECKPOINTS)
        if isinstance(value, FunctionType):
            return self.bind(value)
        if isinstance(value, ModuleType):
            filename = getattr(value, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(SOURCE):
                if value not in self.modules:
                    self.modules[value] = _Module(value, self)
                return self.modules[value]
        return value

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        """仅本函数副本的builtins代理import；无sys.modules或全局函数替换。"""
        return self.value(builtins.__import__(name, globals, locals, fromlist, level))

    def bind(self, function):
        """复用原code/defaults及类闭包；函数闭包延迟分派，避免遗漏validator里的I/O。"""
        if isinstance(function, MethodType):
            return MethodType(self.bind(function.__func__), function.__self__)
        if not self.project_code(function):
            return function
        if function in self.functions:
            return self.functions[function]
        original = function.__globals__
        fresh = id(original) not in self.namespaces
        if fresh:
            local = dict(vars(builtins))
            local['__import__'] = self._import
            self.namespaces[id(original)] = {'__builtins__': local}
        namespace = self.namespaces[id(original)]
        def cell(value):
            """只让函数闭包经过同一I/O分派；__class__及科学数据不改。"""
            if isinstance(value, FunctionType) and self.project_code(value):
                original_value = value
                def call(*args, **kwargs):
                    return self.bind(original_value)(*args, **kwargs)
                value = call
            return (lambda: value).__closure__[0]
        closure = tuple(cell(item.cell_contents) for item in function.__closure__) if function.__closure__ else None
        clone = FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, closure)
        clone.__kwdefaults__ = function.__kwdefaults__
        clone.__annotations__ = function.__annotations__
        self.functions[function] = clone
        if fresh:
            for key, value in list(original.items()):
                # 冻结版已有私有函数作用域字典；只复制其函数引用，科学数据仍原样。
                namespace[key] = {k: self.value(v) for k, v in value.items()} if key == '_scope' and isinstance(value, dict) else self.value(value)
        return clone

    def wrap(self, workflow):
        """保留原类继承关系和状态算法，只有本实例的方法使用私有I/O分派。"""
        if getattr(workflow, '_worker_io', None) is self:
            return workflow
        wrapper = type('WorkerIOWorkflow', (WorkerWorkflow, type(workflow)), {})
        value = object.__new__(wrapper)
        value.__dict__.update(workflow.__dict__)
        value._worker_io = self
        value.validators = {key: self.bind(fn) for key, fn in workflow.validators.items()}
        return value

    def read_checkpoint(self, workflow, sid, run_id, key, version, field):
        """每次全SHA检查登记列表；只解析本对象payload，其他对象仅留有界身份头。"""
        first._checkpoint_key(key)
        manifest = workflow.load(sid)
        run = workflow.run(manifest, run_id)
        require(run['module_id'] == 'A06' and run['config'].get('version') == version,
                '检查点不是本补救运行')
        home = workflow.location(sid)
        previous = None
        for ref in manifest.get(field, []):
            path = bounded.verified_file(home, ref)
            self.stats['checkpoint_sha_checks'] += 1
            identity = (str(path), ref['bytes'], ref['sha256'])
            header = self.headers.get(identity)
            value = None
            if header is None:
                value = bounded.read_verified_json(home, ref)
                self.stats['checkpoint_json_parses'] += 1
                header = tuple(value.get(k) for k in ('schema_version', 'study_id', 'run_id', 'key'))
                # 头字段必须小且是字符串，不能把任意JSON大对象塞进缓存。
                require(all(isinstance(v, str) and len(v) <= 256 for v in header), '检查点身份头不合法')
                if self.header_limit:
                    self.headers[identity] = header
                    while len(self.headers) > self.header_limit:self.headers.popitem(last=False)
            else:
                self.stats['checkpoint_header_hits'] += 1
                self.headers.move_to_end(identity)
            require(header[:2] == (version, sid), '补救检查点归属不同')
            if header[2:] != (run_id, key):continue
            if value is None:
                value = bounded.read_verified_json(home, ref)
                self.stats['checkpoint_json_parses'] += 1
            # 解析后再核内容，不能verified_file后把替换字节认作原件。
            bounded.verified_file(home, ref)
            require(value.get('config_hash') == run['config_hash'] and isinstance(value.get('payload'), dict)
                    and isinstance(value.get('files'), list) and value.get('human_review_written') is False,
                    '补救检查点配置、内容或人工标记不同')
            require(ref['path'].startswith(f'runs/A06/{run_id}/rescue_checkpoints/{key}/')
                    and value.get('previous') == (previous[0] if previous else None),
                    '补救检查点未按本对象原尝试链登记')
            if previous:
                old = previous[1]['payload']
                require(old.get('state') not in ('ready', 'completed') and old.get('retryable') is True,
                        '已完成或不可重试的补救对象不能追加替换')
            for item in value['files']:bounded.verified_file(home, item)
            region_key = re.fullmatch(r'pair_([0-9]{6})_region_([0-9]{4})', key)
            execution = value['payload'].get('execution')
            if region_key and execution is not None:
                prefix = f'runs/A06/{run_id}/rescue/scores/pair_{region_key[1]}/region_{region_key[2]}/'
                require(isinstance(execution, dict) and execution in value['files']
                        and execution['path'].startswith(prefix)
                        and re.fullmatch(r'attempt_[0-9a-f]{32}/execution.json',execution['path'][len(prefix):]),
                        '区域检查点执行跨运行、组合或区域')
            previous = (deepcopy(ref), value)
        require(fingerprint(workflow.load(sid)) == fingerprint(manifest), '检查点读取期间登记改变')
        return previous

    def guard(self, workflow, sid):
        """逐对象登记及最终发表前重核适配器原件、当前实现与登记，不靠版本号放行。"""
        if self.adapter_binding is None:return
        study, reference, implementations = self.adapter_binding
        require(sid == study, 'worker I/O适配跨研究')
        manifest = workflow.load(sid)
        require(reference in manifest.get('worker_io_adaptations', []), 'worker I/O适配登记已改变')
        value = bounded.read_verified_json(workflow.location(sid), reference)
        code = Path(__file__).resolve().parents[3]
        for name, digest in implementations.items():
            require(sha256((code/name).read_bytes()).hexdigest() == digest, 'worker I/O实现已改变')
        for item in value['files']:bounded.verified_file(workflow.location(sid), item)

    def activate_registration(self, workflow, sid, reference):
        """只有已登记且与本次代码一致的适配器才能进入明确恢复。"""
        value = bounded.read_verified_json(workflow.location(sid), reference)
        require(value['schema_version'] == VERSION, 'worker I/O适配协议不同')
        self.adapter_binding = sid, reference, value['implementation_sha256']
        self.guard(workflow, sid)

    def close(self):
        """完成后解除所有私有函数引用，worker退出前不长期持有缓存。"""
        self.headers.clear()
        self.functions.clear()
        self.namespaces.clear()
        self.modules.clear()


class WorkerWorkflow:
    """方法分派与显式I/O适配登记；不引入第二套状态、存储或队列。"""
    def __getattribute__(self, name):
        value = super().__getattribute__(name)
        if name == '_worker_io' or not isinstance(value, MethodType):return value
        adapter = object.__getattribute__(self, '_worker_io')
        bound = adapter.bind(value)
        if name.startswith('append_analysis_plan_receptor_rescue') or name == '_finish':
            def guarded(*args, **kwargs):
                sid = args[0]['study_id'] if name == '_finish' else args[0]
                adapter.guard(self, sid)
                return bound(*args, **kwargs)
            return guarded
        return bound

    def register_worker_io(self, sid, run_id, body):
        """原二版资格核验通过后追加适配器快照；不替换run/config/checkpoint或人工意见。"""
        with storage.write_lock(self.root):
            manifest, _, run = self._worker_io.bind(second.validate_request)(self, sid, body)
            require(run and run['run_id'] == run_id and not manifest['runs'][run_id].get('result_file'),
                    'I/O适配只用于明确指定的当前未完成二版')
            home = self.location(sid)
            code = Path(__file__).resolve().parents[3]
            implementations = {name: sha256((code/name).read_bytes()).hexdigest() for name in (
                'src/modulea/core/worker_io.py', 'src/modulea/core/bounded_evidence.py',
                'src/modulea/core/rescue_recovery.py', 'src/modulea/tasks/rescue_worker_io.py',
                'tools/run_rescue_worker_io.py')}
            expected = {'schema_version': VERSION, 'study_id': sid, 'run_id': run_id,
                        'request': run['inputs']['rescue_request'], 'implementation_sha256': implementations,
                        'scientific_config_hash': run['config_hash'], 'human_review_written': False}
            for ref in manifest.get('worker_io_adaptations', []):
                old = storage.read_json(bounded.verified_file(home, ref))
                if old['run_id'] == run_id and old['implementation_sha256'] == implementations:
                    require(all(old.get(k) == v for k, v in expected.items()), 'I/O适配登记内容不同')
                    for item in old['files']:bounded.verified_file(home, item)
                    return ref
            folder = home/'runs/A06'/run_id/'execution_adapters'/storage.new_id('adapter')
            files = []
            for name in implementations:
                dest = folder/'code'/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                raw = (code/name).read_bytes()
                require(sha256(raw).hexdigest() == implementations[name], '适配器快照读取期间改变')
                with dest.open('xb') as stream:stream.write(raw)
                files.append(bounded.file_record(home, dest, 'worker_io_implementation'))
            path = folder/'adapter.json'
            storage.write_json(path, dict(expected, files=files, created_at=storage.now()))
            ref = bounded.file_record(home, path, 'worker_io_adaptation')
            manifest.setdefault('worker_io_adaptations', []).append(ref)
            self.save(manifest)
            return ref
