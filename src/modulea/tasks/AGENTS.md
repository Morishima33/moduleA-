# tasks/ — 后台任务

- 任务在子进程中执行：`python -m modulea task-run <task_id>`，解释器取 `config/local.toml` 的 `science_python`（默认与工作台相同）。
- 状态：`queued → running → succeeded | failed | cancelled | interrupted`。索引在 `<runtime_dir>/tasks.sqlite`，日志在 `<runtime_dir>/task_logs/`；二者都是运行时信息，可删除，研究事实以 `studies/` 为准。

## 规则

1. 同一研究同一时刻只有一个写入型任务；重复提交返回已有任务（`submit` 内部去重）。
2. 取消会结束子进程；被取消或中断的运行不可复用，原文件全部保留，内核会把它显示为“未完整提交”。
3. 服务重启、任务查询或新提交时，将进程已不存在的 running，以及超过 30 秒启动宽限且无存活进程的 queued，标记为 interrupted，**不自动重跑**，由用户点“重试”。启动失败立即记为 failed 并记录原因，不能留下永久排队任务。
   Windows 进程存活通过只读句柄查询，禁止使用 `os.kill(pid, 0)`。子进程原子认领 queued 并登记自身 PID，取消后的任务不能认领；完成回写不能覆盖取消决定。
   SQLite 连接上下文必须提交/回滚后立即关闭，日志文件在启动成功与失败时均关闭。
4. 任务只能通过科学内核的生产入口产生结果（例如 `auto_continue.continue_after_review`），不得绕过 `Workflow.begin/finish` 直接写文件；任务从不代签复核。
5. 失败要写明原因（`error_zh`），缺科学依赖时说明缺哪个包、如何配置；联网失败与“0 条结果”严格区分。
6. 新增任务类型：在 `manager.KINDS` 登记中文名，在 `worker.HANDLERS` 登记执行函数，并在 `api/AGENTS.md` 说明触发方式。

## 分库资料任务

`source_upload`解析A01来源包或调用既有A02候选入口，`a01_sources`显式整理完整三库。任务payload存私有SQLite，不进入公开任务响应；原始字节暂存于runtime/upload_queue并校验指纹，失败/取消后保留供人工重试。重试保留原版本绑定；版本过期须重新上传。所有写入仍使用Workflow和研究锁，不代签。

A04专用任务a04_ppi完成后停在A04。助手修复图件时可通过私有任务payload提供reuse_source_run，必须等于expected_a04，且原run同研究、同A03；使用指纹核验的原始STRING包归档新A04版本，不覆盖旧文件。公开页面按钮默认重新获取来源，不提供该私有参数。图元数据采用degree_network单行平面表，与结果files中的SVG/PNG指纹绑定，遵守既有表格契约。

## A05独立根目录运行接入

continue后台使用science_modules/a05/flow.run_enrichment，full_workflow登记同适配层的validator。自动接续旧编排仍冻结，仅在本科学子进程绑定新PPI及A05入口；当前双分支对接来源未定时只可按原逻辑生成缺失或失效的A05，不进入A06。A05成功归档后进度1/1且结果待复核，R或来源失败保持失败，不能解释为无显著。

## A05第二版展示及人工确认

现行continue使用science_modules/a05/display_flow.run_enrichment：冻结A05.1统计完成后生成A05.display.2待确认预览。新增a05_display任务接收明确清单或版式确认，归档用户决定和新展示，失败保留记录、重试复用，统计不重算，绝不自动批准A05或启动A06。full_workflow登记display_flow.validator，旧版委托flow.validator。公开接口绑定研究、A03、A05及最新决定，历史/回收站/过期/忙碌状态拒绝。

## 2026-10-11 A05第三版展示入口

现行continue及a05_display使用science_modules/a05/compact_flow，full_workflow登记其validator并委托旧版历史核验。用户要求的版式修订通过revise_layout复用原统计、译名和排除范围，生成A05.display.3；新版式待用户确认，不运行R、不代签A05或启动A06。未新增公开任务类型或后台监听。

## A06候选分组
新增a06_candidates：只经DockingWorkflow.generate_candidates读取当前已批准A04归档并追加分组，不重算PPI、不下载结构、不启动Vina、不代签。continue仍停在A06来源/结构准备关口，不能将分组生成视为结构质控通过。

已有有效两梯队归档时，continue准确提示“结构方案待微调与核查”，不再称候选来源未确定；A05独立分支仍保留。此入口不会调用旧第一轮准备、不会启动真实对接。
