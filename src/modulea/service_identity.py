"""本机服务的轻量身份与源码/前端签名；不读取研究，不加载科学依赖。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit
import uuid


PROTOCOL = 'ModuleA.local_service.1'
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_INSTANCE = re.compile(r'service_[0-9a-f]{32}\Z')
_EXCLUDED = frozenset({'__pycache__', '.git', '.pytest_cache', '.mypy_cache',
                       '.ruff_cache', 'node_modules', 'data', 'studies',
                       'references', 'runtime', '.runtime', 'static'})


class _References(HTMLParser):
    """只收集入口实际引用的脚本、样式及图标，不递归读取其它网页。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.errors, self.scripts = [], [], 0

    # base会改变引用解析范围，当前本机入口不允许它覆盖静态根。
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'base' and 'href' in values:
            self.errors.append('前端入口不得通过base改变资源目录')
        if tag == 'script' and 'src' in values:
            self.scripts += 1
            self.items.append((values['src'], 'script'))
        if tag == 'link':
            rel = set((values.get('rel') or '').lower().split())
            preload = bool(rel.intersection({'preload', 'prefetch'}))
            kind = ('style' if 'stylesheet' in rel else 'script' if 'modulepreload' in rel
                    else 'style' if preload and values.get('as') == 'style'
                    else 'script' if preload and values.get('as') == 'script'
                    else 'icon' if rel.intersection({'icon', 'apple-touch-icon', 'mask-icon'}) else None)
            if kind:
                self.items.append((values.get('href'), kind))

    # 自闭合标签与普通标签采用同样规则。
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _local_reference(value, kind):
    """将同源引用变为静态根相对路径；拒绝远程、盘符及编码后的越界。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('前端资源引用为空')
    value = value.strip()
    if any(ord(ch) < 32 for ch in value) or '\\' in value:
        raise ValueError('前端资源路径含非法字符')
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith('//'):
        raise ValueError('前端入口不得引用远程或非本地资源')
    decoded = unquote(parsed.path, errors='strict')
    if '\\' in decoded or ':' in decoded or any(ord(ch) < 32 for ch in decoded):
        raise ValueError('前端资源路径含非法字符')
    parts = PurePosixPath(decoded.lstrip('/')).parts
    if not parts or '..' in parts or '%' in decoded:
        raise ValueError('前端资源路径越界或编码无效')
    path = PurePosixPath(*parts)
    if kind == 'script' and path.suffix.lower() not in ('.js', '.mjs'):
        raise ValueError('前端脚本引用必须为JS资源')
    if kind == 'style' and path.suffix.lower() != '.css':
        raise ValueError('前端样式引用必须为CSS资源')
    return path.as_posix()


def _contained_bytes(root, relative):
    """只读规范静态根以内的实际文件，符号链接或目录联接不能逃逸。"""
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('前端资源链接越界或不是文件')
    return path.read_bytes()


def frontend_status(static_dir):
    """返回入口及其实际引用资源的摘要；缺失或不安全时给出中文原因。"""
    result = {'ready': False, 'index_sha256': None, 'assets': [], 'errors_zh': []}
    if static_dir is None:
        result['errors_zh'].append('未配置前端静态目录')
        return result
    try:
        root = Path(static_dir).resolve(strict=True)
        content = _contained_bytes(root, 'index.html')
        result['index_sha256'] = hashlib.sha256(content).hexdigest()
        parser = _References()
        parser.feed(content.decode('utf-8-sig'))
        parser.close()
        result['errors_zh'].extend(parser.errors)
        if not parser.scripts:
            result['errors_zh'].append('前端入口没有引用可运行的JS资源')
        references = set()
        for reference, kind in parser.items:
            try:
                references.add(_local_reference(reference, kind))
            except (ValueError, UnicodeError) as exc:
                result['errors_zh'].append(str(exc))
        for relative in sorted(references):
            try:
                data = _contained_bytes(root, relative)
                result['assets'].append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
            except (OSError, ValueError) as exc:
                result['errors_zh'].append(f'前端资源不可用：{relative}（{type(exc).__name__}）')
    except (OSError, ValueError, UnicodeError) as exc:
        result['errors_zh'].append(f'前端入口不可用（{type(exc).__name__}）')
    result['errors_zh'] = sorted(set(result['errors_zh']))
    result['ready'] = not result['errors_zh']
    return result


def _source_records(project_root):
    """稳定枚举实际源码，不依赖Git；缓存、数据与未引用构建不参与。"""
    root = Path(project_root).resolve(strict=True)
    source = root / 'src'
    if not source.is_dir() or not source.resolve().is_relative_to(root):
        raise ValueError('项目源码目录不存在或越界')
    paths = [path for path in source.iterdir() if path.is_file() and path.suffix.lower() in ('.py', '.r')]
    for name in ('modulea', 'science_modules'):
        base = source / name
        if not base.is_dir() or not base.resolve().is_relative_to(root):
            raise ValueError(f'项目源码目录不存在或越界：{name}')
        for current, dirs, files in os.walk(base, followlinks=False, onerror=_raise_read_error):
            dirs[:] = sorted(item for item in dirs if item.lower() not in _EXCLUDED)
            for item in dirs:
                child = Path(current)/item
                if child.is_symlink() or getattr(child, 'is_junction', lambda: False)():
                    raise ValueError('项目源码子目录不能为链接')
            paths.extend(Path(current)/item for item in sorted(files) if Path(item).suffix.lower() in ('.py', '.r'))
    records = []
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('项目源码文件链接越界')
        content = path.read_bytes()
        records.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
    return records


def _raise_read_error(error):
    """源码子目录不可读时明确失败，不能把不完整遍历当成完整签名。"""
    raise error


def implementation_signature(project_root, static_dir=None):
    """对实际源码及本次入口引用的前端字节确定性签名，不触碰研究。"""
    record = {'schema_version': PROTOCOL, 'source': _source_records(project_root),
              'frontend': frontend_status(static_dir)}
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def expected_identity(settings):
    """仅从本机可信配置规范化目录并计算当前期望实现，供纯比较使用。"""
    result = {key: str(Path(getattr(settings, key)).expanduser().resolve())
              for key in ('project_root', 'data_root', 'runtime_dir')}
    result['static_dir'] = str(Path(settings.static_dir).expanduser().resolve()) if settings.static_dir is not None else None
    result['code_signature'] = implementation_signature(result['project_root'], result['static_dir'])
    return result


class ServiceIdentity:
    """每次进程启动固定实例编号及加载签名，描述时仅轻量检查静态资源。"""
    def __init__(self, settings):
        self._expected = expected_identity(settings)
        self.instance_id = 'service_' + uuid.uuid4().hex
        self.pid = os.getpid()
        self.started_at = datetime.now(timezone.utc).isoformat()

    # 描述不重扫源码、不加载Workflow，科学核验状态明确为未执行。
    def describe(self, port):
        return {'schema_version': PROTOCOL, 'instance_id': self.instance_id,
                'pid': self.pid, 'started_at': self.started_at, 'port': port,
                **self._expected, 'frontend': frontend_status(self._expected['static_dir']),
                'scientific_validation_performed': False}


def compare_identity(actual, expected, port):
    """纯比较已规范本机期待值，不解析、连接或访问响应中任意路径。"""
    errors = []
    if not isinstance(actual, dict):
        return ['服务身份响应不是JSON对象']
    if actual.get('schema_version') != PROTOCOL:
        errors.append('服务身份协议不匹配')
    if type(port) is not int or not 1 <= port <= 65535 or type(actual.get('port')) is not int or actual['port'] != port:
        errors.append('服务端口不匹配或类型无效')
    if not isinstance(actual.get('instance_id'), str) or not _INSTANCE.fullmatch(actual['instance_id']):
        errors.append('服务实例编号无效')
    if type(actual.get('pid')) is not int or actual['pid'] <= 0:
        errors.append('服务进程编号无效')
    try:
        if not isinstance(actual.get('started_at'), str):
            raise ValueError('invalid started_at')
        started = datetime.fromisoformat(actual['started_at'])
        if started.tzinfo is None or started.utcoffset() is None:
            raise ValueError('missing timezone')
    except ValueError:
        errors.append('服务启动时间无效')
    for key in ('project_root', 'data_root', 'runtime_dir', 'static_dir'):
        value = actual.get(key)
        valid = (value is None if key == 'static_dir' and expected.get(key) is None else isinstance(value, str) and bool(value))
        if not valid or value != expected.get(key):
            errors.append(f'服务目录不匹配：{key}')
    signature = actual.get('code_signature')
    if not isinstance(signature, str) or not _SHA.fullmatch(signature) or signature != expected.get('code_signature'):
        errors.append('服务代码或前端签名不匹配')
    frontend = actual.get('frontend')
    if not isinstance(frontend, dict) or frontend.get('ready') is not True:
        errors.append('服务前端资源未就绪')
    elif not isinstance(frontend.get('index_sha256'), str) or not _SHA.fullmatch(frontend['index_sha256']) or not isinstance(frontend.get('assets'), list) or not frontend['assets']:
        errors.append('服务前端资源摘要无效')
    else:
        if frontend.get('errors_zh') != []:
            errors.append('服务前端资源存在错误')
        for asset in frontend['assets']:
            if (not isinstance(asset, dict) or not isinstance(asset.get('path'), str) or not asset['path']
                    or not isinstance(asset.get('sha256'), str) or not _SHA.fullmatch(asset['sha256'])
                    or type(asset.get('bytes')) is not int or asset['bytes'] < 0):
                errors.append('服务前端资源条目无效')
                break
    if actual.get('scientific_validation_performed') is not False:
        errors.append('服务身份不得冒充科学核验')
    return errors
