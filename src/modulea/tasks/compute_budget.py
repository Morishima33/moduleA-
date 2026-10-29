"""跨进程计算位与磁盘事实基础层；只管理运行资源，不修改科学参数或研究。"""
from pathlib import Path
import os
import shutil
import json
import uuid


class ComputeLease:
    """已占用的计算位由持有进程关闭；正常退出和句柄关闭都会释放系统锁。"""
    def __init__(self,stream,index,record_path=None):
        self.stream,self.index=stream,index
        self.record_path=record_path

    def bind(self,task_id,tree):
        """先登记实际进程树再运行科学任务；记录保留到下个持锁者确认树已结束。"""
        if self.stream is None:raise ValueError('计算位已释放')
        record={'schema_version':1,'task_id':task_id,'pid':os.getpid(),'tree':tree}
        temporary=self.record_path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(record,ensure_ascii=False),encoding='utf8')
        temporary.replace(self.record_path)

    def close(self):
        """重复释放无副作用，不删除锁文件或终止任何其他进程。"""
        if self.stream is None:return
        stream,self.stream=self.stream,None
        try:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        finally:stream.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class ComputeBudget:
    """同一运行目录下共享有限计算位；一次尝试不阻塞界面或忙等。"""
    def __init__(self,runtime_dir,slots=1):
        if not isinstance(slots,int) or isinstance(slots,bool) or slots<1:
            raise ValueError('计算位必须为正整数')
        self.folder=Path(runtime_dir)/'compute_slots';self.slots=slots

    def try_acquire(self):
        """返回实际系统锁租约；没有空位时返回None，不启动科学过程。"""
        self.folder.mkdir(parents=True,exist_ok=True)
        for index in range(self.slots):
            stream=(self.folder/f'slot_{index}.lock').open('a+b')
            try:
                stream.seek(0,2)
                if stream.tell()==0:stream.write(b'0');stream.flush()
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except (BlockingIOError,PermissionError):
                stream.close();continue
            except OSError as error:
                stream.close()
                if error.errno in (11,13):continue
                raise
            except BaseException:
                stream.close();raise
            lease=ComputeLease(stream,index,self.folder/f'slot_{index}.json')
            try:
                if lease.record_path.exists():
                    from .process_tree import tree_alive
                    record=json.loads(lease.record_path.read_text('utf8'))
                    if record.get('schema_version')!=1:raise ValueError('计算位记录版本未知')
                    if tree_alive(record['tree']):
                        lease.close();continue
            except BaseException:
                lease.close();raise
            return lease
        return None


def disk_space(path,required_bytes=0):
    """只读磁盘事实；调用者提供有依据的最低字节量，不猜测科学产物总大小。"""
    if not isinstance(required_bytes,int) or isinstance(required_bytes,bool) or required_bytes<0:
        raise ValueError('最低空间须为非负整数字节')
    folder=Path(path).resolve()
    while not folder.exists():
        parent=folder.parent
        if parent==folder:raise ValueError('无法定位目标磁盘')
        folder=parent
    if folder.is_file():folder=folder.parent
    usage=shutil.disk_usage(folder)
    return {'free_bytes':usage.free,'total_bytes':usage.total,'required_bytes':required_bytes,
            'sufficient':usage.free>=required_bytes}
