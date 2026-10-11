# api/ — 本机 JSON 接口契约（前端与后端的唯一约定）

## A05第二版展示与确认（2026-10-11）

ModuleView新增enrichment_display：{enabled,disabled_reason_zh,expected_a03,expected_a05,expected_decision_id,exclusions_confirmed,layout_confirmed,excluded_ids,missing_translations,catalog,retained_count,excluded_count,significant_count,latest}。catalog为本次完整显著KEGG清单，保留ID、Description、Count、p.adjust、RichFactor、gene_symbols，并附description_zh、translation_status、proposed、reason_zh、evidence_url。latest显示核验人、意见、时间、是否实际应用；保存清单不代表批准A05。

POST /studies/{sid}/modules/A05/actions/display_confirmation：{expected_a03,expected_a05,expected_decision_id,action:exclusions|layout,reviewer,note,excluded_ids,confirmed:true} →202 {task,created,message_zh}。排除清单可以为空，须明确核对；版式确认仅在范围已确认且当前图表中文齐备时接受，并禁止同时修改清单。后台a05_display生成新A05展示修订，统计来源和BH不变；改变清单撤销版式确认。人工确认记录通过EnrichmentWorkflow公开方法留存，失败重试复用同一决定。

special新增enrichment_display_tables：{bp_top15,cc_top15,mf_top15,kegg_p_top10,kegg_count_top10,kegg_excluded}，均为同源归档行；enrichment_graphs：{go|kegg:{url,caption_zh}}。当前版本的历史、失效、回收站和活动任务均禁用写操作。未确认展示范围／版式或中文缺失时，handoff_blocked由A05结果给出，不能选通过；确认后仍须用户独立复核。

本文件是前端开发和接口修改的依据。改动任何字段前先改本文件，并保证前端同步；字段只增不删，删除或改名须用户确认。

## 1 通用约定

- 前缀 `/api/v1`；服务只绑定 `127.0.0.1`，Host 头必须是 `127.0.0.1:<端口>` 或 `localhost:<端口>`。
- **令牌**：`GET /api/v1/session` 返回 `token`；所有 POST 必须带请求头 `X-ModuleA-Token: <token>`。
- **跨源**：默认只接受同源。前端开发服务器（如 `http://localhost:5173`）需启动时 `--allow-origin http://localhost:5173`。生产时前端由同一服务托管，不需要跨源。
- **并发保护**：写请求带 `expected_*` 编号（`expected_review_id`、`expected_action_id`、条目里的 `run_id`）。状态已变化时返回 409 `STALE_VERSION`，前端提示“状态已更新，请刷新”。
- 时间为 UTC ISO 8601，由前端格式化；面向用户的文字字段以 `_zh` 结尾。
- 错误格式：`{"error": {"code", "message_zh", "details", "retryable"}}`。

| HTTP | code | 场景 |
|---|---|---|
| 400 | BAD_REQUEST | JSON、编号或整数查询参数格式错误；`details.field` 指出参数 |
| 403 | FORBIDDEN_ORIGIN / BAD_TOKEN | 安全检查失败 |
| 404 | NOT_FOUND | 研究、模块、运行、表格或文件不存在 |
| 409 | STALE_VERSION | 版本已变化 |
| 409 | GATE_BLOCKED | 上游未通过、`handoff_blocked`、A07 通路未对齐 |
| 413 | BODY_TOO_LARGE | 请求超过 1 MB |
| 422 | VALIDATION_FAILED | 复核人或意见为空、决定不合法等 |
| 423 | TRASHED_READONLY | 研究在回收站 |
| 503 | ARCHIVE_UNAVAILABLE | 归档文件指纹核验失败（例如 LFS 文件未下载完） |
| 503 | TOOL_UNAVAILABLE | 本机缺少某项依赖（例如 A07 通过校验需要 python-docx） |

## 2 状态码（与原型《模块状态样式一览》一一对应）

| code | 中文 | 复核栏 |
|---|---|---|
| idle | 未开始（上游未通过） | 不显示 |
| ready | 可以开始 | 不显示 |
| running | 运行中（有后台任务） | 不显示 |
| incomplete | 未完整提交（无任务在跑，可能中断） | 不显示 |
| failed | 执行失败 | 不显示 |
| waiting | 等待资料（`handoff_blocked`，不能选“通过”） | 显示，`allowed_decisions` 不含 approved |
| empty | 有效空结果·待复核 | 显示 |
| review | 待你复核 | 显示 |
| hold | 暂存待定 | 显示 |
| returned | 已退回修改 | 显示 |
| approved | 已通过 | 收起，只保留“更改决定” |
| stale | 已失效 | 不显示 |
| published | 已发布（仅 A07 通过） | 收起 |
| unavailable | 归档未就绪 | 不显示 |
| history | 历史版本（只读，`?run_id=` 查看旧运行时） | 不显示 |

