"""页面请求内的只读归档核验；逐文件校验SHA-256，不跨请求保留核验结果。"""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import stat
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from contracts import ContractError, require, safe_id


_legacy_report_scope = ContextVar('modulea_legacy_report_read_scope', default=None)


@contextmanager
def legacy_report_read_scope(root):
    """只有本线程、本数据根的只读请求可向嵌套报告核验传递读取适配。"""
    token = _legacy_report_scope.set((Path(root).resolve(), threading.get_ident()))
    try:
        yield
    finally:
        _legacy_report_scope.reset(token)


def legacy_report_read_instance(root):
    """冻结报告核验创建原Workflow时，仅在明确只读作用域中采用同类I/O适配。"""
    scope = _legacy_report_scope.get()
    if scope is not None and scope[1] == threading.get_ident() and Path(root).resolve() == scope[0]:
        from .read_plan_workflow import ReadPlanWorkflow
        return object.__new__(ReadPlanWorkflow)
    return None


def verify_records(workflow, root, records):
    """只读实例复用既有完整SHA批量核验；科学/写入实例仍逐件原校验，不跳过文件。"""
    bulk = getattr(workflow, 'verify_archives', None)
    if callable(bulk):
        bulk(root, list(records))
    else:
        from storage import verified_file
        for record in records:
            verified_file(root, record)


