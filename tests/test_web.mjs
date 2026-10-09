// 本文件用真实浏览器检查工作台；只访问测试程序提供的临时研究。
import fs from "node:fs"; // 读取由测试程序传入的地址和截图位置。
import path from "node:path"; // 组合测试工具所在目录。
import { createRequire } from "node:module"; // 使用本机已有 Playwright，不安装依赖。
const require = createRequire(import.meta.url); // 为当前测试文件建立依赖读取入口。
const { chromium } = require(path.join(process.env.MODULEA_NODE_MODULES, "playwright")); // 从明确指定的测试环境加载浏览器工具。
const settings = JSON.parse(fs.readFileSync(0, "utf8")); // 从标准输入获取临时服务地址。
const browser = await chromium.launch({ channel: "msedge", headless: true }); // 使用已安装 Edge 的后台测试模式。
try { // 无论检查成功失败都释放浏览器。
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 } }); // 用普通桌面视窗检查布局。
    await page.goto(settings.url); // 打开临时工作台。
    await page.getByRole("heading", { name: "创建研究", exact: true }).waitFor(); // 确认首页有可用的登记入口。
    await page.screenshot({ path: settings.home }); // 保留首页实际渲染画面。
    await page.getByLabel("方剂名称", { exact: true }).fill("网页验收测试方"); // 使用明确标记的虚构方剂。
    await page.getByLabel("药味清单", { exact: true }).fill("测试甲"); // 不写入任何真实研究资料。
    await page.getByLabel("中文疾病名称", { exact: true }).fill("慢性阻塞性肺疾病"); // 中文名用于页面和报告显示。
    await page.getByLabel("MeSH标准词（官方英文首选词）", { exact: true }).fill("Pulmonary Disease, Chronic Obstructive"); // 提交标准词字段。
    await page.getByLabel("MeSH编号（例如D029424）", { exact: true }).fill("D029424"); // 提交与标准词对应的描述词编号。
    await page.getByLabel("研究范围", { exact: true }).fill("仅测试，不作科研结论"); // 明确测试范围。
    await page.getByLabel("登记人", { exact: true }).fill("网页自动验收"); // 不冒用用户身份。
    await page.getByRole("button", { name: "核对MeSH并保存登记" }).click(); // 验证真实创建表单。
    await page.getByRole("heading", { name: "研究与逐模块复核", exact: true }).waitFor(); // 等待保存后跳转。
    await page.getByLabel("复核人", { exact: true }).fill("网页自动验收"); // 填写测试复核身份。
    await page.getByLabel("意见或处理理由", { exact: true }).fill("只验证网页保存与恢复，不代表真实审核"); // 留存明确的测试意见。
    await page.getByLabel("决定", { exact: true }).selectOption("approved"); // 模拟明确选择通过。
    await page.getByRole("button", { name: "保存复核决定" }).click(); // 保存真正的磁盘复核记录。
    await page.getByText("已复核通过", { exact: true }).waitFor(); // 校验页面显示已保存状态。
    await page.reload(); // 模拟关闭页面后重新读取。
    await page.getByText("已复核通过", { exact: true }).waitFor(); // 确认不是只保存在浏览器内存。
    await page.screenshot({ path: settings.review }); // 保留真实复核页画面。
    await page.setViewportSize({ width: 390, height: 844 }); // 检查窄窗口是否可阅读。
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)) throw new Error("页面出现整体横向溢出"); // 宽表应在内部滚动，不挤坏页面。
    await page.setViewportSize({ width: 1280, height: 960 }); // 用桌面宽度记录中文历史的实际布局。
    await page.getByText("全部复核历史", { exact: true }).click(); // 展开中文历史，而不是只看原始字段。
    const reviewHistory = page.getByText("全部复核历史", { exact: true }).locator(".."); // 限定在复核历史区域。
    await reviewHistory.getByRole("columnheader", { name: "复核人", exact: true }).waitFor(); // 必须存在中文列标题。
    await reviewHistory.getByRole("cell", { name: "网页自动验收", exact: true }).waitFor(); // 历史中的真实复核人可直接阅读。
    await page.getByText("全部运行版本索引", { exact: true }).click(); // 展开中文运行版本表。
    await page.getByText("全部运行版本索引", { exact: true }).locator("..").getByRole("columnheader", { name: "版本用途", exact: true }).waitFor(); // 版本用途不能只显示散列字段。
    await reviewHistory.screenshot({ path: settings.review }); // 截图保留中文复核历史，原始字段仍默认收起。
    await page.getByText("研究管理", { exact: true }).click(); // 打开研究管理入口。
    await page.getByLabel("管理人", { exact: true }).fill("网页回收站测试"); // 明确管理操作身份。
    await page.getByLabel("管理操作原因", { exact: true }).fill("临时测试研究"); // 原因留存。
    await page.getByLabel("确认移入回收站当前研究", { exact: true }).check(); // 用户必须明确勾选。
    await page.getByRole("button", { name: "移入回收站", exact: true }).click(); // 仅改变临时研究状态。
    await page.getByRole("heading", { name: "回收站", exact: true }).waitFor(); // 移入后进入回收站。
    await page.getByRole("link", { name: "网页验收测试方 · 慢性阻塞性肺疾病", exact: true }).click(); // 回收站研究仍能查看。
    if (await page.getByRole("button", { name: "保存复核决定", exact: true }).count()) throw new Error("回收站不应显示复核写入按钮"); // 必须只读。
    await page.getByText("研究管理", { exact: true }).click(); // 打开恢复入口。
    await page.getByLabel("管理人", { exact: true }).fill("网页回收站测试"); // 恢复也必须记录管理人。
    await page.getByLabel("管理操作原因", { exact: true }).fill("验证恢复"); // 记录恢复原因。
    await page.getByLabel("确认恢复研究当前研究", { exact: true }).check(); // 明确恢复当前研究。
    await page.getByRole("button", { name: "恢复研究", exact: true }).click(); // 不修改原来的科学数据。
    await page.getByText("已复核通过", { exact: true }).waitFor(); // 原登记审核完整保留。
    const a01 = page.locator("article").filter({ has: page.getByRole("heading", { name: "A01 · 成分与方剂靶点", exact: true }) }); // 限定A01卡片，避免与其他模块混淆。
    await a01.getByText("其他操作：查看图表、补充资料或重新运行", { exact: true }).first().click(); // 重跑入口默认折叠。
    await a01.getByLabel("A01运行或重跑原因", { exact: true }).fill("网页虚构来源验收"); // 每次运行都保存原因。
    await a01.getByRole("button", { name: "运行A01成分与靶点整理", exact: true }).click(); // 调用真实A01入口。
    await a01.getByText("待复核", { exact: true }).waitFor(); // 计算成功不得自动批准。
    await a01.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 结果明细按当前减负界面默认折叠。
    await a01.getByText("结果摘要", { exact: true }).click(); // 摘要表本身也保持折叠，按需展开核对。
    await a01.getByRole("cell", { name: "筛选后不同成分数", exact: true }).waitFor(); // 数量摘要必须中文可读。
    const sid = new URL(page.url()).searchParams.get("study"); // 从实际跳转取得临时研究身份。
    const facts = await (await page.request.get(settings.url + "/api/study?study=" + sid)).json(); // 核对已保存的事实。
    if (facts.modules[1].result.summary["不同人类基因数"] !== 1) throw new Error("A01网页结果与测试来源不符"); // 不只判断按钮是否可点。
    const combined=page.getByLabel("本次复核人",{exact:true}); // 新流程在A02已生成时使用一次复核表单。
    if(await combined.count()){ // 新版预上传研究。
        await combined.fill("A01网页验收"); // 共用复核人。
        await page.locator('textarea[name="a01_note"]').fill("虚构来源，仅验收"); // A01独立依据。
        await page.locator('select[name="a01_decision"]').selectOption("approved"); // 只批准本次已核对的A01。
        await page.locator('textarea[name="a02_note"]').fill("疾病资料尚未核对，暂存待定"); // A02不被误批准。
        await page.getByRole("button",{name:"保存A01和A02复核决定",exact:true}).click(); // 原子保存两项决定。
    } else { // 历史研究保留独立复核入口。
        await a01.getByLabel("复核人", { exact: true }).fill("A01网页验收"); // 独立保存A01的复核身份。
        await a01.getByLabel("意见或处理理由", { exact: true }).fill("虚构来源，仅验收"); // 不冒充正式科研审核。
        await a01.getByLabel("决定", { exact: true }).selectOption("approved"); // 明确选择通过。
        await a01.getByRole("button", { name: /保存复核决定/, exact: false }).first().click(); // 保存A01审核。
    }
    await a01.getByText("已复核通过", { exact: true }).waitFor(); // 对应模块状态正确。
    await page.reload(); // 检查磁盘持久化。
    await a01.getByText("已复核通过", { exact: true }).waitFor(); // 重载后原审核仍然存在。
    await a01.screenshot({ path: settings.a01 }); // 保存A01中文摘要的实际界面。
    const a02 = page.locator("article").filter({ has: page.getByRole("heading", { name: "A02 · 疾病靶点", exact: true }) }); // 限定疾病模块。
    await a02.getByText("其他操作：查看图表、补充资料或重新运行", { exact: true }).first().click(); // 先展开模块次要操作。
    await a02.getByText("资料获取与更新", { exact: true }).first().click(); // 主页面次要操作默认收起。
    await a02.getByText("GeneCards：上传或替换资料", { exact: true }).click(); // 展开真实上传入口。
    const upload = a02.locator('form[action="/disease-upload"]').filter({ has: page.getByRole("button", { name: "上传并整理GeneCards", exact: true }) }); // 避免与其他表单字段混淆。
    if (await upload.locator('input[name="database"]').inputValue() !== "GeneCards") throw new Error("专属入口数据库错误"); // 不要求用户重复选择库。
    for (const db of ["OMIM", "TTD", "PharmGKB"]) if (await a02.getByText(db + "：上传或替换资料", { exact: true }).count() !== 1) throw new Error("缺少新版人工资料入口"); // 四个人工来源均可补充。
    await upload.getByLabel("GeneCards文件格式", { exact: true }).selectOption("detailed_txt"); // 使用严格详细TXT格式。
    const fixture = "raw_symbol\traw_id\traw_score\tscore_name\tdisease_term\tdisease_id\nTEST1\tID1\t0\ttest\ttest disease\tTEST_1\nTEST2\tID2\t0.8\ttest\tother disease\tTEST_2\n"; // 虚构资料，不作研究结论。
    await upload.getByLabel("GeneCards资料文件", { exact: true }).setInputFiles({ name: "candidate_test.tsv", mimeType: "text/tab-separated-values", buffer: Buffer.from(fixture) }); // 通过浏览器实际上传。
    await upload.getByLabel("GeneCards 实际检索词或疾病名称", { exact: true }).fill("网页验收测试疾病"); // 来源绑定测试研究。
    await upload.getByLabel("GeneCards 资料下载日期", { exact: true }).fill("2026-09-10"); // 明确来源日期。
    await upload.getByLabel("GeneCards 数据库版本（未知填未知）", { exact: true }).fill("虚构验收"); // 不冒称真实版本。
    await upload.getByLabel("确认这份GeneCards资料用于当前研究候选核查", { exact: true }).check(); // 明确提交。
    await upload.getByRole("button", { name: "上传并整理GeneCards", exact: true }).click(); // 创建实际A02运行。
    await a02.getByText("待复核", { exact: true }).waitFor(); // 候选发布为待核验。
    if (await a02.locator('select[name="decision"] option[value="approved"]').count()) throw new Error("候选不应显示允许下游使用"); // 网页不提供提前批准。
    const diseaseFacts = await (await page.request.get(settings.url + "/api/study?study=" + sid)).json(); // 校验磁盘实际结果。
    if (diseaseFacts.modules[2].result.summary["候选记录数"] !== 2) throw new Error("上传候选数量不一致"); // 原始行不丢失。
    await a02.getByText("复核资料与完整结果（需要时展开）", { exact: true }).click(); // 疾病结果链接按当前减负界面默认折叠。
    await a02.getByRole("link", { name: /疾病条目范围复核/ }).click(); // 进入真实条目复核页。
    await page.getByRole("heading", { name: "疾病条目范围复核", exact: true }).waitFor(); // 页面必须显示中文。
    await page.getByLabel("未单独调整条目的统一处理", { exact: true }).selectOption("outside"); // 批量排除并保留一个例外。
    const wanted = diseaseFacts.modules[2].result.tables.scope_groups.find(row => row.disease_id === "TEST_1"); // 按实际分组编号选择例外。
    await page.getByLabel("条目" + wanted.scope_id + "本次决定", { exact: true }).selectOption("direct"); // 特定本病条目优先于统一处理。
    await page.getByLabel("本批复核人", { exact: true }).fill("网页范围测试"); // 留存操作者。
    await page.getByLabel("本批范围复核依据", { exact: true }).fill("虚构条目批次，仅测试"); // 同批依据随条目保存。
    await page.getByLabel("确认提交整张表的统一处理及例外决定", { exact: true }).check(); // 明确全表提交。
    await page.getByRole("button", { name: "一次保存全部范围决定", exact: true }).click(); // 一个批次仅形成一个版本。
    await a02.getByText("待复核", { exact: true }).waitFor(); // 范围意见不替代正式筛选批准。
    await page.getByLabel("本次复核人", { exact: true }).fill("A02暂存测试"); // 新流程一次复核表单共用复核人。
    await page.locator('textarea[name="a02_note"]').fill("正式评分规则未定，暂存"); // 明确暂存A02。
    await page.getByRole("button", { name: "保存A01和A02复核决定", exact: true }).click(); // A01保留通过，A02保存暂存。
    await page.reload(); // 模拟关闭重开后的重新读取。
    await a02.getByText("暂存待定", { exact: true }).first().waitFor(); // 保存状态持续存在。
    const finalFacts = await (await page.request.get(settings.url + "/api/study?study=" + sid)).json(); // 对照实际新版本。
    if (finalFacts.modules[2].result.tables.scope_history.length !== 2 || finalFacts.modules[3].available) throw new Error("范围留痕或A03门控不正确"); // 不因A01通过而绕开A02门控。
    if (finalFacts.modules[2].result.tables.scope_groups.find(row => row.disease_id === "TEST_2").scope !== "outside") throw new Error("批量统一处理未生效"); // 验证统一决定。
    if (finalFacts.modules[2].result.tables.scope_groups.find(row => row.disease_id === "TEST_1").scope !== "direct") throw new Error("例外决定未生效"); // 验证例外优先。
    await a02.screenshot({ path: settings.a02 }); // 截图仅含虚构验收资料。
    console.log("UI_OK: A02 upload, scope review, history, reload, A03 blocked"); // 报告真实完成的检查。
    console.log("UI_OK: A01 run, Chinese results, review, reload"); // 记录实际科学入口验收范围。
    console.log("UI_OK: Chinese history, recycle, read-only, restore"); // 记录真实通过的管理验收。
    console.log("UI_OK: create, review, reload, narrow viewport"); // 只输出本次实际通过的检查项。
} finally { // 清理本次浏览器测试资源。
    await browser.close(); // 不留下浏览器进程。
} // 测试结束。