前端**不得**自行推算状态；以 `state.code`、`review.can_review`、`review.allowed_decisions` 为准。
研究在回收站时，各模块仍显示原有状态，但 `can_review=false`，`reason_zh` 说明“回收站中只读”；研究卡片的 `study.trashed=true`。

## 3 端点

| 方法 路径 | 用途 |
|---|---|
| GET `/session` | 令牌、版本、平台、能力开关 `capabilities`、决定中文名 `decisions_zh` |
| GET `/studies` | 首页研究卡片 `{items: StudyCard[]}` |
| GET `/trash` | 回收站中的研究卡片 |
| GET `/studies/{sid}` | 研究页 `StudyView` |
| GET `/studies/{sid}/modules/{mid}` | 模块页 `ModuleView`；`?run_id=` 查看历史版本 |
| GET `/studies/{sid}/modules/{mid}/runs` | 中文运行历史 `{items: RunItem[]}` |
| GET `/studies/{sid}/modules/{mid}/tables/{name}?page=&size=&q=&run_id=` | 明细表分页：`{kind:"rows", columns: [字段名，按原表顺序], total, page, size, items}`；或 `{kind:"object", data}` |
| GET `/studies/{sid}/files/{key}?inline=1` | 下载归档文件。`key` 为 `<run_id>.<序号>`（来自 `ModuleView.files[].key`），或 `<run_id>.r<行号>`（A07 报告登记在 report_files 表中时）；两种都逐字节核验指纹。`inline=1` 且为图片时内嵌显示 |
| POST `/studies/{sid}/modules/{mid}/reviews` | 复核：`{run_id, expected_review_id, decision: approved\|rejected\|pending, reviewer, note, after: "save"\|"continue"}` → 201 `{review, task, message_zh}` |
| POST `/studies/{sid}/reviews:batch` | A01+A02 一次提交：`{reviewer, entries: {A01: {run_id, expected_review_id, action: "decide"\|"preserve", decision, note}, A02: {...}}}` → 201 `{reviews, task, message_zh}`；两项都通过时自动开始生成 A03 |
| POST `/studies/{sid}:continue` | 手动推进到下一人工关口 → 202 `{task, created}` |
| POST `/studies/{sid}:trash` / `:restore` | `{operator, reason, expected_action_id, confirm: true}` → 201 `{action}` |
| GET `/inbox` | 跨研究待办 `{items: [{study_id, study_title_zh, module_id, code, label_zh, text_zh}]}` |
| GET `/tasks?study=&active=1` | 任务列表 |
| GET `/tasks/{tid}` / `/tasks/{tid}/log?offset=` | 任务详情 / 增量日志 `{offset, next_offset, text}` |
| POST `/tasks/{tid}:cancel` / `:retry` | 取消 / 重试 |

任务对象 `Task`：`{task_id, study_id, kind, kind_zh, state: queued|running|succeeded|failed|cancelled|interrupted, state_zh, requested_by, message_zh, error_zh, progress: {step_zh, done, total}|null, created_at, started_at, finished_at}`。前端每 3 秒轮询有活动任务的研究即可。

### 参数与任务失败处理（2026-10-09 基础修复）

- `page`、`size`、`offset` 不是整数时返回 400 `BAD_REQUEST`，`details.field` 为参数名。合法整数继续沿用页码至少 1、每页 1—500 条、日志偏移至少 0 的边界处理。
- `Content-Length` 非整数或负数返回 400；超过正文限制仍返回 413。
- 提交/重试的 202 表示任务已登记，**不表示子进程一定启动成功**。启动失败时返回的 `task.state=failed`，同时有 `error_zh` 与 `finished_at`；前端显示失败原因并保留手动重试入口。
- 保存复核的 201 仍表示决定已保存；若随后启动后台任务失败，`message_zh` 明确分别说明保存成功与启动失败，前端用警告提示。
- GET 任务列表/详情时检查进程状态。Windows 只读探测进程，禁止通过 `os.kill(pid, 0)` 检查存活；排队任务保留 30 秒启动宽限。丢失进程的活动任务标记中断，不自动重跑。

