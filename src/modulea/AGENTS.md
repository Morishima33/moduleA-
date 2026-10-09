# src/modulea/ — 新架构外壳

## 分层与依赖方向

```
api/        本机 JSON 接口与静态前端托管          → 依赖 core、presenters、tasks
presenters/ 各模块展示适配（只读归档结果）         → 依赖 core
tasks/      后台任务登记与子进程执行               → 依赖 core（子进程里才导入科学依赖）
core/       内核桥接、模块登记、状态映射           → 依赖 src/ 科学内核（workflow、storage、contracts）
config.py   本机配置（路径只在这里出现）
devtools/   开发辅助（演示数据），不参与正式流程
static/     前端构建产物（由 web/ 构建生成，不手改）
```

只允许上层依赖下层；presenters 之间不互相导入；任何文件都不得导入 `web.py` 或 `*_ui.py`。

## 规则

1. **不做科学计算**：外壳只读取、翻译、展示和调度。科学结果只能由 `src/` 科学内核在后台任务中产生。
2. **接口进程只用标准库**：`api/`、`core/`、`presenters/` 不得在模块顶层导入第三方库或科学依赖。需要科学依赖的代码放在 `tasks/worker.py` 的函数内部，或通过 `core.kernel.full_workflow()` 获取。
3. **状态只来自 `Workflow.view()`**：`core/status.py` 只做状态码翻译。新增状态码时同时更新 `api/AGENTS.md` 和前端。
4. **不写死病例**：不出现研究编号、运行编号、病名、固定受体名单；读不到的字段直接省略，不编造。
5. **写入只经过 Workflow 的公开方法**（`review`、`review_a01_a02`、`set_trashed` 等），并在写锁内完成；不得直接改 `studies/` 下的文件。
6. 注释：每个文件开头说明用途，每个函数或代码块上方用中文说明作用；面向用户的文字用中文。

## 常用命令

```bash
PYTHONPATH=src python3 -m modulea serve                 # 启动工作台（默认端口 8765，start_v2 脚本用 8780）
PYTHONPATH=src python3 -m modulea doctor                # 检查数据目录、归档核验和科学依赖
PYTHONPATH=src python3 -m modulea.devtools.demo_data <目录> [--source <数据根> --study <研究编号>]   # 生成演示数据
PYTHONPATH=src python3 -m unittest discover -s tests/modulea                                       # 外壳测试
```

## 扩展方式

| 要做的事 | 改哪里 |
|---|---|
| 新增模块 | 先在 `src/contracts.py` 的 `MODULES` 登记依赖（须用户批准），再在 `core/modules.py` 的 `PRESENTATION` 加展示信息，在 `presenters/` 加展示函数 |
| 模块页多显示一个数字或图 | 对应的 `presenters/*.py`；新字段写进 `api/AGENTS.md` 的 special 表 |
| 新增后台任务类型 | `tasks/manager.py` 的 `KINDS` 与 `tasks/worker.py` 的 `HANDLERS` |
| 新增接口 | `api/server.py` 的路由表 + `api/AGENTS.md` |
| 接入模块操作（运行、上传、范围决定等） | 见 `api/AGENTS.md` 第 7 节：统一为 `POST .../actions/{action}`，执行放在后台任务 |
