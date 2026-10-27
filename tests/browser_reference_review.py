"""在隔离合成研究中验证共晶页面提交、失败留NA和准备绑定。"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import threading
import time

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))
sys.path.insert(0, str(CODE))
from modulea.api.server import create_server
from modulea.config import Settings
from storage import file_record, new_id, read_json, verified_file
from tests.modulea.test_plan_pockets import PocketReviewTests
from tests.modulea.test_reference_docking import fixture


class CandidateFixture(PocketReviewTests):
    def connect(self, home, packet, folder, progress):
        source = super().connect(home, packet, folder, progress)
        cif = folder / "candidate.cif"
        cif.write_text(fixture(), encoding="utf-8")
        candidate = source["receptors"][0]["candidates"][0]
        candidate["cif"] = file_record(home, cif, "synthetic_structure")
        candidate["spec"]["pdb_id"] = "TEST"
        source["files"].append(candidate["cif"])
        return source


def main():
    parser = argparse.ArgumentParser()
    for name in ("artifact", "static-dir", "tools-root", "browser-path"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.artifact / new_id("browser")
    output.mkdir(parents=True)
    case = CandidateFixture("test_confirmation_revision_preserves_sources_and_na_without_scoring")
    case.setUp()
    try:
        sid = case.sid
        shutil.copytree(case.base.settings.data_root, output / "data")
    finally:
        case.doCleanups()
    settings = Settings(project_root=CODE, data_root=output / "data", runtime_dir=output / "runtime",
                        science_python=sys.executable, science_tools_root=args.tools_root, static_dir=args.static_dir)
    server, app = create_server(settings, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors, posts, responses = [], [], []
    try:
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(args.browser_path), headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(30000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
            page.on("response", lambda response: responses.append((response.status, response.url)) if response.status >= 400 else None)
            page.goto(f"http://127.0.0.1:{server.server_port}/#/studies/{sid}/A06_PREP")
            panel = page.locator("#a06-reference-evidence")
            expect(panel.get_by_text("共晶参考证据核查")).to_be_visible()
            expect(page.get_by_text("一次确认后连续计算", exact=True)).to_have_count(0)
            expect(panel.get_by_role("checkbox")).not_to_be_checked()
            expect(panel.get_by_role("button", name="提交共晶参考复核")).to_be_disabled()
            assert not posts
            panel.locator(".ant-select-selector").first.click()
            page.get_by_text("TEST · LIG · Candidate ligand", exact=False).last.click()
            panel.get_by_role("textbox", name="共晶参考核查人").fill("隔离测试")
            panel.get_by_role("textbox", name="共晶参考核查依据").fill("合成候选缺少序列，验证NA保留")
            panel.get_by_role("checkbox").check()
            panel.get_by_role("button", name="提交共晶参考复核").click()
            def wait_task(kind):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    rows = [r for r in app.tasks.list(sid) if r["kind"] == kind]
                    if rows and rows[0]["state"] not in ("queued", "running"):
                        assert rows[0]["state"] == "succeeded", rows[0]
                        return
                    page.wait_for_timeout(500)
                page.screenshot(path=str(output / "failure.png"), full_page=True, animations="disabled")
                raise AssertionError("任务超时 " + kind + " posts=" + repr(posts) + " errors=" + repr(errors) + " responses=" + repr(responses) + " body=" + page.locator("body").inner_text()[-2500:])
            wait_task("a06_plan_reference_review")
            page.reload()
            binding = page.locator("#a06-reference-preparation-binding")
            expect(binding.get_by_role("button", name="绑定到新版准备")).to_be_disabled()
            binding.get_by_role("textbox", name="参考准备绑定人").fill("隔离测试")
            binding.get_by_role("textbox", name="参考准备绑定依据").fill("核对NA及原因，保存准备")
            binding.get_by_role("checkbox").check()
            binding.get_by_role("button", name="绑定到新版准备").click()
            wait_task("a06_plan_reference_preparation")
            page.reload()
            expect(page.get_by_text("参考证据已绑定新版准备", exact=True)).to_be_visible()
            expect(page.get_by_text("一次确认后连续计算", exact=True)).to_have_count(0)
            manifest = app.kernel.workflow().load(sid)
            review = read_json(verified_file(output / "data" / "studies" / sid,
                                            manifest["analysis_plan_a06_reference_records"][-1]["decision"]))
            packet = read_json(verified_file(output / "data" / "studies" / sid, review["packet"]))
            assert packet["summary"]["na_count"] == 1 and packet["results"][0]["reason_zh"]
            assert not errors, errors
            page.screenshot(path=str(output / "final.png"), full_page=True, animations="disabled")
            browser.close()
        print(json.dumps({"passed": True, "artifact": str(output), "posts": len(posts),
                          "result": "nonempty candidate retained NA; binding completed; no automatic approval"}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
