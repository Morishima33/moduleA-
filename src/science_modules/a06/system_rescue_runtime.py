"""补救运行的真实工具字节签名；仅在当前进程激活既有Java，不安装或改全局配置。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from contracts import require

VERSION = 'A06.system_rescue_runtime.1'
EXCLUDED = frozenset(('__pycache__', '.git', '.pytest_cache', 'tests', 'test', 'test_data',
                      'testdata', 'test_output', 'docs', 'doc', 'examples', 'example',
                      'html', 'images', 'tmp', 'cache', 'benchmarks'))


def _java_binary(home):
    """只接受实际存在的Java启动文件，兼容合成测试和POSIX解释器。"""
    return next((path for name in ('java.exe', 'java')
                 if (path := Path(home) / 'bin' / name).is_file()), None)


def _java_home():
    """有效JAVA_HOME优先；PATH可能是启动别名，因此从实际java.home取真实目录。"""
    configured = os.environ.get('JAVA_HOME', '').strip().strip('"')
    if configured and _java_binary(Path(configured)):
        return Path(configured).resolve()
    launcher = shutil.which('java')
    require(launcher, '没有可用Java；请配置既有Java后再运行补救')
    try:
        result = subprocess.run([launcher, '-XshowSettings:properties', '-version'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        require(False, '无法核对既有Java实际目录：' + str(error))
    require(result.returncode == 0, '既有Java属性检查失败，不能启动P2Rank')
    match = re.search(r'^\s*java\.home\s*=\s*(.+?)\s*$',
                      (result.stdout or '') + '\n' + (result.stderr or ''), re.MULTILINE)
    require(match is not None, 'Java没有报告实际java.home，不能猜测安装目录')
    home = Path(match.group(1)).resolve()
    require(_java_binary(home), 'Java报告的实际目录缺少启动文件')
    return home


def _scan(folder, predicate):
    """只遍历运行目录，提前跳过测试、文档和缓存，不读无关研究数据。"""
    rows = []
    if not Path(folder).is_dir():
        return rows
    for current, directories, names in os.walk(folder):
        directories[:] = sorted(name for name in directories if name.casefold() not in EXCLUDED)
        for name in sorted(names):
            path = Path(current) / name
            if not name.casefold().startswith(('test_', 'readme', 'license')) and predicate(path):
                rows.append(path)
    return rows


def _native(path):
    """实际加载的Python扩展和共享库必须逐字节绑定，不能以版本元数据代替。"""
    return path.suffix.lower() in ('.pyd', '.dll', '.so', '.dylib') or '.so.' in path.name.lower()


def _package_files(folder, *, data=False):
    """绑定执行源码与原生库；修补模板和力场数据另按实际目录保留。"""
    base = Path(folder)
    return _scan(base, lambda path: path.suffix.lower() == '.py' or _native(path)
                 or (data and (path.suffix.lower() == '.xml'
                               or any(part.casefold() in ('data', 'templates', 'params')
                                      for part in path.relative_to(base).parts[:-1]))))


def _metadata(folder):
    """发行版元数据参与签名，实际源码、模型及原生库仍分别散列。"""
    return sorted(Path(folder).glob('*.dist-info/METADATA'))


def _records(paths):
    """分块读取有效文件，返回可稳定序列化的绝对路径、大小与SHA-256。"""
    output = {}
    for path in sorted({Path(value).resolve() for value in paths}):
        require(path.is_file(), '补救运行依赖文件缺失：' + str(path))
        digest, size = hashlib.sha256(), 0
        with path.open('rb') as stream:
            for raw in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(raw)
                size += len(raw)
        output[str(path)] = {'bytes': size, 'sha256': digest.hexdigest()}
    return output


def signature(tools, repair_packages):
    """只读核对真实工具、模型、修补依赖和解释器；不启动结构准备或修改环境。"""
    tools, repair = Path(tools).resolve(), Path(repair_packages).resolve()
    require(tools.is_dir() and repair.is_dir(), '补救工具目录或修补依赖目录不存在')
    java_home = _java_home()
    java = [_java_binary(java_home)]
    java += [path for name in ('release', 'bin/server/jvm.dll', 'lib/server/libjvm.so',
                               'lib/server/libjvm.dylib') if (path := java_home / name).is_file()]
    executable = Path(sys.executable).resolve()
    python = [executable]
    for folder in {executable.parent, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}:
        python.extend(folder.glob('python*.dll'))

    p2rank = tools / 'environments/p2rank_2.5'
    jars = _scan(p2rank / 'bin', lambda path: path.suffix.lower() == '.jar')
    config = _scan(p2rank / 'config', lambda path: path.suffix.lower() == '.groovy')
    default = p2rank / 'config/default.groovy'
    require(default.is_file(), 'P2Rank实际默认配置缺失')
    selected = re.search(r'''^\s*model\s*=\s*['"]([^'"]+)['"]''',
                         default.read_text('utf-8'), re.MULTILINE)
    require(selected is not None and re.fullmatch(r'[A-Za-z0-9_-]+', selected.group(1)),
            'P2Rank默认配置没有明确模型目录')
    model_folder = p2rank / 'models' / selected.group(1)
    models = _scan(model_folder, lambda path: path.suffix.lower() not in ('.md', '.pyc'))
    models += _scan(p2rank / 'models/_score_transform', lambda path: path.suffix.lower() == '.json')
    require((p2rank / 'prank.bat').is_file() and (p2rank / 'bin/p2rank.jar').is_file()
            and jars and (p2rank / 'config/default.groovy').is_file() and config
            and (model_folder / 'features.txt').is_file()
            and any(path.parent == model_folder and path.name.startswith('model.') for path in models),
            'P2Rank启动器、程序、默认配置或实际模型缺失')

    require((repair / 'pdbfixer/pdbfixer.py').is_file() and (repair / 'openmm').is_dir()
            and _scan(repair / 'openmm', _native) and _metadata(repair),
            '有限侧链修补缺少PDBFixer、OpenMM原生库或发行版元数据')
    repair_files = _metadata(repair)
    for name in ('pdbfixer', 'openmm', 'numpy', 'simtk'):
        repair_files += _package_files(repair / name, data=True)
    for name in ('OpenMM.libs', 'numpy.libs'):
        repair_files += _scan(repair / name, _native)

    runtime_path = tools / 'environments/A06_python_runtime.json'
    require(runtime_path.is_file(), '缺少对接Python运行环境清单')
    try:
        runtime = json.loads(runtime_path.read_text('utf-8'))
    except (ValueError, OSError) as error:
        require(False, '对接Python运行环境清单无法读取：' + str(error))
    require(isinstance(runtime, dict) and runtime.get('schema_version') == 'A06.runtime.1'
            and isinstance(runtime.get('packages'), dict) and runtime['packages'], '对接运行环境清单无效')
    packages = tools / 'environments/docking_packages'
    docking = [runtime_path, *_metadata(packages)]
    for specification in runtime['packages'].values():
        module = specification.get('module') if isinstance(specification, dict) else None
        require(isinstance(module, str) and re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module),
                '对接运行环境模块名称无效')
        folder = packages / module.split('.')[0]
        files = _package_files(folder)
        require(files, '对接运行环境模块缺失：' + module)
        docking += files
    require(_metadata(packages) and (packages / 'meeko/data').is_dir(), '对接依赖元数据或Meeko模板缺失')
    docking += _scan(packages / 'meeko/data', lambda path: path.suffix.lower() != '.pyc')
    for folder in packages.glob('*.libs'):
        docking += _scan(folder, _native)
    return {'schema_version': VERSION, 'java_home': str(java_home), 'python_executable': str(executable),
            'tools_root': str(tools), 'repair_packages': str(repair),
            'files': {'java': _records(java), 'python': _records(python),
                      'p2rank': _records([p2rank / 'prank.bat', *jars, *config, *models]),
                      'repair': _records(repair_files), 'docking': _records(docking)}}


def activate(tools, repair_packages):
    """取得同一字节签名后，只设置当前子进程JAVA_HOME供冻结prank.bat继承。"""
    value = signature(tools, repair_packages)
    os.environ['JAVA_HOME'] = value['java_home']
    return value
