"""下载专用私有临时快照：分块核实际响应字节，原件被换后也不发送另一份内容。"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

from contracts import require
from ..core.bounded_evidence import verified_file
from ..core.read_evidence import current_evidence

CHUNK=1024*1024


@dataclass(frozen=True)
class VerifiedSnapshot:
    """只暴露有界读取和关闭，不把临时文件路径当作公开下载权限。"""
    _file:object
    bytes:int
    sha256:str

    @property
    def closed(self):
        """用于异常路径确认句柄已释放。"""
        return self._file.closed

    def read(self,size=256*1024):
        """响应发送固定块，不允许无上限整件读取。"""
        require(type(size) is int and 0<size<=CHUNK,'下载块大小必须在1字节至1MiB之间')
        return self._file.read(size)

    def rewind(self):
        """完整核验后从快照头部发送；原件路径不再参与传输。"""
        self._file.seek(0)

    def close(self):
        """正常、连接断开和首尾核验失败均关闭并删除临时快照。"""
        self._file.close()


def _copy_verified(source,output,ref):
    """核验真正复制进快照的完整字节；首次原件校验不能代替此处。"""
    digest=sha256();size=0
    with source.open('rb') as stream:
        for raw in iter(lambda:stream.read(CHUNK),b''):
            output.write(raw);size+=len(raw);digest.update(raw)
            require(size<=ref['bytes'],'下载原件复制期间长度增加')
    require((size,digest.hexdigest())==(ref['bytes'],ref['sha256']),'下载原件复制期间SHA或长度改变')
    output.flush();output.seek(0)
    return size,digest.hexdigest()


def capture_verified(home,ref,runtime_dir,*,min_free_bytes=16*1024*1024):
    """仅在运行目录创建自动删除的技术临时文件；研究原件/manifest/任务保持。"""
    home=Path(home);runtime=Path(runtime_dir)
    require(type(min_free_bytes) is int and min_free_bytes>=0,'下载快照磁盘余量无效')
    evidence=current_evidence(home.parent.parent)
    source=evidence.reader.verify(home,ref) if evidence else verified_file(home,ref)
    runtime.mkdir(parents=True,exist_ok=True)
    require(shutil.disk_usage(runtime).free>=ref['bytes']+min_free_bytes,'下载快照磁盘余量不足，请清理运行磁盘后重试')
    output=tempfile.TemporaryFile(mode='w+b',dir=runtime,prefix='acceptance_download_')
    try:
        size,digest=_copy_verified(source,output,ref)
        return VerifiedSnapshot(output,size,digest)
    except BaseException:
        output.close()
        raise
