"""隔离记录原启动夹具与长路径的具体失败条件，不把FileNotFoundError猜成长路径根因。"""
import argparse
import json
import os
from pathlib import Path
import platform
import struct
from tempfile import TemporaryDirectory


def extended(path):
    """Windows同一绝对路径的扩展写法；其他系统保持原路径。"""
    text=str(Path(path).absolute())
    if os.name!='nt' or text.startswith('\\\\?\\'):return Path(text)
    return Path('\\\\?\\UNC\\'+text[2:] if text.startswith('\\\\') else '\\\\?\\'+text)


def probe(path):
    """捕获原生错误码、字符/字节及组件长度；只在临时资料中创建和读回。"""
    value={'path':str(path),'characters':len(str(path)),
        'utf16_units':len(str(path).encode('utf-16-le'))//2,
        'max_component_utf8_bytes':max(len(x.encode('utf-8')) for x in path.parts),
        'max_component_utf16_units':max(len(x.encode('utf-16-le'))//2 for x in path.parts)}
    try:
        path.mkdir(parents=True,exist_ok=True)
        file=path/'读回 检查.txt';file.write_text('Module A路径核对',encoding='utf-8')
        assert file.read_text('utf-8')=='Module A路径核对'
        value['passed']=True
    except OSError as error:
        value.update(passed=False,error_type=type(error).__name__,errno=error.errno,
            winerror=getattr(error,'winerror',None),filename=str(error.filename),message=str(error))
    return value


def main():
    """默认系统临时目录，可指定独立测试父目录，输出只写指定的新JSON。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('--work-dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    settings={'system':platform.system(),'machine':platform.machine(),'python':platform.python_version(),
              'pointer_bits':8*struct.calcsize('P'),'research_files_used':False}
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
                settings['windows_long_paths_enabled']=winreg.QueryValueEx(key,'LongPathsEnabled')[0]
        except OSError as error:settings['windows_long_paths_registry_error']=str(error)
    with TemporaryDirectory(prefix='Module A 中文 路径 ',dir=args.work_dir) as temp:
        root=Path(temp).resolve()
        original=root/('长路径片段 '*12)/('中文目录 '*10)
        long=root/'long'
        while len(str(long))<340:long=long/('中文 空格 路径 '+'x'*24)
        settings['cases']=[dict(case=label,**probe(path)) for label,path in (
            ('original_fixture',original),('original_same_path_extended',extended(original)),
            ('over_320',long),('over_320_same_path_extended',extended(long)))]
    with args.output.open('x',encoding='utf-8') as stream:json.dump(settings,stream,ensure_ascii=False,indent=2)
    print(json.dumps(settings,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
