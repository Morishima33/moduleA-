"""A06精准下拉浏览器核查：读取页面，所有写请求在浏览器拦截，不修改研究。"""

import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run(base, study_id, artifact):
    """验证单组定位、队列去重、上传独立绑定及只读门控，并保存界面证据。"""
    artifact.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=60000)
    checks, posts, errors = [], [], []
    completed = False
    cached = {}
    read_only = [False]

    def passed(name):
        checks.append(name)
        print("通过：" + name, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1040})
        page.set_default_timeout(180000)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def isolate(route):
            request = route.request
            headers = {
                "Access-Control-Allow-Origin": request.headers.get("origin", base.rstrip("/")),
                "Access-Control-Allow-Headers": "Content-Type, X-ModuleA-Token",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            }
            if request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
                return
            if request.method == "POST":
                posts.append(
                    {
                        "url": request.url,
                        "body": (request.post_data_buffer or b"").decode("utf-8", errors="replace"),
                    }
                )
                route.fulfill(
                    status=422,
                    headers=headers,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "error": {
                                "code": "BROWSER_ISOLATED",
                                "message_zh": "隔离核查已捕获请求，未写入研究",
                            }
                        }
                    ),
                )
                return
            if request.url.endswith(f"/studies/{study_id}/modules/A06"):
                if not cached:
                    response = route.fetch(timeout=180000)
                    cached.update(response.json())
                payload = deepcopy(cached)
                if read_only[0]:
                    payload["docking_artifacts"]["enabled"] = False
                    payload["docking_artifacts"]["disabled_reason_zh"] = "隔离只读展示核查"
                route.fulfill(
                    headers=headers, content_type="application/json", body=json.dumps(payload)
                )
                return
            # 开发页的隔离传输仅用于UI核查，生产服务的同源/CORS保护不变。
            response = route.fetch(timeout=180000)
            route.fulfill(response=response, headers={**response.headers, **headers})

        page.route("**/api/v1/**", isolate)
        try:
            page.goto(base.rstrip("/") + f"/#/studies/{study_id}/A06")
            section = page.get_by_role("region", name="对接出图与图片上传")
            expect(section).to_be_visible(timeout=180000)
            page.set_default_timeout(20000)
            eligible = [p for p in cached["docking_artifacts"]["pairs"] if p["eligible"]]
            assert eligible, "核查来源须有可选组合"
            initial_posts = len(posts)
            expect(section.get_by_role("combobox", name="出图受体", exact=True)).to_be_disabled()
            expect(
                section.get_by_role("combobox", name="图片对应受体", exact=True)
            ).to_be_disabled()
            expect(section.get_by_text("批量队列（0组）", exact=True)).to_be_visible()
            expect(section.get_by_role("table")).not_to_be_visible()
            section.screenshot(path=str(artifact / "a06-selectors-default.png"))
            passed("默认无选择，受体等待成分，批量队列折叠且不显示全组合表")

            def choose(label, option):
                field = section.get_by_role("combobox", name=label, exact=True)
                field.evaluate("el => el.closest('.ant-select').scrollIntoView({block: 'center'})")
                field.locator(
                    "xpath=ancestor::div[contains(@class,'ant-select-selector')][1]"
                ).click()
                field.fill(option)
                page.locator(
                    ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content"
                ).get_by_text(option, exact=True).click(timeout=15000)

            def pair_select(pair):
                choose("出图成分", pair["compound_name_zh"])
                expect(section.get_by_role("combobox", name="出图受体", exact=True)).to_have_value(
                    ""
                )
                choose("出图受体", pair["target_zh"])

            def click_button(label):
                control = section.locator("button").filter(has_text=label).first
                control.evaluate("el => el.scrollIntoView({block: 'center'})")
                control.click()

            first = eligible[0]
            pair_select(first)
            expect(
                section.get_by_text(
                    f"{first['compound_name_zh']} × {first['target_zh']}", exact=True
                )
            ).to_be_visible()
            click_button("加入批量队列")
            expect(
                section.get_by_role("button", name="已加入批量队列", exact=True)
            ).to_be_disabled()
            expect(section.get_by_text("批量队列（1组）", exact=True)).to_be_visible()
            click_button("使用上方组合")
            expected_upload = f"当前上传对象：{first['compound_name_zh']} × {first['target_zh']}"
            expect(section.get_by_text(expected_upload, exact=True)).to_be_visible()
            passed("搜索定位一个组合，加入队列去重，显式复制到上传对象")

            other = next(p for p in eligible if p["compound_id"] != first["compound_id"])
            pair_select(other)
            expect(section.get_by_text(expected_upload, exact=True)).to_be_visible()
            click_button("加入批量队列")
            expect(section.get_by_text("批量队列（2组）", exact=True)).to_be_visible()
            assert len(posts) == initial_posts, posts[initial_posts:]
            passed("更换成分清空出图受体，上传对象保持；选择和加队列零写请求")
            section.screenshot(path=str(artifact / "a06-selectors-independent-upload.png"))

            section.get_by_text("批量队列（2组）", exact=True).click()
            expect(section.get_by_role("table")).to_be_visible()
            click_button("生成队列出图包")
            expect(
                section.get_by_text("隔离核查已捕获请求，未写入研究", exact=True)
            ).to_be_visible()
            body = json.loads(posts[-1]["body"])
            assert body["pair_keys"] == [first["pair_key"], other["pair_key"]]
            assert posts[-1]["url"].endswith("/actions/pair_packages")
            passed("批量生成按钮只提交去重队列两组，写请求被隔离拦截")
            section.get_by_text("批量队列（2组）", exact=True).click()

            unready = next((p for p in eligible if not p["package_url"]), None)
            if unready:
                pair_select(unready)
                click_button("生成本组出图包")
                page.wait_for_function("document.querySelector('button') !== null")
                expect(section.get_by_role("combobox", name="出图成分", exact=True)).to_be_enabled()
                assert json.loads(posts[-1]["body"])["pair_keys"] == [unready["pair_key"]]
                passed("单组生成按钮只提交当前一组，未触发全部出图包")
            ready = next((p for p in eligible if p["package_url"]), None)
            if ready:
                pair_select(ready)
                link = section.get_by_role("link", name="下载本组出图包", exact=True)
                expect(link).to_have_attribute("href", ready["package_url"])
                passed("已准备组合直接显示原同源下载地址")

            section.get_by_label("图片说明", exact=True).fill("浏览器隔离核查，不写入研究")
            section.get_by_label("选择对接结果图片", exact=True).set_input_files(
                {
                    "name": "isolated.png",
                    "mimeType": "image/png",
                    "buffer": base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
                    ),
                }
            )
            click_button("上传并保存图片")
            expect(section.get_by_role("combobox", name="出图成分", exact=True)).to_be_enabled()
            assert posts[-1]["url"].endswith("/actions/figure")
            assert f'name="pair_key"\r\n\r\n{first["pair_key"]}\r\n' in posts[-1]["body"]
            passed("单组图片提交仍绑定独立上传组合，未随上方变化")
            scope = section.get_by_role("combobox", name="图片对应范围", exact=True)
            scope.evaluate("el => el.closest('.ant-select').scrollIntoView({block: 'center'})")
            scope.locator("xpath=ancestor::div[contains(@class,'ant-select-selector')][1]").click()
            page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content').get_by_text('本批综合图',exact=True).click()
            expect(
                section.get_by_role("combobox", name="图片对应成分", exact=True)
            ).not_to_be_visible()
            expect(section.get_by_text("当前上传对象：本批综合图", exact=True)).to_be_visible()
            click_button("上传并保存图片")
            expect(section.get_by_role("combobox", name="出图成分", exact=True)).to_be_enabled()
            assert 'name="pair_key"\r\n\r\n\r\n' in posts[-1]["body"]
            passed("本批综合图显式选择且提交空组合键")

            read_only[0] = True
            page.reload()
            expect(section.get_by_text("隔离只读展示核查", exact=True)).to_be_visible()
            for label in ("出图成分", "出图受体", "图片对应成分", "图片对应受体", "图片对应范围"):
                expect(section.get_by_role("combobox", name=label, exact=True)).to_be_disabled()
            expect(
                section.get_by_role("button", name="上传并保存图片", exact=True)
            ).to_be_disabled()
            passed("只读上下文禁用出图与上传选择和写按钮")
            read_only[0] = False
            page.set_viewport_size({"width": 390, "height": 900})
            page.reload()
            expect(section.get_by_role("combobox", name="出图成分", exact=True)).to_be_enabled()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            section.screenshot(path=str(artifact / "a06-selectors-mobile.png"))
            passed("390px窄屏不产生整页横向滚动")
            assert not errors, errors
            passed("浏览器无未捕获控制台异常，真实研究写请求全部拦截")
            completed = True
        finally:
            if not completed:
                page.screenshot(path=str(artifact / "failed.png"), full_page=False)
            (artifact / "proof.json").write_text(
                json.dumps(
                    {
                        "checks": checks,
                        "requests": posts,
                        "page_errors": errors,
                        "study_write_performed": False,
                        "passed": completed and not errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    run(args.base, args.study, args.artifact)