## 4 StudyCard / StudyView

```jsonc
// StudyCard（GET /studies 的 items）
{
  "study": {"study_id", "title_zh", "formula_zh", "herbs_zh": [..], "disease": {"name_zh","mesh_term","mesh_ui"},
            "kind", "workflow_profile", "trashed", "created_at", "updated_at"},
  "purpose": {"analysis_purpose": "workflow_test", "banner_zh", "severity": "warning"} | null,
  "archive_ok": true, "archive_error_zh": null,
  "progress": {"approved": 9, "total": 10, "segments": [{"module_id","code","label_zh"}]},
  "next_step": {"module_id": "A07", "code": "review", "text_zh"} | null,
  "todo_count": 1,
  "active_task": Task | null
}
// StudyView（GET /studies/{sid}）
{
  "study": {...同上}, "purpose": {...}, "archive_ok", "archive_error_zh",
  "progress": {"approved", "total"},
  "nav": [{"group_zh": "交集与候选", "modules": [{"module_id","title_zh","sub","code","label_zh"}]}],
  "next_step": {...}, "inbox": [{"module_id","code","label_zh","text_zh"}],
  "active_tasks": [Task], "management": {"expected_action_id": "action_..."|null}
}
```

## 5 ModuleView（GET /studies/{sid}/modules/{mid}）

```jsonc
{
  "module": {"module_id","title_zh","group_zh","purpose_zh","sub","depends_on": [..]},
  "state": {"code","label_zh","reason_zh","raw_state","is_empty_result","handoff_blocked","can_review"},
  "purpose": {...} | null,
  "run": {"run_id","artifact_id","order_zh":"第 3 次运行","created_at","finished_at","reason_zh","parent_runs":{},"is_current","is_active"} | null,
  "outcome": "success"|"empty"|"failed"|"partial"|null,
  "kpis":  [{"label_zh","value","text","note_zh","source"}],          // 关键数字卡片
  "flow":  [{"label_zh","value","text","note_zh","delta_zh","kind": "main"|"plain"|"end"}],  // 数量变化链
  "flow_note_zh": "...",
  "focus": [{"tier": "must_handle"|"should_know","title_zh","body_zh","impact_zh","blocks": ["A03"]}],  // “本轮你只需核对这些”：must_handle 置顶
  "params": [{"label_zh","value","origin": "recorded"|"outline"|"decision"|"run_config"}],  // 参数与版本页签
  "table": {"columns": [{"key","label_zh"}], "rows": [..], "row_count", "source_table"} | null,  // 结果明细页签的摘要表
  "special": {...模块专属，见第 6 节...},
  "review": {
    "current": {"review_id","decision","reviewer","note","created_at","batch"} | null,
    "history": [..], "can_review", "allowed_decisions": ["approved","rejected","pending"],
    "blocked_reason_zh", "expected_review_id", "run_id", "batch_with": "A02"|null,
    "continue": {"available","note_zh"}, "already_approved"
  },
  "downstream": {"note_zh", "modules": [{"module_id","title_zh","code","label_zh"}]},
  "trace": [{"label_zh","value"}],                      // 来源与追溯页签
  "files": [{"key","role","name","path","bytes","sha256","inline"}],
  "tables": [{"name","kind": "rows"|"object","row_count","columns"}],   // 可分页查看的完整明细
  "history": [{"run_id","order_zh","created_at","reason_zh","outcome","review_decision","is_current"}],
  "tasks": [Task], "historical": false
}
```

`batch_with` 不为空时（新流程的 A01/A02），复核栏应提供“与 A0x 一起提交”，调用 `reviews:batch`。

## 6 special（模块专属数据）

| 模块 | 键 | 结构 |
|---|---|---|
| A03 | `venn` | `{formula_only, both, disease_only, formula_total, disease_total}` |
| A04 | `ppi_top` | 第一轮按 Degree 降序前 10：`[{symbol, degree, bc, cc, round2, bar(0–1)}]` |
| A05 | `enrichment_top` | `{bp|cc|mf|kegg: [{id, description, count, gene_ratio, p_adjust, rich_factor}]}`（与归档展示表同源） |
| A06 | `heatmap` | `{unit, orientation:"rows=compounds, columns=receptors", color_rule_zh, min, max, receptors: [{name, order, pdb, rmsd, status_zh, role_zh}], rows: [{compound_id, compound_name, cells: [{receptor, value|null}]}], omitted: [{kind, name, reason_zh}]}` |
| A07 | `conclusion_zh`、`leads`、`limits`、`pathway`、`report_files` | `leads: [{title_zh, fact_zh, next_zh}]`；`limits: [str]`；`report_files: [{role, label_zh, key, path, sha256, row}]`（`key` 为空表示该文件不可下载） |

