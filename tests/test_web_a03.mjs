// A03真实浏览器验收仅连接临时合成研究。
import fs from "node:fs"; // 读取测试配置。
import path from "node:path"; // 组合工具目录。
import { createRequire } from "node:module"; // 载入已有Playwright。
const require = createRequire(import.meta.url); // 使用当前文件依赖。
const { chromium } = require(path.join(process.env.MODULEA_NODE_MODULES, "playwright")); // 不安装新依赖。
const settings = JSON.parse(fs.readFileSync(0, "utf8")); // 临时服务由测试驱动传入。
const browser = await chromium.launch({ channel: "msedge", headless: true }); // 后台运行Edge。
try { // 始终清理浏览器。
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 } }); // 桌面视图。
    const studyUrl = settings.url + "/study?study=" + settings.study; // 只访问测试研究。
    await page.goto(studyUrl); // 从真实页面启动。
    const card = page.locator("article").filter({ has: page.getByRole("heading", { name: "A03 · 交集与成分候选", exact: true }) }); // 精确选中交集卡片。
    await card.getByLabel("A03运行原因").fill("合成资料浏览器验收"); // 不用于真实科研。
    await card.getByRole("button", { name: "运行A03交集与排序" }).click(); // 运行真实服务端计算。
    await card.getByText("待复核", { exact: true }).waitFor(); // 不能自动批准。
    await card.getByText("其他操作：查看图表、补充资料或重新运行", { exact: true }).click(); // 韦恩图位于当前减负界面的操作折叠区。
    await card.locator("svg").waitFor(); // 韦恩图实际渲染。
    await card.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 两种排序表位于完整结果折叠区。
    await card.getByText("按交集靶点数主排序", { exact: true }).click(); // 展开主排序。
    await card.getByText("按混合Degree参考排序", { exact: true }).click(); // 展开独立参考表。
    await card.getByLabel("复核人", { exact: true }).fill("合成测试复核"); // 测试签署。
    await card.getByLabel("意见或处理理由").fill("交集测试通过，不代表真实基因关联"); // 保存明确理由。
    await card.getByLabel("决定", { exact: true }).selectOption("approved"); // 人工操作模拟。
    await card.getByRole("button", { name: "保存复核决定" }).click(); // 批准交集。
    const select = page.locator("article").filter({ has: page.getByRole("heading", { name: "A03_SELECT · A03主候选确认（仅对接分支）", exact: true }) }); // 选择独立关口。
    await select.getByText(/存在截断处并列/).waitFor(); // 关键问题置顶。
    await select.getByText("填写或修改主候选", { exact: true }).click(); // 打开选择表单。
    await select.getByLabel(/主候选成分编号/).fill("0\n1\n2\n3\n4"); // 默认规则下明确选择五个。
    await select.getByLabel("候选核对人").fill("合成测试复核"); // 不冒用用户。
    await select.getByLabel("候选选择、并列或替换理由").fill("合成测试：核对并列身份并保留C补充候选"); // 留下选择依据。
    await select.getByRole("checkbox").check(); // 明确确认身份条件。
    await select.getByRole("button", { name: "保存主候选版本" }).click(); // 保存实际研究内独立版本。
    await select.getByText("待复核", { exact: true }).waitFor(); // 结果仍要总体复核。
    await select.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 补充候选表位于完整结果折叠区。
    await select.getByText("补充候选（不自动对接）", { exact: true }).click(); // 确认补充列表可查看。
    await select.getByLabel("复核人", { exact: true }).fill("合成测试复核"); // 模拟总体复核。
    await select.getByLabel("意见或处理理由").fill("主候选与覆盖结果核对完成"); // 记录结果确认。
    await select.getByLabel("决定", { exact: true }).selectOption("approved"); // 只有明确通过才供对接用。
    await select.getByRole("button", { name: "保存复核决定" }).click(); // 保存批准。
    await page.reload(); // 验证留存。
    await select.getByText("已复核通过", { exact: true }).waitFor(); // 非浏览器临时状态。
    await select.getByText("其他操作：查看图表、补充资料或重新运行", { exact: true }).click(); // 主候选修改入口按当前界面默认折叠。
    await select.getByText("填写或修改主候选", { exact: true }).click(); // 修改已有选择时必须带回原编号。
    if (await select.getByLabel(/主候选成分编号/).inputValue() !== "0\n1\n2\n3\n4") throw new Error("已保存主候选未回填"); // 不让空表单误导用户。
    await select.getByText("查看可选成分及两种排序", { exact: true }).click(); // 就地核对名称、药味和指标。
    const data = await (await page.request.get(settings.url + "/api/study?study=" + settings.study)).json(); // 核查服务端实际状态。
    for (const id of ["A04", "A05"]) if (!data.modules.find(x => x.module_id === id).available) throw new Error("交集分支被候选错误阻断"); // PPI富集可以继续。
    await card.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 重载后重新展开A03完整结果。
    await card.getByText("主候选建议与边界并列", { exact: true }).click(); // 截图显示并列池。
    await card.screenshot({ path: settings.image }); // 保存真实布局。
    await select.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 重载后重新展开完整结果。
    await select.getByText("补充候选（不自动对接）", { exact: true }).click(); // 重载后展开。
    await select.screenshot({ path: settings.selection }); // 候选及覆盖的真实布局。
    await page.setViewportSize({ width: 390, height: 844 }); // 检查窄窗口。
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)) throw new Error("A03窄屏溢出"); // 保持手机宽度可读。
    const rid = data.manifest.current.A03; // 查询绑定同次运行。
    await page.goto(settings.url + "/intersection-table?study=" + settings.study + "&run=" + rid + "&table=ranking&q=成分0"); // 验证真实明细检索。
    await page.getByText("共1条匹配，第1/1页。", { exact: true }).waitFor(); // 搜索没有改动归档。
    console.log("A03_UI_OK: 交集、SVG、双排序、并列、选择、补充、复核、重开、窄屏、分支和搜索"); // 只报告通过的检查。
} finally { // 出错也释放资源。
    await browser.close(); // 关闭测试浏览器。
}
