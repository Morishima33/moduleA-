# Module A 研究工作台前端（web/）

本目录是 Module A 新工作台的网页前端源码（Vite + React 18 + TypeScript + Ant Design 5）。
它只调用本机 JSON 接口 `/api/v1`（契约见 `src/modulea/api/AGENTS.md`），不计算任何科学结果。
构建产物输出到 `src/modulea/static/`，由 Python 服务同源托管；用户日常使用不需要 Node.js。

## 能做什么

- 首页：研究卡片（用途标签、方剂药味与 MeSH、按模块的进度分段条、“n / 10 已通过”、下一步、待办数、继续）、全局待办、回收站（列表与恢复）。
- 研究工作页：用途横幅、下一步提示、左侧分组导航、模块页、右侧复核栏；窄屏时导航变为抽屉、复核栏堆叠在“重点核对”之后。
- 模块页：本轮你只需核对这些、需要知悉、关键数字、数量变化链、模块专属图（A03 韦恩图、A04 前 10 Degree、A05 富集前列、A06 结合能热图、A07 结论/线索/限制/报告下载），以及“结果明细 / 参数与版本 / 来源与追溯”三个页签（完整明细分页搜索、归档文件下载、运行历史与历史版本只读查看）。
- 复核：单模块复核（仅保存 / 保存并继续）、A01+A02 一起提交、版本冲突自动刷新。
- 后台任务面板：列表、增量日志、取消、重试；有活动任务时每 3 秒轮询，任务结束后自动刷新当前研究。
- 研究管理：推进到下一人工关口、移入回收站、从回收站恢复（均须确认，管理操作带 `expected_action_id`）。

## 开发

需要 Node.js 22 与 npm 10。

```bash
cd web
npm install            # 安装依赖（只需一次）
# 另开终端启动接口服务，并允许前端开发地址跨源：
cd ../src && python3 -m modulea --data-root <演示数据目录> --runtime-dir <演示数据目录>/.runtime \
    serve --port 8799 --no-browser --allow-origin http://localhost:5173
# 回到 web/ 启动开发服务器（http://localhost:5173）：
npm run dev
```

开发时接口地址默认为 `http://127.0.0.1:8799`，可用环境变量覆盖：`VITE_API_BASE=http://127.0.0.1:8800 npm run dev`。
演示数据可用 `python3 -m modulea.devtools.demo_data <新目录> --source <真实项目目录> --study <研究编号>` 生成（只读源数据）。

## 构建

```bash
cd web
npm run build          # 先做 TypeScript 检查，再输出到 ../src/modulea/static/（会先清空该目录）
```

构建后直接启动服务即可使用（默认托管 static）：

```bash
cd src && python3 -m modulea --data-root <数据目录> --runtime-dir <数据目录>/.runtime serve --port 8797 --no-browser
# 浏览器打开 http://127.0.0.1:8797/
```

`npm run typecheck` 只做类型检查不输出产物。

## 目录结构

```
web/
├── index.html                 入口页面（只加载同源脚本）
├── public/favicon.svg         图标
├── vite.config.ts             构建配置（base './'，输出到 ../src/modulea/static）
├── tsconfig.json
└── src/
    ├── main.tsx               挂载、Ant Design 主题与中文语言包
    ├── App.tsx                顶栏、路由、全局待办与任务面板、活动任务轮询
    ├── styles.css             全局样式与三栏布局（系统中文字体，不加载外部字体）
    ├── api/
    │   ├── types.ts           接口数据类型（与契约一一对应）
    │   └── client.ts          唯一的请求出口：令牌、错误码、各端点封装、下载地址
    ├── lib/
    │   ├── appContext.ts      全局上下文（会话、刷新信号、任务面板）
    │   ├── route.ts           哈希路由 #/studies/<研究>/<模块>?run_id=
    │   ├── theme.ts           状态配色、热图色带
    │   └── format.ts          时间、大小、数值、p 值等显示格式
    ├── pages/
    │   ├── HomePage.tsx       首页
    │   └── StudyPage.tsx      研究工作页（三栏布局、研究管理）
    └── components/
        ├── common.tsx         状态胶囊、进度分段条、归档未就绪提示等
        ├── ModulePage.tsx     模块页主体
        ├── ModuleSections.tsx 重点核对、需要知悉、关键数字、数量变化、下游影响
        ├── DataTabs.tsx       结果明细 / 参数与版本 / 来源与追溯
        ├── ReviewPanel.tsx    复核栏
        ├── DecisionPicker.tsx 三选一决定
        ├── BatchReviewModal.tsx  A01+A02 一起提交
        ├── TaskDrawer.tsx     后台任务面板
        ├── InboxDrawer.tsx    全局待办
        ├── ManageStudyModal.tsx  移入回收站 / 恢复
        └── special/           模块专属图：Venn、PpiTop、EnrichmentTop、Heatmap、ReportSummary
```

`node_modules/` 与 `dist/` 不进入版本库；`src/modulea/static/` 是正式构建产物，需要随代码一起提交。