热图规则：整行或整列没有有效评分的不画（列在 `omitted` 中并在图下说明）；单个缺失格 `value: null` 显示白底“NA”，不填 0、不填灰色。颜色：数值越负红色越深，越不负蓝色越深，红到蓝平滑过渡，不设通用阈值。

## 7 修改本层的规则

- 视图只读归档结果，不计算科学结果，不联网；新增字段先写进本文件。
- 安全措施（Host、Origin、令牌、CSP、仅下载索引文件）不得放宽。
- 新增写操作：在 `server.py` 路由表登记，写入只能通过科学内核 Workflow 的公开方法，长计算必须走后台任务。
- 模块操作（运行、上传、范围决定、候选选择、对接方案确认、通路审核）尚未接入新接口（`capabilities.module_actions=false`），原网页仍是这些操作的入口；接入时为每个操作定义 `POST /studies/{sid}/modules/{mid}/actions/{action}` 并在 ModuleView 中提供 `actions` 列表及参数结构。


## 2026-10-09 A01 三库归档结果展示

A01 使用既有 `kpis`、`flow`、`params`、`table` 和 `focus` 字段展示三库归档，不新增状态来源。摘要含 `候选成分分组数` 时，区分结构键分组与结构待核分组；828 等数量只读归档，不能称为已全部核实的独立物质数。来源摘要表按 `component_sources` 的来源编号去重计数，跨库来源计数不可相加作为最终分组数。A01/A02/A03 的原始结果、来源和例外继续由分页及下载接口提供。

已有研究的独立本地快照保留原运行和审批绑定；显示原批准不代表重构实现已经验收。上游三库更新后旧 A03_SELECT/A04—A07 的失效由 Workflow 判定，不自动重算、批准或替换旧报告。本轮不把代码中的导入函数表示为网页通用上传入口已完成。

## 2026-10-09 来源名称与前十展示

模块首段 `module.purpose_zh` 按绑定方案列出实际数据库名称，历史 DisGeNET 方案不替换成 PharmGKB。A03 `special.component_top` 为归档 ranking 的前十及第十个同分并列；字段保持原名，`component_top_note_zh` 解释排序与用途。完整 ranking 分页不截断，不改变科学排序、候选名额或韦恩图说明。

## 2026-10-09 分库上传接口

A01/A02模块视图新增 `source_uploads`（历史及回收站只读）：`enabled`、`disabled_reason_zh`、`expected_a00`、`expected_run`、`expected_staging`、`note_zh`、`can_process`、`process_reason_zh`、`sources`。sources各项包括database、label_zh、status_zh、formats[{value,label_zh,accept,template_url}]、hint_zh、uploaded_name、sha256、download_url；全部由后端给出。

- GET `.../modules/{mid}/sources`：当前分库入口及资料状态。
- GET `.../modules/{mid}/sources/{database}/template?format=...`：该库该格式模板；A01为官方原始资料ZIP包装规范及字段示例，A02复用原解析器的字段模板。
- GET `.../modules/{mid}/sources/{database}/file`：当前研究绑定的原始资料，先核验归档指纹。
- POST `.../modules/{mid}/actions/upload`：multipart/form-data，一个upload文件（最多16MiB，整包17MiB）。字段database、format、encoding、query、retrieved_at、version、source_url、reason、expected_a00、expected_run、expected_staging、confirmed=yes；字段非空及格式需校验。令牌、Origin和Host要求保持不变。立即返回202 `{task,created,message_zh}`，解析和归档在后台科学任务中执行。
- POST `.../modules/A01/actions/process_sources`：JSON `{expected_a00,expected_run,expected_staging,reason}`，完整三库包及HGNC依据齐备后，后台沿用现有算法生成新的待复核A01。未知身份不继承历史例外，缺资料/映射依据明确失败。

