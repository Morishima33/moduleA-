"""页面请求内的只读归档核验；逐文件校验SHA-256，不跨请求保留核验结果。"""

from __future__ import annotations

import hashlib
import stat
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from contracts import ContractError, require, safe_id
from storage import read_json


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

    def _verify(self, root, record):
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
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == record.get("sha256")
                and len(data) == record.get("bytes"), "归档文件校验失败，暂停使用")
        # 不凭文件时间跳过内容核验：Windows创建时间不等于内容变更时间。
        require(self.signature(path.stat()) == signature, "归档文件读取期间发生变化，请刷新")
        return path

    def read(self, root, record):
        """逐次核验字节；同一请求中不重复解析相同内容的JSON。"""
        path = self.verify(root, record)
        key = (path, record["sha256"], record["bytes"])
        if key not in self.json:
            self.json[key] = read_json(path)
        return self.json[key]

    def verify_all(self, root, records):
        """大批附件以有限线程并行读取；任一指纹失败都拒绝整个结果。"""
        if len(records) < 64:
            for record in records:
                self.verify(root, record)
            return
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="archive-read") as pool:
            # 取完迭代器以传播每项异常，不能把未等待的任务当核验完成。
            list(pool.map(lambda record: self.verify(root, record), records))


class ReadResultMixin:
    """仅替换展示实例的文件读取；状态与有效性继续调用原Workflow.view。"""

    def _reader(self):
        """一个只读实例只供一个请求使用，独立view会重新建立缓存。"""
        if not hasattr(self, "_read_archive"):
            self._read_archive = ReadArchive()
        return self._read_archive

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
        return super().view(study_id)


class SnapshotFlight:
    """合并同时到达的同版本读取；完成即移除，不缓存已经完成的页面状态。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}

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
            return deepcopy(future.result())
        finally:
            if owner:
                with self._lock:
                    self._pending.pop(key, None)
