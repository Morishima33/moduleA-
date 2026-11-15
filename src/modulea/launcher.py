"""Windows与macOS共用的本机启动、状态和正常停止入口；只复用原服务控制。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
import webbrowser

from .config import load_settings
from .service_control import probe_service, runtime_location, stop_service


def start_service(settings, port=8780, *, open_browser=True, timeout=20):
    """持原文件锁后核对同实例；只在确认空端口和启动预检通过时创建一个服务。"""
    from storage import write_lock
    folder = runtime_location(settings)
    folder.mkdir(parents=True, exist_ok=True)
    runtime_location(settings)
    with write_lock(settings.runtime_dir):
        before = probe_service(settings, port)
        if before['state'] == 'running' and before['ready']:
            if open_browser:
                webbrowser.open(before['url'])
            return dict(before, reused=True, message_zh='已识别并复用本目录同实例工作台')
        if before['state'] != 'not_running' or not before['preflight_ready']:
            return dict(before, reused=False, message_zh='启动检查未通过；请按原因处理后重新启动')
        from .platform_preflight import inspect_platform
        platform = inspect_platform(settings, port=port, probe_tools=False)
        if not platform['browse_available']:
            return dict(before, state='preflight_failed', ready=False,
                        reasons_zh=platform['browse_blockers_zh'])
        command = [sys.executable, '-B', '-m', 'modulea', '--data-root', str(settings.data_root),
                   '--runtime-dir', str(settings.runtime_dir), 'serve', '--port', str(port),
                   '--static-dir', str(settings.static_dir), '--no-browser']
        env = dict(os.environ, PYTHONPATH=str(settings.project_root / 'src'),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        log = folder / ('service_start_' + uuid.uuid4().hex + '.log')
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
        with log.open('xb') as stream:
            process = subprocess.Popen(command, cwd=settings.project_root, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != 'nt')
        threading.Thread(target=process.wait,daemon=True,name='modulea-service-reap').start()
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = probe_service(settings, port, timeout=1)
            if value['ready']:
                # 代码、配置或前端在启动中变化时拒绝宣布成功，不停止未知新实例。
                if value['expected'] != before['expected'] or value['actual'].get('pid') != process.pid:
                    return dict(value, state='instance_changed', ready=False, log_path=str(log),
                                reasons_zh=['启动期间代码、目录或实例发生变化，请核对日志'])
                if open_browser:
                    webbrowser.open(value['url'])
                return dict(value, reused=False, log_path=str(log), message_zh='工作台已启动并通过同实例核对')
            if process.poll() is not None:
                return dict(value, state='start_failed', ready=False, exit_code=process.returncode,
                            log_path=str(log), reasons_zh=['服务启动退出，请查看启动日志'])
            time.sleep(.15)
        return dict(before, state='start_pending', ready=False, log_path=str(log),
                    reasons_zh=['尚未确认服务就绪；未重复启动或强制终止进程，请先检查状态与日志'])


def main(argv=None):
    """全部平台使用同一参数和中文结果；停止必须主动给出confirmed。"""
    parser = argparse.ArgumentParser(description='Module A 跨平台运行管理')
    parser.add_argument('action', nargs='?', choices=('start', 'status', 'stop', 'preflight'), default='start')
    parser.add_argument('--port', type=int, default=os.environ.get('MODULEA_PORT', '8780'))
    parser.add_argument('--data-root')
    parser.add_argument('--runtime-dir')
    parser.add_argument('--static-dir')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--confirmed', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        settings = load_settings(data_root=args.data_root, runtime_dir=args.runtime_dir)
        if args.static_dir:
            settings.static_dir = Path(args.static_dir).expanduser().resolve()
        elif settings.static_dir is None:
            settings.static_dir = settings.project_root / 'src/modulea/static'
        if args.action == 'preflight':
            from .platform_preflight import inspect_platform
            result = inspect_platform(settings, port=args.port)
            result['ready'] = result['browse_available']
        elif args.action == 'start':
            result = start_service(settings, args.port, open_browser=not args.no_browser)
        elif args.action == 'stop':
            result = stop_service(settings, args.port, confirmed=args.confirmed)
        else:
            result = probe_service(settings, args.port)
    except (OSError, ValueError, TypeError) as error:
        result = {'state': 'configuration_error', 'ready': False, 'reasons_zh': [str(error)]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print(result.get('message_zh') or '工作台状态：' + result.get('state', 'preflight'), flush=True)
        for note in result.get('reasons_zh', []):
            print(note, flush=True)
        if args.action == 'preflight' and 'checks' in result:
            for row in result['checks']:
                print(row['label_zh'] + '：' + row['detail_zh'], flush=True)
            print('可浏览已有结果：' + ('是' if result['browse_available'] else '否'), flush=True)
            print('科学执行：' + result['science_state_zh'], flush=True)
        if result.get('ready') and result.get('url'):
            print(result['url'], flush=True)
        if result.get('log_path'):
            print('日志：' + result['log_path'], flush=True)
    return 0 if result.get('ready') or result.get('state') == 'stopped' else 3


if __name__ == '__main__':
    raise SystemExit(main())