A02上传通过现有run_disease单库替换入口产生新候选，不自动批准或标准化。A01上传先按库校验并版本化留存，原结果保持；页面明确提示上传资料尚未进入结果。三库整理为用户另行触发的操作，绝不因上传而后台代签。历史文件只追加；同研究已有活动任务时拒绝第二次不同写操作。任务保存私有输入以支持失败重试，不向公共Task或日志输出上传内容。

## 2026-10-10 A04双分支展示

A04.dual.1新增`special.ppi_dual`：`{version, thresholds, degree_rows, bc_cc_rows, counts, note_zh, network_note_zh}`。rows分别来自归档`degree_top10`、`bc_cc_top15`，均为第二轮排名含边界并列；空数组代表真实空候选。thresholds来自`dual_thresholds`，counts含两分支两轮数量。BC/CC平级，分别用平均名次处理同值，再取两项名次平均；原始指标不相加。完整四轮名单、排名和指标继续通过既有明细接口提供。旧`ppi_top`保留历史第一轮含义，新版不同时输出该键。网络方案尚未确认时只显示说明，不输出正式新图。新双分支不提供旧`round1`别名供对接使用；对接来源待用户决定。

## 2026-10-10 用户确认第一轮网络及实际A04计算

A04.dual.2沿用双分支阈值，新增归档degree_round1_top10（第一轮Degree排名前十及边界并列）；旧degree_top10仍指第二轮，历史dual.1不变。special.ppi_dual新增degree_round（1或2）、network（null或{url,caption_zh}）；新版degree_rows来自degree_round1_top10，BC/CC仍来自第二轮bc_cc_top15。network.url只绑定本次结果files内的已核验PNG。

ModuleView新增ppi_run（A04且非历史时）：{enabled,disabled_reason_zh,expected_a03,expected_a04}。POST /studies/{sid}/modules/A04/actions/run_ppi JSON {expected_a03,expected_a04,reason}：先核验当前已批准A03及旧A04编号，再提交后台a04_ppi任务；任务入科学写锁后再核验。仅产生A04，不运行A05/A06、不代签结果；旧版保留。session.capabilities新增ppi_compute=true。失败重试仍使用原版本绑定，已过期时须刷新重新提交。

A04专用任务a04_ppi完成后停在A04。助手修复图件时可通过私有任务payload提供reuse_source_run，必须等于expected_a04，且原run同研究、同A03；使用指纹核验的原始STRING包归档新A04版本，不覆盖旧文件。公开页面按钮默认重新获取来源，不提供该私有参数。图元数据采用degree_network单行平面表，与结果files中的SVG/PNG指纹绑定，遵守既有表格契约。

## 2026-10-10 圆形第二轮Degree图（用户认可）

A04.dual.3保留dual.2筛选及表格口径，仅新增degree_network_rule=A04.degree_round2_circular.1。special.ppi_dual新增可选network_round=2；degree_round=1仍说明Degree表来自第一轮，不用于描述图。图展示degree_round2全部候选和真实诱导边，degree_top10（第二轮前十含边界并列）标红，其余蓝色。network.url仍来自本次A04已核验PNG。历史dual.1/2契约和归档保持不变。

## 2026-10-10 待核验事项优先展示

focus各项新增可选source_table，指定已归档明细表的入口。A04身份项source_table=identity_issues；special新增ppi_identity={total,source_table,note_zh,rows:[{target_id,symbol,returned,reason_zh}]}，rows逐项来自本次已核验归档identity_issues，不重查、不修改身份、不推算处理状态。存在待核验明细时在标题后优先展开，用中文标签显示；点击本项只读查看证据及同运行的已核验下载文件。历史版绑定历史run，保持只读。上传/审核权限、身份授权范围、模块通过门控不变。


## 2026-10-10 身份方案确认与应用

ModuleView新增identity_plan：{enabled,disabled_reason_zh,expected_a03,expected_a04,expected_decision_id,latest|null}。latest只读取Workflow指纹索引中的人工决定及绑定的新A04结果，包含reviewer、note_zh、check_ids、omit_ids、applied_run_id、pending_count、status_zh。历史页只读取原run.inputs.identity_authorization，不提供提交。