class ReadArchive:
    """复用同一请求中已解析的目录，避免Windows为每个文件反复展开相同路径。"""

    def __init__(self):
        self.roots = {}
        self.parents = {}
        self.json = {}

    @staticmethod
    def signature(info):
        """文件身份或内容元数据变化时，先前核验不能复用。"""
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def verify(self, root, record):
        """缺失文件仍按原契约报告归档不可用，不能误报研究不存在。"""
        try:
            return self._verify(root, record)
        except OSError as error:
            raise ContractError("归档文件缺失") from error

    def _verify(self, root, record, *, content=False):
        """目录仍须限于本研究，链接单独展开，实际文件字节仍按原指纹核验。"""
        require(isinstance(record, dict), "文件索引缺失")
        root = Path(root)
        if root not in self.roots:
            self.roots[root] = root.resolve()
        root = self.roots[root]
        target = root / record.get("path", "")
        parent = target.parent
        parent_signature = self.signature(parent.stat())
        prior = self.parents.get(parent)
        if prior is None or prior[0] != parent_signature:
            prior = (parent_signature, parent.resolve())
            self.parents[parent] = prior
        path = prior[1] / target.name
        info = path.lstat()
        # Windows链接和junction的重解析属性也必须检查，不能按普通文件读取。
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            path = path.resolve()
            info = path.stat()
        require(path.is_relative_to(root), "文件路径超出研究包")
        require(stat.S_ISREG(info.st_mode), "归档文件缺失")
        signature = self.signature(info)
        # 大结构/报告只分块计算指纹，避免多个页面同时把整批附件读入内存。
        # JSON则返回这次已核验的原始字节，不能另开文件解析未经核验的第二份内容。
        with path.open("rb") as stream:
            opened = self.signature(os.fstat(stream.fileno()))
            # Windows的lstat与fstat对ctime的含义可能不同；跨接口比较共同身份字段，
            # 句柄自身前后仍比较完整签名，路径自身前后也保持原完整检查。
            require(opened[:4] == signature[:4],
                    "归档文件读取期间发生变化，请刷新")
            data = stream.read() if content else None
            digest = hashlib.sha256(data).hexdigest() if content else hashlib.file_digest(stream, "sha256").hexdigest()
            size = len(data) if content else info.st_size
            require(self.signature(os.fstat(stream.fileno())) == opened,
                    "归档文件读取期间发生变化，请刷新")
        require(digest == record.get("sha256") and size == record.get("bytes"),
                "归档文件校验失败，暂停使用")
        # 不凭文件时间跳过内容核验：Windows创建时间不等于内容变更时间。
        require(self.signature(path.stat()) == signature, "归档文件读取期间发生变化，请刷新")
        return (path, data) if content else path

    def read(self, root, record):
        """逐次核验字节；同一请求中不重复解析相同内容的JSON。"""
        try:
            path, data = self._verify(root, record, content=True)
        except OSError as error:
            raise ContractError("归档文件缺失") from error
        key = (path, record["sha256"], record["bytes"])
        if key not in self.json:
            self.json[key] = json.loads(data.decode("utf-8"))
        return self.json[key]

    def verify_all(self, root, records):
        """大批附件以有限线程并行读取；任一指纹失败都拒绝整个结果。"""
        if len(records) < 64:
            for record in records:
                self.verify(root, record)
            return
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="archive-read") as pool:
            # 小文件按批调度，减少几千个Future的内存与线程切换；每件仍完整核验。
            chunk = min(32, max(1, len(records) // 32))
            batches = [records[i:i + chunk] for i in range(0, len(records), chunk)]
            def verify_batch(batch):
                for record in batch:
                    self.verify(root, record)
            # 取完迭代器以传播每项异常，不能把未等待的任务当核验完成。
            list(pool.map(verify_batch, batches))


class ReadResultMixin:
    """仅替换展示实例的文件读取；状态与有效性继续调用原Workflow.view。"""

    def _reader(self):
        """一个只读实例只供一个请求使用，独立view会重新建立缓存。"""
        if not hasattr(self, "_read_archive"):
            self._read_archive = ReadArchive()
        return self._read_archive

    @contextmanager
    def handoff_read_cache(self):
        """原单次缓存与嵌套报告读取同进退，不跨请求、根目录或线程传播。"""
        with legacy_report_read_scope(self.root), super().handoff_read_cache():
            yield

    def active(self, manifest, run_id):
        """页面组装在view返回后仍会核对有效性，嵌套核验继续使用同一读取适配。"""
        with legacy_report_read_scope(self.root):
            return super().active(manifest, run_id)

    def verify_archive(self, root, record):
        """给只读展示适配提供同一套完整文件核验，不影响写入实例。"""
        return self._reader().verify(root, record)

    def verify_archives(self, root, records):
        """试算明细的附件同样采用有限并发，仍等待全部核验完成。"""
        return self._reader().verify_all(root, records)

    def run(self, manifest, run_id):
        """复用原运行归属检查，不更改输入版本或有效性判断。"""
        cache = getattr(self, "_view_cache", None)
        if cache is not None and run_id in cache["runs"]:
            return cache["runs"][run_id]
        safe_id(run_id, "run")
        require(run_id in manifest["runs"], "运行不属于当前研究")
        run = self._reader().read(self.location(manifest["study_id"]), manifest["runs"][run_id]["run_file"])
        require(run["study_id"] == manifest["study_id"] and run["run_id"] == run_id, "运行身份不一致")
        if cache is not None:
            cache["runs"][run_id] = run
        return run

    def latest_review(self, manifest, artifact_id):
        """仍按归档顺序取最近决定，不按文件时间推断或缓存旧批准。"""
        cache = getattr(self, "_view_cache", None)
        if cache is not None and artifact_id in cache["reviews"]:
            return cache["reviews"][artifact_id]
        for record in reversed(manifest["reviews"]):
            review = self._reader().read(self.location(manifest["study_id"]), record)
            if review["artifact_id"] == artifact_id:
                if cache is not None:
                    cache["reviews"][artifact_id] = review
                return review
        if cache is not None:
            cache["reviews"][artifact_id] = None
        return None


    def result(self, manifest, run_id):
        """沿用原结果归属检查及请求缓存，只加速逐文件核验的路径读取。"""
        cache = getattr(self, "_view_cache", None)
        if cache is not None and run_id in cache["results"]:
            return cache["results"][run_id]
        record = manifest["runs"][run_id]
        if not record.get("result_file"):
            return None
        reader = self._reader()
        root = self.location(manifest["study_id"])
        result = reader.read(root, record["result_file"])
        run = self.run(manifest, run_id)
        require(result["artifact_id"] == run["artifact_id"]
                and result["run_id"] == run_id
                and result["study_id"] == manifest["study_id"], "产物身份不一致")
        # 自动批次可有上万个证据文件。列表只验证结果索引；所选附件在下载时逐件核验。
        # 该优化仅用于只读实例；写入、科研复核及后台完整校验器仍核验全部输入。
        if result.get("summary", {}).get("science_version") not in ("A06.automatic.1", "A06.automatic.2", "A06.automatic.3"):
            reader.verify_all(root, result["files"])
        if cache is not None:
            cache["results"][run_id] = result
        return result

    def view(self, study_id):
        """每次独立状态读取重新核验；不保留上一请求的目录或文件缓存。"""
        self._read_archive = ReadArchive()
        with legacy_report_read_scope(self.root):
            return super().view(study_id)


class SnapshotFlight:
    """合并同时到达的同版本读取；完成即移除，不缓存已经完成的页面状态。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}

    @staticmethod
    def _clone(value):
        """在内存中复制已核验的归档容器，保留别名和各请求的修改隔离。

        编解码字节只由当前内存对象生成，不读取文件或接收外部序列化输入。
        页面主要由JSON容器组成；遇到其他Python对象仍使用原deepcopy。
        """
        try:
            return marshal.loads(marshal.dumps(value))
        except (TypeError, ValueError):
            return deepcopy(value)

    def run(self, key, read):
        """各请求取得独立副本，任何写请求仍独立重新核验。"""
        with self._lock:
            future = self._pending.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._pending[key] = future
        try:
            if owner:
                try:
                    future.set_result(read())
                except BaseException as error:
                    future.set_exception(error)
            return self._clone(future.result())
        finally:
            if owner:
                with self._lock:
                    self._pending.pop(key, None)
