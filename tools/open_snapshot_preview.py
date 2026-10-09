"""打开独立研究快照的重构核查页面；指定数据、运行目录，保留原项目。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

# 固定本仓库的代码根目录，资料路径由调用方传入。
CODE = Path(__file__).resolve().parents[1]

# 本机端口会话探测不读取大归档，避免把慢读取误判为服务未启动。
def alive(url):
    try:
        with urllib.request.urlopen(url + 'api/v1/session', timeout=3) as response:
            json.load(response)
        return True
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            return False
        raise RuntimeError('核查端口暂时无法响应，请稍后重试；不会重复启动服务。') from error

# 查询只读接口；不发送凭据到外部，不触发复核或科学任务。
def get(url, endpoint):
    with urllib.request.urlopen(url + endpoint, timeout=30) as response:
        return json.load(response)

# 启动时核对研究及A01版本，避免打开同名研究的旧快照。
def validate(url, data):
    expected = {}
    for path in (data / 'studies').glob('*/manifest.json'):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if not manifest.get('trashed'):
            expected[manifest['study_id']] = manifest['current'].get('A01')
    cards = get(url, 'api/v1/studies')['items']
    if not expected or {c['study']['study_id'] for c in cards} != set(expected):
        raise RuntimeError('此端口的数据与指定核查快照不一致。')
    if any(not c.get('archive_ok') for c in cards):
        raise RuntimeError('快照归档未通过校验，不能跳过指纹核验。')
    for study_id, run_id in expected.items():
        if run_id:
            view = get(url, f'api/v1/studies/{study_id}/modules/A01')
            if (view.get('run') or {}).get('run_id') != run_id:
                raise RuntimeError('此端口仍在读取旧A01版本，请检查启动参数。')
    return cards

# 所有运行日志均在指定运行目录；同一快照端口已启动时直接复用。
def main():
    parser = argparse.ArgumentParser(description='打开重构研究快照核查页')
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--port', type=int, default=18883)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    data, runtime = Path(args.data_root).resolve(), Path(args.runtime_dir).resolve()
    if not (data / 'studies').is_dir():
        raise RuntimeError('指定数据目录中没有 studies，请先准备独立核查快照。')
    if not 1 <= args.port <= 65535:
        raise RuntimeError('端口必须在1—65535之间。')
    url = f'http://127.0.0.1:{args.port}/'
    reused = alive(url)
    if not reused:
        runtime.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHONPATH=str(CODE / 'src'), MODULEA_DATA_ROOT=str(data),
                   MODULEA_SCIENCE_PYTHON=args.python, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        command = [args.python, '-B', '-m', 'modulea', '--data-root', str(data),
                   '--runtime-dir', str(runtime), 'serve', '--port', str(args.port), '--no-browser']
        with (runtime / 'server.stdout.log').open('ab') as stdout, (runtime / 'server.stderr.log').open('ab') as stderr:
            process = subprocess.Popen(command, cwd=CODE, env=env, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        (runtime / 'server.pid').write_text(str(process.pid), encoding='ascii')
        for _ in range(40):
            time.sleep(.25)
            if alive(url):
                break
            if process.poll() is not None:
                raise RuntimeError('核查服务启动失败，请查看运行目录中的 server.stderr.log。')
        else:
            raise RuntimeError('核查服务启动超时，请查看独立运行日志。')
    cards = validate(url, data)
    print(json.dumps({'url': url, 'reused': reused, 'data_root': str(data),
                      'studies': [{'id': c['study']['study_id'], 'archive_ok': c['archive_ok'],
                                   'approved': c['progress']['approved']} for c in cards]}, ensure_ascii=False))
    print('这是独立研究快照；原项目审批记录保持原样，显示旧批准不代表重构实现验收通过。')
    if not args.no_browser:
        webbrowser.open(url)
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('无法打开核查页：' + str(error), file=sys.stderr)
        raise SystemExit(1)