POST .../modules/A04/actions/identity_plan：{expected_a03,expected_a04,expected_decision_id,reviewer,note,check_ids,omit_ids,confirmed:true}→202 {task,created,message_zh}。选项只能来自当前身份问题清单；omit_ids是用户明确允许“全部官方稳定编号补查均成功无命中时，仅本次PPI暂不采用”的子集，缺编号、请求失败、编号冲突均不能因此移除。核验人和说明必填，不预填代签。安全要求保持；同研究活动任务拒绝重复提交。后台通过IdentityWorkflow公开方法，在统一写锁内向研究decisions/A04_identity/追加决定并更新manifest.identity_decisions索引。失败重试沿用同一决定编号，不追加重复决定。

新的A04.identity_apply.1冻结人工方案与原A03/A04归档指纹；科学筛选、身份匹配规则和图表顺序沿用dual.3。唯一一致的稳定编号才能采用；原名称返回STRING编号与稳定编号冲突仍失败，不改写原始名称返回。确认的是补查及有限处理方案，不是已核实全部身份或模块通过；剩余问题继续门控。任务失败保留决定和旧结果，成功新增待复核A04，不运行A05/A06。科研结果仍经独立复核。

补查请求及原响应（含失败前已经返回的原文）经Workflow公开方法追加至decisions/A04_identity/，manifest.identity_evidence仅记录文件指纹；不完整取证明确error_zh，不能作为成功空响应。latest新增evidence_url、error_zh。GET .../modules/A04/identity_evidence/{evidence_id}仅下载本研究索引登记且指纹完整的原文；不能指定任意路径。历史页只展示原决定的证据。

同一A03的逐项补查保留已应用的人工范围，新选择追加；决定记录引用原已应用方案，旧运行继续按原决定独立复算。再次计算A04沿用当前结果已绑定的同上游方案，不重复签署；更换A03不继承。

## 2026-10-11 A04复核后的方案状态文字

identity_plan.latest.status_zh在方案已应用且绑定A04被Workflow判定已批准时显示“已应用，A04已通过复核”；未批准仍显示待独立复核，保存未应用仍显示任务结果提示。不新增字段、不改变批准或门控；该文案不由任务成功直接推断批准。

## 2026-10-11 KEGG排除应用后才展示

ModuleView.enrichment_display新增kegg_ready:boolean与kegg_reason_zh:string，由已归档排除确认、最新决定是否已应用和活动任务给出。未确认范围、决定待应用或任务进行中时，special.enrichment_graphs不含kegg，enrichment_display_tables不含kegg_p_top10/kegg_count_top10；GO及完整追溯资料保留。前端本地勾选发生改动时临时隐藏KEGG图表，恢复原选择或新归档应用后解除。原图和统计不覆盖，不重算ORA/BH，不自动批准。

## 2026-10-11 A05第三版紧凑展示

原字段及确认请求契约保持，A05.display.3仍输出同源enrichment_display_tables及enrichment_graphs。前端将Description、description_zh分列，疾病核查25条分页；reason_zh仍完整归档并可展开。接口不重算BH、不改变排除或审批。专业报告第19版同步列序，旧报告继续按旧配置校验。

## 2026-10-11 A06两梯队候选（用户确认）
ModuleView新增docking_candidates，当前A04/A06_PREP/A06提供，历史页为null：
{enabled,disabled_reason_zh,expected_a03,expected_a04,expected_a04_review,data|null,preparation_note_zh}。
data为不可变A06.candidate_groups.1归档：group_id、source_runs、source_review、source_result、rule_zh、note_zh、degree_top15、group_a、group_b、counts；各行保留HGNC、symbol、degree、bc、cc并增加evidence_group。
POST .../modules/{A04|A06_PREP}/actions/docking_candidates：JSON {expected_a03,expected_a04,expected_a04_review,reason}→202后台a06_candidates任务；只取已批准A04第二轮归档名单，保留边界并列，不重算PPI、不下载结构、不启动Vina、不代签。
GET /studies/{sid}/docking_candidates/{group_id}：仅下载本研究索引中的指纹文件。
A=Degree第二轮前十∩BC/CC第二轮前十五；B=Degree第二轮前十五去除A；身份按HGNC。A/B是本项目候选证据分组，与结构质控和临床证据等级独立。更换A03/A04或撤回/重签A04后旧分组不可作当前输入；旧归档和批准保留。候选归档不使旧A06_PREP/A06自动恢复有效。

当前A04已有有效候选归档时，focus不再显示旧“对接来源待确认”，图注改为已归档A/B规则及独立结构质控提示；历史页及尚无分组时原提示保留。科学summary中的历史未定记录不回写。
