"""完整验收ZIP有界落盘与逐成员SHA校验；不登记研究、不计算、不覆盖已有产物。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import unicodedata
import zipfile

from contracts import ContractError, fingerprint, require
from .bounded_evidence import file_record, verified_file

CHUNK=1024*1024
INVENTORY_NAME='验收目录与指纹.json'
MAX_INLINE_BYTES=8*1024*1024
MAX_METADATA_BYTES=64*1024*1024


def _check(callback):
    """调用者传原任务取消/身份检查；本层不创建另一套任务状态。"""
    if callback:callback()


def _name(value):
    """ZIP路径必须可在Windows和macOS安全解压，禁止歧义或路径逃逸。"""
    require(isinstance(value,str) and value and not any(ch in value for ch in '\\:<>"|?*')
            and not any(ord(ch)<32 or ord(ch)==127 for ch in value),
            '压缩成员名称无效')
    parts=value.split('/')
    require(not PurePosixPath(value).is_absolute() and all(part not in ('','.','..')
        and part==part.rstrip(' .') for part in parts),'压缩成员路径越界或含歧义')
    devices={'con','nul','prn','aux',*[f'com{i}' for i in range(1,10)],*[f'lpt{i}' for i in range(1,10)]}
    require(all(part.split('.')[0].casefold() not in devices for part in parts),'压缩成员包含系统保留名')
    return value


def _entries(home,entries):
    """先核完整成员清单，文件只保留引用；派生小对象不代替来源原件。"""
    require(isinstance(entries,list) and entries,'完整包成员不能为空')
    rows=[];seen={INVENTORY_NAME.casefold()};directories=set()
    for entry in entries:
        require(isinstance(entry,dict) and set(entry)<= {'name','file','data','role','registrations'}
                and {'name','role'}<=set(entry) and ('file' in entry)!=('data' in entry), '完整包成员字段错误')
        name=_name(entry['name']);_remember(name,seen,directories)
        require(isinstance(entry['role'],str) and entry['role'].strip(),'完整包成员角色缺失')
        row={'path':name,'role':entry['role']}
        if 'file' in entry:
            ref=entry['file']
            require(isinstance(ref,dict) and type(ref.get('bytes')) is int and ref['bytes']>=0,'原件登记长度无效')
            path=verified_file(home,ref)
            row.update(bytes=ref['bytes'],sha256=ref['sha256']);source=('file',path,ref)
        else:
            raw=entry['data']
            require(isinstance(raw,bytes) and len(raw)<=MAX_INLINE_BYTES,'派生成员过大或字节无效')
            row.update(bytes=len(raw),sha256=sha256(raw).hexdigest());source=('data',raw,None)
        if 'registrations' in entry:row['registrations']=deepcopy(entry['registrations'])
        rows.append((row,source))
    return rows


def _remember(name,seen,directories):
    """大小写/Unicode等价和文件-目录冲突在创建ZIP前拒绝，避免跨平台解压覆盖。"""
    key=unicodedata.normalize('NFC',name).casefold();parts=key.split('/')
    parents=['/'.join(parts[:i]) for i in range(1,len(parts))]
    require(key not in seen and key not in directories and not any(parent in seen for parent in parents),
            '完整包成员重复、目录冲突或平台等价冲突')
    seen.add(key);directories.update(parents)


def _encoded_metadata(metadata,inventory):
    """目录自哈希排除，与现有验收格式相同；调用者的绑定字段完整保留。"""
    require(isinstance(metadata,dict) and 'files' not in metadata,'完整包元数据不能覆盖成员清单')
    value=deepcopy(metadata);value.update(files=deepcopy(inventory),inventory_self_hash_excluded=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
    require(len(raw)<=MAX_METADATA_BYTES,'完整包目录超过64MiB，保留原件待处理')
    return value,raw


def write_archive(home,destination,entries,metadata,*,check_task=None,min_free_bytes=16*1024*1024):
    """沿旧交付ZIP落盘模式独占创建，逐块核真正写入字节，完整校验后才交调用者登记。"""
    home=Path(home).resolve();destination=Path(destination).resolve()
    require(destination.is_relative_to(home) and destination.parent.is_dir()
            and destination.suffix=='.zip','完整包输出目录越界或尚未建立')
    require(not destination.exists(),'完整包目标已存在，不能覆盖历史或未登记残件')
    require(type(min_free_bytes) is int and min_free_bytes>=0,'完整包磁盘余量无效')
    _check(check_task);rows=_entries(home,entries);inventory=[row for row,_ in rows]
    value,encoded=_encoded_metadata(metadata,inventory)
    raw_bytes=sum(row['bytes'] for row in inventory)+len(encoded)
    # 预留不可压缩数据、ZIP头和运行余量；实际写失败仍保留未登记草案，不视为成功。
    required=raw_bytes+raw_bytes//100+len(rows)*1024+min_free_bytes
    require(shutil.disk_usage(destination.parent).free>=required,'完整包磁盘余量不足，尚未打包')
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
        for row,source in rows:
            _check(check_task);digest=sha256();size=0
            with archive.open(row['path'],'w',force_zip64=True) as output:
                if source[0]=='file':
                    with source[1].open('rb') as stream:
                        for raw in iter(lambda:stream.read(CHUNK),b''):
                            _check(check_task)
                            require(size+len(raw)<=row['bytes'],'完整包写入期间原件长度增加')
                            output.write(raw);size+=len(raw);digest.update(raw)
                else:
                    raw=source[1];output.write(raw);size=len(raw);digest.update(raw)
            require((size,digest.hexdigest())==(row['bytes'],row['sha256']), '完整包写入期间原件改变')
        _check(check_task);archive.writestr(INVENTORY_NAME,encoded)
    validate_archive(destination,inventory,value,check_task=check_task)
    _check(check_task)
    return {'archive':file_record(home,destination,'rescue_acceptance_archive'),
            'inventory':inventory,'metadata':value}


def validate_archive(path,expected_inventory,expected_metadata,*,check_task=None):
    """只信调用者已绑定清单，逐成员复核长度/SHA及CRC，不把ZIP自述当作证明。"""
    require(isinstance(expected_inventory,list) and isinstance(expected_metadata,dict)
            and fingerprint(expected_metadata.get('files'))==fingerprint(expected_inventory), '完整包预期目录不同')
    expected={};names={INVENTORY_NAME.casefold()};directories=set()
    for row in expected_inventory:
        name=_name(row['path']);_remember(name,names,directories);expected[name]=row
    try:
        with zipfile.ZipFile(path) as archive:
            actual=archive.namelist()
            require(len(actual)==len(expected)+1 and set(actual)==set(expected)|{INVENTORY_NAME},
                    '完整包缺成员、重复成员或夹带未登记文件')
            for member in archive.infolist():
                require(stat.S_IFMT(member.external_attr>>16) in (0,stat.S_IFREG)
                        and not member.external_attr&0x10 and not member.is_dir(),
                        '完整包成员不是普通文件，拒绝链接、目录或特殊设备')
            info=archive.getinfo(INVENTORY_NAME)
            require(info.file_size<=MAX_METADATA_BYTES,'完整包目录超过读取预算')
            metadata=json.loads(archive.read(INVENTORY_NAME).decode('utf8'))
            require(fingerprint(metadata)==fingerprint(expected_metadata),'完整包输入、修订或目录改变')
            for name,row in expected.items():
                _check(check_task);require(archive.getinfo(name).file_size==row['bytes'],'完整包成员长度不同')
                digest=sha256();size=0
                with archive.open(name) as stream:
                    for raw in iter(lambda:stream.read(CHUNK),b''):
                        _check(check_task);digest.update(raw);size+=len(raw)
                        require(size<=row['bytes'],'完整包成员解压长度越界')
                require((size,digest.hexdigest())==(row['bytes'],row['sha256']),'完整包成员SHA不同')
    except (OSError,ValueError,KeyError,RuntimeError,zipfile.BadZipFile) as error:
        raise ContractError('完整包无法完整核验：'+str(error)) from error
    return True
