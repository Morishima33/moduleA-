"""原检查点函数的私有写前读取范围；第一次真实写入前完成并释放证明。"""
from contextlib import contextmanager, ExitStack
from functools import wraps
from types import FunctionType, SimpleNamespace

from contracts import require
from . import read_evidence


def read_checkpoint_in_scope(adapter, function, *args):
    """原读取器所核每件旧CP/目标历史附件也参加同一范围的最终完整SHA。"""
    from .scoped_worker_io import scoped_verified_file
    from . import bounded_evidence
    namespace = dict(function.__globals__)
    namespace['bounded'] = SimpleNamespace(verified_file=scoped_verified_file,
                                           read_verified_json=bounded_evidence.read_verified_json)
    clone = FunctionType(function.__code__, namespace, function.__name__,
                         function.__defaults__, function.__closure__)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone(adapter, *args)


def bind_checkpoint(adapter, function, original_bind):
    """保留原code/规则/锁/写入，只有该私有函数副本的两个全局引用包边界。"""
    original = original_bind(function)

    @wraps(function)
    def append(workflow, sid, run_id, key, payload, files):
        from .scoped_worker_io import source_scope
        require(read_evidence.current_evidence(workflow.root) is None,
                '检查点写入不能嵌套在外部纯读取范围')
        adapter.guard(workflow, sid)
        namespace = dict(original.__globals__)
        original_lock, original_write = namespace['write_lock'], namespace['write_json']
        state = {}

        @contextmanager
        def locked(root):
            # 原锁从读取到两次真实写入均保持；不另取锁或释放后重取。
            with original_lock(root):
                with ExitStack() as reads:
                    evidence = reads.enter_context(source_scope(workflow.root, sid))
                    state.update(reads=reads, evidence=evidence, finished=False)
                    try:
                        yield
                    finally:
                        # 幂等无写返回和异常路径同样完成范围清理。
                        reads.close()
                        state['finished'] = True
                        adapter.stats['checkpoint_read_phases'] += 1

        def write(path, value, *args, **kwargs):
            require('reads' in state, '原检查点写入未持有读取锁范围')
            if not state['finished']:
                # 首次写入之前全量退出复验；失败时不会调用真实writer。
                state['reads'].close()
                state['finished'] = True
            require(read_evidence.current_evidence(workflow.root) is None,
                    '首次写入前纯读取范围未释放')
            return original_write(path, value, *args, **kwargs)

        namespace.update(write_lock=locked, write_json=write)
        clone = FunctionType(original.__code__, namespace, original.__name__,
                             original.__defaults__, original.__closure__)
        clone.__kwdefaults__ = original.__kwdefaults__
        return clone(workflow, sid, run_id, key, payload, files)

    return append
