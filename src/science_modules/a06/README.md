# A06代码复用与候选入口
科学实现仍在src/docking_*.py，24个文件按来源与版本索引逐项核对，不移动、不重写算法，保留历史与复用键。
- candidates.py：两梯队规则A06.candidate_groups.1，从已批准第二轮名单生成。
- modulea/core/docking_workflow.py：研究绑定、版本留存与失效保护。
- modulea/tasks/worker.py：a06_candidates，只生成名单。
- docking_generic_prep.py、docking_automation.py：旧版第一轮受体选择及人工方案，保留历史，不能直接用于新版两梯队。
- docking_automation_compute.py：已有配体/受体准备、Vina、质控与动态结果引擎。
- docking_formal.py、docking_contract.py、docking_result_reuse.py：结构质控、动态矩阵及指纹复用。
- docking_dynamic_heatmap.py、docking_grouped_heatmap.py、docking_task_package.py：图表与出图任务包。

新版名单接入核查页。本轮不调用旧prepare_screen或自动发布批准入口；新版结构方案与执行契约需在后续微调时接入，不能用旧round1别名伪装。
A/B是项目候选依据，不改变RMSD、结构质量、失败NA、Top-1或审批规则。失效A03_SELECT需重新选择成分；结构和盒参数另行确认。
代码根与数据根分离；实际工具路径在后续明确调用时适配。本轮验证名单归档、接口、网页及现有纯契约，不声称Vina已运行。
