"""跨平台环境预检：一次列出浏览、计算、版本和芯片架构的实际缺口。"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone

from .service_control import probe_service, runtime_location
from .service_identity import frontend_status

PROFILE = 'ModuleA.platform_tools.1'


def binary_platform(path):
    """读取PE/Mach-O/ELF头，不凭文件后缀把Windows二进制当Mac工具。"""
    with Path(path).open('rb') as stream:
        raw = stream.read(4096)
    if raw[:2] == b'MZ':
        offset = int.from_bytes(raw[60:64], 'little')
        machine = int.from_bytes(raw[offset + 4:offset + 6], 'little')
        return 'Windows', {0x8664: 'x86_64', 0xaa64: 'arm64'}.get(machine, 'unknown')
    if raw[:4] in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf'):
        endian = '<' if raw[:4] == b'\xcf\xfa\xed\xfe' else '>'
        cpu = struct.unpack(endian + 'I', raw[4:8])[0]
        return 'Darwin', {0x100000c: 'arm64', 0x1000007: 'x86_64'}.get(cpu, 'unknown')
    if raw[:4] in (b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf'):
        return 'Darwin', 'universal'
    if raw[:4] == b'\x7fELF':
        return 'Linux', 'unknown'
    return 'unknown', 'unknown'


def _file(path):
    """所有工具记录实际长度和SHA，检查不下载或改动工具。"""
    path = Path(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': digest}


def _run(args):
    """固定argv、超时及UTF-8捕获；不经过shell，不接受浏览器命令。"""
    value = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if value.returncode:
        raise ValueError('工具探测退出码：' + str(value.returncode))
    return value.stdout + '\n' + value.stderr


def verify_profile(settings):
    """明确新平台工具配置；系统、架构、版本及实际工具字节都必须一致。"""
    profile_path = settings.tools_profile
    if not profile_path or not Path(profile_path).is_file():
        raise ValueError('未配置本机tools_profile；旧Windows执行绑定不能在Mac上续算')
    value = json.loads(Path(profile_path).read_text('utf-8'))
    machine = {'aarch64': 'arm64', 'AMD64': 'x86_64', 'arm64': 'arm64'}.get(platform.machine(), platform.machine())
    if value.get('schema_version') != PROFILE or value.get('system') != platform.system() or value.get('machine') != machine:
        raise ValueError('工具配置协议、系统或芯片架构与本机不同')
    if value.get('science_protocol') != 'A06.platform_execution.1':
        raise ValueError('新平台必须使用明确的A06.platform_execution.1，不冒充旧批次重放')
    facts = {'profile': _file(profile_path), 'tools': {}, 'packages': {}}
    for tool, version in (('vina', '1.2.7'), ('java', '19')):
        spec = value.get(tool, {})
        if str(spec.get('version')) != version:
            raise ValueError(tool + '版本必须显式固定为' + version)
        path = Path(spec.get('path', '')).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(tool + '工具不存在或不可执行')
        system, arch = binary_platform(path)
        if system != platform.system() or arch not in (machine, 'universal'):
            raise ValueError(tool + '二进制系统或架构不同，不能直接调用')
        fact = _file(path)
        if fact['sha256'] != spec.get('sha256'):
            raise ValueError(tool + '实际工具SHA与配置不同')
        text = _run([str(path), '--version' if tool == 'vina' else '-version'])
        if tool == 'vina' and not re.search(r'AutoDock Vina\s+v?1\.2\.7\b', text):
            raise ValueError('实际Vina版本不是1.2.7')
        if tool == 'java' and not re.search(r'version "19(?:[.\"])', text):
            raise ValueError('实际Java版本不是本配置固定19')
        facts['tools'][tool] = dict(fact, version=version, system=system, machine=arch)
    p2 = value.get('p2rank', {})
    base = Path(p2.get('path', '')).expanduser()
    expected = p2.get('files', {})
    if p2.get('version') != '2.5' or not expected or not all(
            name in expected for name in ('bin/p2rank.jar', 'config/default.groovy')):
        raise ValueError('P2Rank必须固定2.5及jar、配置、实际模型文件SHA清单')
    p2facts = []
    for name, digest in expected.items():
        target = (base / name).resolve()
        if not target.is_relative_to(base.resolve()):
            raise ValueError('P2Rank文件清单路径越界')
        item = _file(target)
        if item['sha256'] != digest:
            raise ValueError('P2Rank配置或模型SHA不同：' + name)
        p2facts.append(item)
    if not any(name.startswith('models/') for name in expected):
        raise ValueError('P2Rank缺少实际模型SHA清单')
    facts['tools']['p2rank'] = {'version': '2.5', 'files': p2facts}
    packages = value.get('packages', {})
    required = {'rdkit', 'meeko', 'gemmi', 'numpy', 'scipy', 'pdbfixer', 'openmm'}
    if not required <= set(packages) or any(not isinstance(x, str) or not x for x in packages.values()):
        raise ValueError('结构准备依赖必须逐项固定版本：' + '、'.join(sorted(required)))
    if any(packages.get(name)!=version for name,version in (('meeko','0.8.0'),('pdbfixer','1.12.0'),('openmm','8.4.0'))):
        raise ValueError('原生准备固定Meeko0.8.0、PDBFixer1.12.0、OpenMM8.4.0；不得静默替换')
    script = ('import importlib,importlib.metadata,json,platform; names=' + repr(packages) + '; '
              'print(json.dumps({"machine":platform.machine(),"packages":{n: '
              '{"version":importlib.metadata.version(n),"origin":importlib.import_module(n).__file__} for n in names}}))')
    probe = json.loads(_run([settings.science_python, '-I', '-B', '-c', script]).strip())
    actual_arch = {'aarch64': 'arm64', 'AMD64': 'x86_64'}.get(probe['machine'], probe['machine'])
    if actual_arch != machine or any(probe['packages'][name]['version'] != version for name, version in packages.items()):
        raise ValueError('科学Python芯片或实际依赖版本与新平台配置不同')
    facts['packages'] = probe['packages']
    facts['python'] = _file(settings.science_python)
    return value, facts


def inspect_platform(settings, *, port=8780, probe_tools=True):
    """一次汇总全部基础缺口；浏览与执行分别报告，预检不认作科学验收。"""
    checks = []
    blockers = []
    def add(key, label, passed, detail, *, browsing=False):
        checks.append({'id': key, 'label_zh': label, 'passed': passed, 'detail_zh': detail})
        if browsing and not passed:
            blockers.append(detail)
    add('platform', '系统与芯片', platform.system() in ('Windows', 'Darwin'), platform.system() + ' / ' + platform.machine())
    add('python', '工作台Python', sys.version_info >= (3, 11), sys.version, browsing=True)
    frontend = frontend_status(settings.static_dir)
    add('frontend', '前端构建', frontend['ready'], '构建原件齐全' if frontend['ready'] else '；'.join(frontend['errors_zh']), browsing=True)
    add('data', '数据目录', settings.data_root.is_dir() and os.access(settings.data_root, os.R_OK),
        '目录可读' if settings.data_root.is_dir() and os.access(settings.data_root, os.R_OK) else '配置的数据目录不存在或不可读', browsing=True)
    try:
        runtime_location(settings)
        ancestor = Path(settings.runtime_dir)
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        writable = os.access(ancestor, os.W_OK)
        add('runtime', '运行目录权限', writable, '运行目录父级可写' if writable else '运行目录不可写', browsing=True)
    except ValueError as error:
        add('runtime', '运行目录权限', False, str(error), browsing=True)
    port_info = probe_service(settings, port)
    usable = port_info['ready'] or port_info['state'] == 'not_running'
    add('port', '本机端口', usable, '同实例已运行' if port_info['ready'] else '端口可用' if usable else '；'.join(port_info['reasons_zh']), browsing=True)
    from .__main__ import probe_science_python
    science = probe_science_python(settings.science_python) if probe_tools else {'passed': False, 'error_zh': '本次启动仅核对浏览环境；科学依赖未探测'}
    add('science_python', '科学Python及依赖', science['passed'], science.get('error_zh') or
        ('依赖导入入口存在' if science['passed'] else '缺少：' + '、'.join(k for k,v in science.get('dependencies', {}).items() if not v)))
    facts = None
    configured={}
    if settings.tools_profile and Path(settings.tools_profile).is_file():
        try:configured=json.loads(Path(settings.tools_profile).read_text('utf-8'))
        except (ValueError,OSError):pass
    for key,label in (('vina','Vina 1.2.7'),('java','固定Java 19'),('p2rank','P2Rank 2.5及模型')):
        spec=configured.get(key,{})
        path=Path(spec.get('path',''))
        ready=bool(spec.get('path') and (path.is_dir() if key=='p2rank' else path.is_file()))
        add(key,label,ready,'已提供工具路径，版本、架构与SHA继续核对' if ready else '未配置或缺少'+label+'；结构准备或对接执行不可用')
    for key,label in (('openmm','OpenMM原生修补依赖'),('pdbfixer','PDBFixer修补依赖')):
        ready=bool(configured.get('packages',{}).get(key))
        add(key,label,ready,'已明确版本，实际导入继续核对' if ready else '未固定'+label+'版本；有限侧链修补不可用')
    try:
        if not probe_tools:
            raise ValueError('未探测工具；浏览可用不代表科学执行可用')
        _, facts = verify_profile(settings)
        add('tools', 'Vina、Java、P2Rank及结构准备环境', True, '本机工具、模型、配置、架构和版本核对通过')
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        add('tools', 'Vina、Java、P2Rank及结构准备环境', False, str(error))
    for name in ('font_regular', 'font_bold'):
        font = getattr(settings, name)
        add(name, '中文绘图字体' + ('常规' if name.endswith('regular') else '粗体'),
            bool(font and font.is_file()), '已配置本机字体' if font and font.is_file() else '未配置可用中文字体，最终图件导出不可用')
    science_ready=bool(facts and science['passed'] and not blockers and
        all(getattr(settings,name) and getattr(settings,name).is_file() for name in ('font_regular','font_bold')))
    return {'schema_version': 'ModuleA.platform_preflight.1', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'system': platform.system(), 'machine': platform.machine(), 'checks': checks,
            'browse_available': not blockers, 'browse_blockers_zh': blockers,
            'toolchain_available': bool(facts and science['passed'] and not blockers),
            'science_available': science_ready,
            'science_state_zh': '本平台新协议可明确提交；worker完整核源码与实际依赖后执行，人工复核和旧批恢复另核' if science_ready
                else '依赖或平台绑定尚不齐备；已有结果可按浏览检查单独查看',
            'execution_profile': PROFILE, 'science_protocol':'A06.platform_execution.1','tool_evidence': facts,
            'same_batch_resume_verified': False, 'scientific_validation_performed': False,
            'note_zh': '预检不下载、不重算、不批准；迁移历史结果与恢复原计算分别核验，旧Windows批次不自动升级。'}
