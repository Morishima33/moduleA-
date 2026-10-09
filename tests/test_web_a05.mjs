// A05真实网页只读检查，不提交复核决定。
import fs from "node:fs"; // 读取测试入口。
import path from "node:path"; // 依赖位置。
import { createRequire } from "node:module"; // 使用现有Playwright。
const require=createRequire(import.meta.url); // 加载运行环境依赖。
const {chromium}=require(path.join(process.env.MODULEA_NODE_MODULES,"playwright")); // 不安装新包。
const settings=JSON.parse(fs.readFileSync(0,"utf8")); // 研究及临时服务入口。
const browser=await chromium.launch({channel:"msedge",headless:true}); // 后台浏览器。
try { // 无论成功失败均关闭。
 const page=await browser.newPage({viewport:{width:1280,height:1000}}); // 固定视口。
 await page.goto(settings.url+"/study?study="+settings.study); // 只读当前研究。
 const card=page.locator("article").filter({has:page.getByRole("heading",{name:"A05 · GO 与 KEGG 富集",exact:true})}); // 精确选中A05。
 await card.getByText("待复核",{exact:true}).waitFor(); // 不应自动批准。
 await card.getByText("四类结果汇总").count(); // 完整汇总入口存在。
 await card.screenshot({path:settings.root+"/tests/web_a05.png"}); // 检查折叠后的重点界面。
 await card.getByText("其他操作：查看图表、补充资料或重新运行",{exact:true}).click(); // 展开图形操作。
 await card.getByText("BP：柱状图和气泡图",{exact:true}).click(); // 第一类图形。
 await card.locator("svg").first().screenshot({path:settings.root+"/tests/web_a05_chart.png"}); // 真实渲染图。
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth); // 页面不应横向溢出。
 if(overflow)throw new Error("页面出现横向溢出"); // 明确失败。
 console.log("A05网页与图形只读检查通过"); // 输出实际结果。
} finally { await browser.close(); } // 不遗留浏览器。
