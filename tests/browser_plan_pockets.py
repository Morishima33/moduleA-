"""真实HTTP、浏览器和隔离子进程验收；数据全部来自合成夹具。"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import threading
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'src'))
sys.path.insert(0, str(CODE))

from modulea.api.server import create_server
from modulea.config import Settings
from storage import new_id
from tests.modulea.test_plan_pockets import PocketReviewTests


def main():
    """独立样本不写正式研究；保留图像、任务结果及验收记录。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--static-dir', type=Path, required=True)
    parser.add_argument('--tools-root', type=Path, required=True)
    parser.add_argument('--browser-path', type=Path, required=True)
    args = parser.parse_args()
    output = args.artifact / new_id('browser')
    output.mkdir(parents=True, exist_ok=False)
    case = PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
    case.setUp()
    try:
        sid = case.sid
        shutil.copytree(case.base.settings.data_root, output/'sample-data')
    finally:
        case.doCleanups()
    settings = Settings(project_root=CODE, data_root=output/'sample-data', runtime_dir=output/'sample-runtime',
                        science_python=sys.executable, science_tools_root=args.tools_root, static_dir=args.static_dir)
    server, app = create_server(settings, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    checks, errors, posts, console_errors, http_errors = [], [], [], [], []
    try:
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(args.browser_path), headless=True)
            try:
                page = browser.new_page(viewport={'width':1440,'height':1100})
                page.set_default_timeout(30000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
                page.on('response', lambda response: http_errors.append({'url':response.url,'status':response.status}) if response.status >= 400 else None)
                page.on('request', lambda req: posts.append(req.url) if req.method == 'POST' else None)
                page.goto(base+'/#/plan-pockets/'+sid)
                expect(page.get_by_role('heading',name='新版预测口袋核查')).to_be_visible()
                expect(page.get_by_text('本版可用组合 0，NA 4，已评分 0')).to_be_visible()
                checkbox = page.get_by_role('checkbox')
                expect(checkbox).not_to_be_checked()
                expect(page.get_by_role('button',name='保存口袋决定并复验')).to_be_disabled()
                assert not posts, 'GET或首次打开页面不应提交决定'
                checks.append('首次读取不POST、未预选确认、保存禁用')
                page.screenshot(path=str(output/'desktop-before.png'),full_page=True,animations='disabled')
                first = page.locator('.ant-select-selector').first
                first.click()
                page.get_by_text('1ABC · 证据可采用',exact=True).last.click()
                page.get_by_role('textbox',name='实际核查人').fill('浏览器隔离核查')
                page.get_by_role('textbox',name='核查依据').fill('合成结构证据测试，采用首位预测作探索')
                expect(page.get_by_role('button',name='保存口袋决定并复验')).to_be_disabled()
                checkbox.check()
                page.get_by_role('button',name='保存口袋决定并复验').click()
                deadline=time.monotonic()+90
                task=None
                while time.monotonic()<deadline:
                    values=app.tasks.list(sid)
                    if values:
                        task=values[0]
                        if task['state'] not in ('queued','running'): break
                    page.wait_for_timeout(500)
                assert task and task['state']=='succeeded', task
                checks.append('真实HTTP POST提交后台任务，隔离子进程成功归档')
                page.reload()
                expect(page.get_by_text('本版可用组合 1，NA 3，已评分 0')).to_be_visible()
                expect(page.get_by_role('checkbox')).not_to_be_checked()
                checks.append('刷新回显已采用决定，组合1可用/3NA/0评分，确认仍未勾选')
                page.screenshot(path=str(output/'desktop-after.png'),full_page=True,animations='disabled')
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_text('证据一致',exact=True).click()
                expect(page.get_by_text('预测残基：A_10')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), '窄屏存在整页横向滚动'
                page.screenshot(path=str(output/'mobile-evidence.png'),full_page=True,animations='disabled')
                checks.append('窄屏展开结构残基、搜索盒和SHA证据，无整页横向滚动')
                assert len(posts)==1, posts
                assert not errors, errors
                assert not console_errors, console_errors
                assert not http_errors, http_errors
                checks.append('只有一次明确POST、无页面脚本异常')
                data={'passed':True,'sample':'synthetic source/structure/prediction; actual Meeko, HTTP, browser and isolated review',
                      'study_id':sid,'data_root':str(settings.data_root),'runtime_dir':str(settings.runtime_dir),
                      'checks':checks,'task':task,'page_errors':errors,'console_errors':console_errors,
                      'http_errors':http_errors,'posts':posts}
                (output/'browser-checks.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'passed':True,'artifact':str(output),'checks':checks},ensure_ascii=False),flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__=='__main__':
    main()
