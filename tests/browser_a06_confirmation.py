"""A06集中确认浏览器回归：虚构研究隔离保存；真实页面仅打开和填写本地建议。"""
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
import argparse
import json
import sys
import threading
import time

from playwright.sync_api import sync_playwright, expect
from tests.modulea.test_source_review import source_fixture
from tests.modulea.test_two_pass import filled
from modulea.config import Settings
from modulea.api.server import create_server


def run(base, sid, artifact, isolated=None):
    """阻断预检接口仍须立即打开窗口；正式提交继续经过服务端核查。"""
    checks, errors, posts = [], [], []
    def passed(name):
        checks.append(name)
        print("通过：" + name, flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        try:
            page = browser.new_page(viewport={"width": 1450, "height": 1000})
            page.set_default_timeout(180000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
            page.goto(base + "/#/studies/" + sid + "/A06_PREP")
            section = page.locator("#a06-two-pass")
            entry = section.get_by_role("button", name="查看汇总与确认", exact=True)
            expect(entry).to_be_enabled(timeout=180000)
            def unavailable(route):
                route.fulfill(status=503, content_type="application/json",
                              body=json.dumps({"error": {"code": "TEST_DELAY",
                              "message_zh": "隔离模拟核查接口不可用"}}))
            page.route("**/actions/check_two_pass", unavailable)
            count = len(posts)
            start = time.monotonic()
            entry.click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible(timeout=1500)
            expect(dialog.get_by_role("button", name="填写全部建议（仅草案）",
                                      exact=True)).to_be_visible(timeout=1500)
            elapsed = time.monotonic() - start
            assert len(posts) == count, posts[count:]
            passed("预检接口不可用时窗口仍立即打开，建议按钮可见且无写请求")
            dialog.get_by_role("button", name="填写全部建议（仅草案）", exact=True).click()
            assert len(posts) == count
            confirmation = dialog.get_by_role("checkbox", name=(
                "我已核对本窗口全部成分、受体与处理依据，确认本轮完整方案；不启动计算"),
                exact=True)
            expect(confirmation).not_to_be_checked()
            passed("一键建议只修改本地表单，不保存、不确认、不计算")
            page.unroute("**/actions/check_two_pass", unavailable)
            if isolated:
                workflow, app, original = isolated
                # 延迟草案写接口，真实验证可见进度并避免重复提交。
                def delay_draft(route):
                    time.sleep(1)
                    route.continue_()
                page.route("**/actions/two_pass_draft", delay_draft)
                with page.expect_response(lambda r: r.url.endswith("/actions/two_pass_draft")
                                          and r.request.method == "POST") as response:
                    dialog.get_by_role("button", name="保存未完成草案", exact=True).click()
                    expect(section.get_by_role("status").filter(
                        has_text="正在核查或保存")).to_be_visible()
                    expect(section.locator("button").filter(has_text="保存核查草案")).to_be_disabled()
                assert response.value.status == 201, response.value.text()
                expect(dialog).not_to_be_visible()
                page.unroute("**/actions/two_pass_draft", delay_draft)
                passed("保存期间顶部显示进度、阻止重复提交，草案201保存成功")
                page.reload()
                expect(entry).to_be_enabled(timeout=180000)
                entry.click()
                expect(dialog).to_be_visible(timeout=1500)
                expect(confirmation).not_to_be_checked()
                dialog.get_by_label("方案核验人", exact=True).fill("隔离核验人")
                dialog.get_by_label("方案核验依据", exact=True).fill("虚构来源核对，不启动计算")
                confirmation.check()
                with page.expect_response(lambda r: r.url.endswith("/actions/two_pass_plan")
                                          and r.request.method == "POST") as response:
                    dialog.get_by_role("button", name="一次确认完整方案", exact=True).click()
                assert response.value.status == 202, response.value.text()
                task_id = response.value.json()["task"]["task_id"]
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    task = app.tasks.get(task_id)
                    if task["state"] not in ("queued", "running"):
                        break
                    time.sleep(.1)
                assert task["state"] == "succeeded", task
                for key in ("current", "runs", "reviews"):
                    assert workflow.load(sid)[key] == original[key]
                passed("隔离完整提交仍执行服务端验证，只保存方案，不生成科研运行或批准")
                page.reload()
                expect(entry).to_be_enabled(timeout=180000)
                expect(section.get_by_text("方案已确认并保存", exact=True)).to_be_visible()
                entry.click()
                expect(dialog).to_be_visible(timeout=1500)
                expect(confirmation).not_to_be_checked()
                passed("刷新显示已保存方案，整体确认不自动勾选")
            else:
                # 真实研究不点保存或确认，返回后刷新丢弃本地建议。
                dialog.get_by_role("button", name="返回", exact=True).click()
                page.reload()
                expect(entry).to_be_enabled(timeout=180000)
                entry.click()
                expect(dialog).to_be_visible(timeout=1500)
                expect(confirmation).not_to_be_checked()
                passed("真实页面返回与刷新成功，不提交、不更改用户方案")
            page.screenshot(path=str(artifact / "确认窗口.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            page.screenshot(path=str(artifact / "窄屏确认窗口.png"))
            overflow = page.evaluate("""() => ({width: innerWidth, scroll: document.documentElement.scrollWidth, nodes: [...document.querySelectorAll("body *")].map(n=>({tag:n.tagName,cls:n.className,txt:n.innerText?.slice(0,100),right:n.getBoundingClientRect().right,width:n.getBoundingClientRect().width})).filter(n=>n.right>innerWidth+1).slice(0,30)})""")
            (artifact / "overflow.json").write_text(json.dumps(overflow, ensure_ascii=False, indent=2),encoding="utf-8")
            assert overflow["scroll"] <= overflow["width"], overflow
            assert not errors, errors
            passed("窄屏无整页横向溢出、无浏览器脚本错误")
            (artifact / "result.json").write_text(json.dumps({
                "passed": True, "checks": checks, "errors": errors,
                "open_seconds": elapsed, "real_calculation_started": False,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            browser.close()


def main():
    """按参数选择隔离回归或真实页面只读检查，产物始终写指定核查目录。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--real-base")
    parser.add_argument("--study")
    args = parser.parse_args()
    args.artifact.mkdir(parents=True, exist_ok=True)
    if args.real_base:
        if not args.study:
            parser.error("--real-base requires --study")
        return run(args.real_base, args.study, args.artifact)
    root = args.artifact / ("isolated_" + uuid4().hex)
    f, sid, ctx, packet = source_fixture(root)
    plan = filled(ctx)
    r0, r1 = packet["receptors"][:2]
    r0["altloc_codes"] = ["A", "B"]
    packet["choices"] = [
        {"kind": "altloc", "target_id": r0["target_id"], "symbol": r0["symbol"],
         "pdb_id": "1ABC", "round": "first", "options": ["A", "B"],
         "recommended_value": "A", "reason_zh": "虚构构象选择，不表示生物学优劣"},
        {"kind": "route", "target_id": r1["target_id"], "symbol": r1["symbol"],
         "pdb_id": "1ABC", "round": "first", "options": ["adopt"],
         "recommended_value": "adopt", "reason_zh": "虚构路线，仍须实际质控",
         "proposal": plan["receptors"][1]["first"]},
    ]
    for row in packet["receptors"]:
        row.update(missing_residue_count=0, missing_atom_count=0, reason_zh="虚构只读清点")
    source = f.save_source_review(sid, packet)
    del plan["receptors"][0]["first"]["altloc"]
    plan["receptors"][1]["first"] = None
    plan["receptors"][1]["first_reason"] = "虚构路线待确认"
    original = deepcopy(f.load(sid))
    f.save_two_pass_draft(sid, {
        "expected_source": ctx["source_key"], "expected_source_review_id": source["review_id"],
        "expected_plan_id": None, "expected_draft_id": None,
        "draft_id": "draft_" + uuid4().hex, "plan": plan,
        "checked_target_ids": [], "reviewer": "", "note": "隔离来源草案",
    })
    server, app = create_server(Settings(
        project_root=args.project, data_root=root, runtime_dir=root / "runtime",
        static_dir=args.project / "src/modulea/static", science_python=sys.executable,
    ), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run("http://127.0.0.1:" + str(server.server_port), sid, args.artifact,
            (f, app, original))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
