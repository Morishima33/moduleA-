// A06正式结果真实浏览器检查；只读查看，不替用户提交复核。
import fs from 'node:fs'; // 接收明确的服务、研究和截图目录。
import path from 'node:path'; // 定位既有浏览器依赖。
import {createRequire} from 'node:module'; // 加载Playwright。
const require = createRequire(import.meta.url); // 创建模块加载器。
const {chromium} = require(path.join(process.env.MODULEA_NODE_MODULES,'playwright')); // 使用已安装浏览器工具。
const settings = JSON.parse(fs.readFileSync(0,'utf8')); // 不从目录或时间猜研究。
const browser = await chromium.launch({channel:'msedge',headless:true}); // 后台验证而不打扰用户。
try { // 无论成功失败都关闭浏览器。
    const page = await browser.newPage({viewport:{width:1280,height:1000}}); // 固定可复核布局。
    const response = await page.goto(settings.url+'/docking-preview?study='+settings.study); // 打开本研究对接预览。
    if(response.status()!==200) throw new Error('正式对接预览访问失败'); // 不接受错误页当成功。
    await page.getByText('正式对接已完成：下一步集中核验结果矩阵',{exact:true}).waitFor(); // 当前任务必须清楚置顶。
    await page.getByRole('heading',{name:'本轮必须核验：10组正式分子对接',exact:true}).waitFor(); // 复核重点不能藏在长表中。
    const matrix = page.getByRole('heading',{name:'本轮必须核验：10组正式分子对接',exact:true}).locator('xpath=following-sibling::p[1]/following-sibling::div[1]//table'); // 锁定五行矩阵。
    if(await matrix.locator('tr').count()!==6) throw new Error('结合能矩阵不是五个成分'); // 一行表头加五行成分。
    await matrix.getByText('-10.934',{exact:true}).waitFor(); // 检查实际最低显示值。
    await matrix.getByText('-8.372',{exact:true}).waitFor(); // 检查另一受体实际评分。
    if(await matrix.getByText('未运行',{exact:true}).count()!==5) throw new Error('HSP90AA1暂停范围显示不完整'); // 五个成分均明确未运行。
    await page.getByText('本轮没有设置结合能通过阈值；数值只作为候选排序和后续研究依据。',{exact:false}).waitFor(); // 页面不得把评分解释成实验效应。
    if(await page.getByText('展开15组计划明细',{exact:true}).count()) throw new Error('页面仍显示过时的完成0组计划'); // 正式完成后移除旧阶段提示。
    if(await page.locator('form').count()) throw new Error('只读预览不应存在提交表单'); // 复核仍在统一A06卡片完成。
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)) throw new Error('页面横向溢出'); // 长表必须在内部滚动。
    await page.screenshot({path:settings.root+'/tests/web_a06_formal_review_top_20260923.png',fullPage:true}); // 保存本阶段独立验收截图。
    await page.goto(settings.url+'/study?study='+settings.study); // 检查统一研究卡片。
    await page.getByRole('link',{name:'查看10组正式对接结果',exact:true}).waitFor(); // A06_PREP入口反映当前阶段。
    await page.getByRole('heading',{name:'A06 · 分子对接结果',exact:true}).waitFor(); // 正式模块仍在统一工作台。
    await page.getByText('beta-sitosterol',{exact:true}).last().waitFor(); // A06重点区直接展示矩阵。
    console.log('A06十组正式结果、五组暂停边界、矩阵重点区和统一待复核状态检查通过'); // 只报告实际检查内容。
} finally { await browser.close(); } // 不遗留浏览器进程。