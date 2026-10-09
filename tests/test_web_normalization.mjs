// 浏览器验收仅使用调用方提供的临时研究。
import fs from "node:fs"; // 读取配置。
import path from "node:path"; // 定位已有工具。
import { createRequire } from "node:module"; // 引用浏览器工具。
const require = createRequire(import.meta.url); // 当前模块引用。
const { chromium } = require(path.join(process.env.MODULEA_NODE_MODULES,"playwright")); // 不安装运行依赖。
const settings = JSON.parse(fs.readFileSync(0,"utf8")); // 临时研究参数。
const browser = await chromium.launch({channel:"msedge",headless:true}); // 后台浏览器。
try { // 始终释放资源。
 const page = await browser.newPage(); // 独立页面。
 await page.goto(settings.url+"/study?study="+settings.study); // 从研究卡片进入。
 await page.getByRole("link",{name:"进入结果汇总与交接准备",exact:true}).click(); // 验证用户实际入口。
 await page.getByRole("heading",{name:"A02结果汇总与交接准备",exact:true}).waitFor(); // 不只是后台接口成功。
 await page.getByLabel("本次核验人",{exact:true}).fill("隔离网页测试"); // 不冒用用户身份。
 await page.getByLabel("范围及身份例外处理依据",{exact:true}).fill("虚构来源，仅测试接受列出的范围及身份例外"); // 留存依据。
 await page.getByLabel("我确认上述采用及不采用范围，仅用于本次流程测试",{exact:true}).check(); // 明确范围草案。
 await page.getByLabel("我已核查未进入主集合的条目，接受本次流程测试暂不采用（保留原始资料和查实依据）",{exact:true}).check(); // 明确例外。
 await page.getByRole("button",{name:"生成标准化结果，返回研究页复核",exact:true}).click(); // 发布待复核版本。
 const batch=page.getByLabel("本次复核人",{exact:true}); // 新流程使用一次复核，历史合同测试保留独立入口。
 if(await batch.count()){ // 新版预上传研究。
  await batch.fill("隔离网页测试"); // 两项共用复核人。
  for (const prefix of ["A01", "A02"]) { // 两侧意见和决定仍各自保存。
   await page.getByLabel(prefix+"意见",{exact:true}).fill("测试汇总与例外已核对"); // 记录独立依据。
   await page.getByLabel(prefix+"决定",{exact:true}).selectOption("approved"); // 用户能分别选择通过。
  } // 两侧表单填写结束。
  await page.getByRole("button",{name:"保存A01和A02复核决定",exact:true}).click(); // 一次原子提交两项。
 } else { // 历史研究继续验证原独立入口。
  for (const prefix of ["A01", "A02"]) { // 必须两侧实际复核。
   const card=page.locator("article").filter({has:page.getByRole("heading",{name:new RegExp("^"+prefix+" ·")})}); // 对应模块。
   await card.getByLabel("复核人",{exact:true}).fill("隔离网页测试"); // 测试身份。
   await card.getByLabel("意见或处理理由",{exact:true}).fill("测试汇总与例外已核对"); // 记录批准依据。
   await card.getByLabel("决定",{exact:true}).selectOption("approved"); // 用户能找到通过选项。
   await card.getByRole("button",{name:/保存复核决定/,exact:false}).first().click(); // 保存并等待页面刷新。
  } // 历史两侧复核结束。
 }
 const a03 = page.locator("article").filter({has:page.getByRole("heading",{name:"A03 · 交集与成分候选",exact:true})}); // 下游模块。
 await a03.getByLabel("A03运行原因").fill("验证标准化交接"); // 用户实际操作。
 await a03.getByRole("button",{name:"运行A03交集与排序",exact:true}).click(); // 不仅查看按钮。
 await a03.getByText("其他操作：查看图表、补充资料或重新运行",{exact:true}).click(); // 韦恩图位于当前减负界面的操作折叠区。
 await a03.locator("svg").waitFor(); // 下游图表实际生成。
 const facts=await (await page.request.get(settings.url+"/api/study?study="+settings.study)).json(); // 核查磁盘结果。
 const result=facts.modules.find(x=>x.module_id==="A03").result; // 明确模块。
 if(result.summary["交集靶点数"]!==1||result.summary.analysis_purpose!=="workflow_test")throw new Error("交集或用途不一致"); // 手算与测试标签一致。
 console.log("NORMALIZATION_UI_OK"); // 只在全部通过后报告。
} finally { // 清理后台浏览器。
 await browser.close(); // 不遗留进程。
} // 测试结束。
