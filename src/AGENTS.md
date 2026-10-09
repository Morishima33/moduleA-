# src/ — 科学内核（扁平模块）

这里的 `*.py` 和 `enrichment.R` 是**已验收的科学内核**：已批准研究的全部结果都由它们产生。新架构外壳 `src/modulea/` 调用它们，但不复制、不改写其中的科学规则。

## 1 冻结规则

- **语义冻结**：任何已被已批准运行使用的规则版本，其行为不得改变。要改变行为，新增版本号（例如 `HGNC.resolve.4`），旧版本代码保留，供历史运行复算。
- **允许的改动**：修正明确的缺陷（必须附测试，并证明已批准运行的复算结果不变）；把病例专用逻辑抽离为数据（见第 3 节）；为新架构提供只读接口。
- **不允许**：批量重排格式、改名或移动文件（会破坏 `code_version` 与历史比对）、新增“默认授权”、写死研究编号。
- 状态与存储内核（`workflow.py`、`storage.py`、`contracts.py`）是全项目唯一的状态来源。改动它们前必须先与用户确认，并让新旧状态在全部研究上逐项一致。
- 注释风格沿用文件原样；新增函数按根目录 AGENTS.md 第 7 节写块级中文说明。

## 2 模块分组

| 分组 | 文件 | 说明 |
|---|---|---|
| 状态与存储 | `workflow.py` `storage.py` `contracts.py` | 研究、运行、复核、失效判断；原子写入、写锁、指纹 |
| 自动接续 | `auto_continue.py` | 复核后推进到下一人工关口；新架构通过后台任务调用它 |
| A00 登记 | `mesh_identity.py` `intake_sources.py` | MeSH 官方核对；A00 预上传暂存 |
| A01 方剂侧 | `components.py` | TCMSP 快照，OB≥30、DL≥0.18 |
| A02 疾病侧 | `disease.py` `disease_io.py` `a02_auto_prepare.py` `otp_search.py` `ttd_source.py` `pharmgkb_source.py` | 来源获取、上传解析、范围复核 |
| 身份标准化 | `hgnc.py` `identity_sources.py` `identity_queries.py` `identity_audit.py` `normalization.py` | HGNC.resolve.2/3、补充证据、A01/A02 标准化发布 |
| A03 交集 | `intersection.py` `intersection_flow.py` | T∩D、双排序、韦恩图、A03_SELECT |
| A04 PPI | `ppi.py` `ppi_flow.py` `ppi_identity.py` | STRING 获取、三指标两轮、身份缺口授权 |
| A05 富集 | `enrichment.R` `enrichment_flow.py` `enrichment_plot.py` | clusterProfiler ORA 与图 |
| A06 对接 | `docking_*.py` | 受体、配体、P2Rank、重对接、批量对接、复用、热图、任务包、通用自动化 |
| A07 报告 | `report_flow.py` `report_flow_pathway.py` `report_dispatch.py` `report_figures.py` `report_pathway.py` `pathway_review.py` | 双报告、通路审核 |
| 原网页 | `web.py` `main.py` `start.ps1` 及 `*_ui.py` | 原工作台（`start.cmd` 启动），模块操作（运行、上传、范围决定、候选选择、对接方案、通路审核）目前仍从这里进入 |

## 3 待拆解清单（交给后续开发，逐项单独 PR）

已在 2026-10-08 删除不再被引用的病例脚本（可从 git 标签 `legacy-v1-20261008` 恢复）。下列问题仍在，拆解时遵守第 1 节：

1. **研究编号与授权写死在代码里**：`ppi_identity.py`（COPD 与过敏性鼻炎的 A04 授权常量）、`disease.py`、`normalization.py`（`COPD_TERMS`）、`report_flow*.py`（病例文案）、`docking_top10_execute.py`。目标：授权改为研究包内的决定文件，代码不出现研究编号。
2. **缺陷：`ppi_flow.py` 未传授权时回退到 COPD 授权**（`approved_scope or SCOPE`）。应改为没有授权就阻断并给出中文原因。
3. **通用路径依赖病例脚本**：`docking_automation_compute.py` 导入 `docking_top10_execute` 的私有函数；`docking_result_reuse.py` 导入 `docking_top10_publish`。目标：把被引用的函数原样移到通用模块，再冻结病例脚本。
4. **A07 校验不一致**：`docking_automation.py` 使用旧版 `report_flow.validator`，原网页使用带通路核验的版本。应统一通过 `report_dispatch`。
5. **重复实现**：`report_flow.py` 与 `report_flow_pathway.py` 约 99% 相同；热图（`docking_dynamic_heatmap.py`、`docking_grouped_heatmap.py` 及 `docking_formal.py` 内的旧实现）；任务包 v1/v2；`docking_formal.py` 一个校验器混合四套规则。目标：每类一个实现、按版本号分派，旧版本行为逐位不变。
6. **平台绑定**：`docking_*`、`enrichment_flow.py`、`report_*` 中的 Windows 路径（Rscript、PyMOL、Vina、字体）。目标：全部改从 `config/local.toml` 与工具清单读取。
7. **复用键**：对接复用缓存键包含源文件指纹，挪动代码会让复用全部失效。改动对接代码前，先把缓存键改为算法版本号，并为旧缓存条目建立对照表。
8. **依赖锁定**：补 `pyproject.toml` 与锁文件、R 的 `renv.lock`；`environments/` 下的二进制改为工具清单管理。
