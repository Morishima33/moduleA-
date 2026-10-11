# A05 GO与KEGG富集代码索引（2026-10-11）

旧版当前四个核心文件已在正式重构仓库，SHA-256逐一与原项目一致。本目录按模块集中提供入口及用途；执行代码保留原位置，不复制、不移动冻结实现。指纹见[来源与版本索引](来源与版本索引.json)。本轮为代码准备阶段，真实富集暂不运行，等待用户微调。

| 正式代码位置 | 用途与后续修改定位 |
|---|---|
| [enrichment.R](../../enrichment.R) | 固定R包版本；导出GO注释；执行ORA、分组BH校正、显著筛选及展示条目选择。 |
| [enrichment_flow.py](../../enrichment_flow.py) | 获取并固定GO/KEGG来源；HGNC→Entrez映射；绑定A03、归档、版本检查及独立复算。 |
| [enrichment_plot.py](../../enrichment_plot.py) | 从归档展示表生成柱状图和气泡图：Count柱长、GeneRatio横轴、Count气泡面积、校正P值色标。 |
| [enrichment_ui.py](../../enrichment_ui.py) | 原网页运行控件、四类图及全量结果分页；仅作为兼容入口，后续操作仍优先接入重构页面。 |
| [新网页展示适配](../../modulea/presenters/network.py) | present_a05：四类数量、输入与背景、前列条目、身份问题及空结果说明。 |
| [重构网页图表](../../../web/src/components/special/EnrichmentTop.tsx)／[模块页装配](../../../web/src/components/ModulePage.tsx) | 已有模块专属展示装配；A05页面只读取当前绑定运行，不伪造新结果。 |
| [后台内核](../../modulea/core/kernel.py) | full_workflow登记A05校验器，接口进程只读；科学计算使用后台解释器。 |
| [自动接续](../../auto_continue.py)／[后台任务](../../modulea/tasks/worker.py) | 已有A03→A05接续路径，本轮不调用，不自动执行A06。 |
| [专业报告适配](../a07/README.md) | A05保持在A04后、后续对接前；统计、图件、描述应绑定同一次A05，不借用旧下游。 |

## 已有科学口径，供微调确认

输入为当前已批准A03的完整intersection_targets，A04节点筛选及本次PPI有限暂不采用不改变A05输入。A04与A05独立，A05不要求使用PPI第一轮或第二轮候选。

A05.1采用人类注释、clusterProfiler 4.14.6的ORA；GO的BP、CC、MF分别BH校正，KEGG单独BH校正；基因集背景大小10—500，主显著性严格p.adjust < 0.05。每类使用自己的实际可分析注释背景和有效输入，缺注释与身份不明分别留存。GO每类显示前10，KEGG显示前20，排序p.adjust后ID；完整检验、显著、展示和未检验名单均归档。无显著结果不降低阈值补项，qvalue只保留原值，不代替主筛选。

以上是现有代码口径，不代表已替用户确认下一轮微调。涉及统计方法、阈值、输入或展示改动，先按用户意见确认并新增版本，旧A05.1保留供历史复算。

## 后续调用前待适配

旧r_call以运行数据根的environments为工作目录，使用../../src/enrichment.R，重构代码与数据分开后该脚本路径不存在。微调时需明确定位本仓库R脚本，不复制原代码至数据目录；Rscript本机路径保持现状，本轮未启动R。新数据快照暂无A05_sources.json，不借用原项目来源索引或结果补齐。

网页已有历史A05，但其父A03已不是当前版本，当前标记为已失效。保留原件，等待修改确认及明确计算指令后再生成新A05，不能将旧图或旧统计称为本次新结果。
