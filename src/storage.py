# 本文件只负责研究包的安全读写，不执行药理计算。
from contextlib import contextmanager  # 管理写入锁的获取与释放。
from contextvars import ContextVar
from datetime import datetime, timezone  # 记录明确的 UTC 时间。
from pathlib import Path  # 处理中文路径和相对路径。
import hashlib  # 校验文件内容。
import json  # 读取结构化文件。
import os  # 完成原子替换和系统级文件操作。
import time
import uuid  # 生成无冲突的内部编号。
from contracts import ContractError, encoded, require  # 复用全项目统一的数据规则。

def now():  # 为操作生成带时区的时间。
    return datetime.now(timezone.utc).isoformat()  # 不依赖电脑显示格式。

def new_id(prefix):  # 用固定前缀加随机标识区分对象类型。
    return prefix + "_" + uuid.uuid4().hex  # 编号不包含疾病名称或个人姓名。

def within(root, relative):  # 确保所有文件都在指定研究包内。
    root = Path(root).resolve()  # 获得真实目录。
    target = (root / relative).resolve()  # 展开路径，检查跳转后的实际位置。
    require(target.is_relative_to(root), "文件路径超出研究包")  # 阻止跨目录读取或写入。
    return target  # 返回安全位置。

def read_json(path):  # 读取保存的数据，损坏时不偷偷重建。
    try:  # 将常见文件错误转换成用户可读的问题。
        return json.loads(Path(path).read_text(encoding="utf-8"))  # 统一用 UTF-8 读取中文。
    except (OSError, ValueError) as error:  # 缺失和损坏都视为待处理问题。
        raise ContractError("数据文件缺失或损坏：" + Path(path).name) from error  # 不用空字典掩盖错误。

def write_json(path, value, replace=False):  # 保存完整 JSON，只有索引允许明确替换。
    path = Path(path)  # 统一路径对象。
    path.parent.mkdir(parents=True, exist_ok=True)  # 创建该产物所属目录。
    require(replace or not path.exists(), "禁止覆盖历史文件：" + path.name)  # 原始产物和历史记录不能覆盖。
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")  # 中断时也不会伪装成正式结果。
    try:  # 完成写入后才发布文件。
        with temporary.open("xb") as stream:  # 禁止覆盖其他临时写入。
            stream.write(encoded(value))  # 写入完整内容。
            stream.flush()  # 将缓冲区交给操作系统。
            os.fsync(stream.fileno())  # 请求刷新到磁盘。
        os.replace(temporary, path)  # 同一目录内一次替换，避免半份索引。
    finally:  # 普通失败时清理本次临时文件。
        temporary.unlink(missing_ok=True)  # 不碰其他运行的文件。

def file_record(root, path, role):  # 为归档文件记录位置、大小和内容指纹。
    path = Path(path).resolve()  # 获取实际文件位置。
    data = path.read_bytes()  # 对当前文件内容生成指纹。
    return {"path": path.relative_to(Path(root).resolve()).as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "role": role}  # 索引中不保存电脑绝对路径。

def verified_file(root, record):  # 读取前验证归档文件仍然完整。
    require(isinstance(record, dict), "文件索引缺失")  # 不接受只有文件名的输入。
    path = within(root, record.get("path", ""))  # 先做目录边界检查。
    require(path.is_file(), "归档文件缺失")  # 目录或不存在的路径不是产物。
    data = path.read_bytes()  # 读取实际内容。
    require(hashlib.sha256(data).hexdigest() == record.get("sha256") and len(data) == record.get("bytes"), "归档文件校验失败，暂停使用")  # 不继续使用被修改的文件。
    return path  # 返回已核验的文件。

_write_lock_wait = ContextVar("write_lock_wait", default=0)


@contextmanager
def wait_for_parallel_publication():
    """后台并行分支只等待写锁，仍使用同一把跨进程锁和全部发布校验。"""
    token = _write_lock_wait.set(30)
    try:
        yield
    finally:
        _write_lock_wait.reset(token)


@contextmanager  # 自动在函数退出时释放跨进程写入锁。
def write_lock(root):  # 防止多个页面或进程同时覆盖总索引。
    lock_path = Path(root) / "environments" / ".write.lock"  # 锁属于运行环境，不冒充研究资料。
    lock_path.parent.mkdir(parents=True, exist_ok=True)  # 测试目录也能独立建立环境位置。
    stream = lock_path.open("a+b")  # 重开已有锁文件不截断。
    if stream.seek(0, 2) == 0:  # Windows 字节锁需要至少一个字节。
        stream.write(b"0")  # 只在首次创建时初始化。
        stream.flush()  # 确保锁字节已存在。
    stream.seek(0)  # 锁定统一的第一个字节。
    acquired = False  # 只释放本次成功取得的锁。
    try:  # 获取锁失败时不进行任何业务写入。
        deadline = time.monotonic() + _write_lock_wait.get()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                # Windows 为 EACCES，Unix 为 EAGAIN。其他系统异常立即上报。
                if error.errno not in (13, 11) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        acquired = True  # 标记锁已成功取得。
        yield  # 允许调用者完成一次原子业务操作。
    except OSError as error:  # Windows 和其他系统的锁占用异常类型可能不同。
        if not acquired:  # 只把获取锁阶段的系统异常解释为写入占用。
            raise ContractError("另一个操作正在保存，请稍后重试") from error  # 不覆盖其他进程的保存结果。
        raise  # 真正的业务文件错误保留原异常，不能误报成锁占用。
    finally:  # 无论成功失败均关闭文件句柄。
        if acquired:  # 只解开已经拿到的锁。
            stream.seek(0)  # 回到锁定位置。
            if os.name == "nt":  # Windows 释放字节锁。
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)  # 解锁当前字节。
            else:  # Unix 释放文件锁。
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)  # 解锁当前句柄。
        stream.close()  # 系统在进程退出时也会释放锁。
