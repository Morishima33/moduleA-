# tasks/ — 后台任务

- 任务在子进程中执行：`python -m modulea task-run <task_id>`，解释器取 `config/local.toml` 的 `science_python`（默认与工作台相同）。
- 状态：`queued → running → succeeded | failed | cancelled | interrupted`。索引在 `<runtime_dir>/tasks.sqlite`，日志在 `<runtime_dir>/task_logs/`；二者都是运行时信息，可删除，研究事实以 `studies/` 为准。

## 规则

1. 同一研究同一时刻只有一个写入型任务；重复提交返回已有任务（`submit` 内部去重）。
2. 取消会结束子进程；被取消或中断的运行不可复用，原文件全部保留，内核会把它显示为“未完整提交”。
3. 服务重启时，进程已不存在的运行中任务标记为 interrupted，**不自动重跑**，由用户点“重试”（重试会建立新运行，不续写残缺产物）。
4. 任务只能通过科学内核的生产入口产生结果（例如 `auto_continue.continue_after_review`），不得绕过 `Workflow.begin/finish` 直接写文件；任务从不代签复核。
5. 失败要写明原因（`error_zh`），缺科学依赖时说明缺哪个包、如何配置；联网失败与“0 条结果”严格区分。
6. 新增任务类型：在 `manager.KINDS` 登记中文名，在 `worker.HANDLERS` 登记执行函数，并在 `api/AGENTS.md` 说明触发方式。
