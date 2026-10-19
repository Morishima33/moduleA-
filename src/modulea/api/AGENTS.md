# api/ — 本机 JSON 接口契约（前端与后端的唯一约定）

## 2026-10-19 全模块操作导航

ModuleView新增可空`operation_guide:{current_step,note_zh,steps:[{key,label_zh,detail_zh,target,module_id?,href?}]}`。current_step为从1开始的建议操作位置，不是完成率、模块状态或批准。仅只读组合本页已有归档展示字段及Workflow给出的状态；不计算科学结果，不改变权限。当前A00、A01、A03、A03_SELECT、A04、A05、A06_PREP、A06、A07均提供各自流程；A02沿用既有disease_workflow和未保存范围保护。历史页不提供操作导航。本批准备关联使用只读资料核查步骤及原关联结果地址，不能提示重复批准或质控执行。

target为本页稳定区域编号；module_id导航至同研究模块；href仅沿用本页已核验关联结果地址。点击只定位或切页，不能提交复核、后台任务、下载生成或科学选择。目标尚无操作区时定位状态/明细并解释等待条件，不生成虚假的计算按钮。前端可提示本地未保存选择，但不得将其视为归档完成。

## 2026-10-19 A02按操作顺序导航

当前A02的ModuleView新增`disease_workflow:{current_step,note_zh,next_label_zh,next_target}`，仅根据本研究归档事实、同版本预览及Workflow批准状态给出操作定位，不修改模块状态或批准权限。六步为资料、范围、身份预览、确认生成、整体复核、A03。历史版本不提供导航。DiseaseScopeInfo新增`saved_counts:[{value,label_zh,count}]`，计数单位为已保存的范围组，前端未保存的编辑不回写计数。前端存在未保存范围修改时提示先保存并暂禁预览/发布，后台原有版本校验保持。

## 2026-10-17 A02范围到标准化的完整衔接

2026-10-19操作澄清：预览表明确标注“预览”，确认表单和生成按钮置前，右侧复核可定位该表单。有同版本预览时state.reason_zh/review.blocked_reason_zh明确说明“身份预览已完成，尚未生成待复核结果”，不更改state.code或allowed_decisions。normalization.enabled在缺少固定公共参考包时为false并列出缺失文件；后台执行仍核查完整文件及原有指纹。两类人工关口保留。

当前A02候选的ModuleView增加`normalization`，包含enabled、disabled_reason_zh、expected_a00/a01/a02、scope_note_zh及preview。preview仅取本研究、相同三个输入版本的后台预览，含stamp、两侧summary与完整identity_issues、source_exceptions；不在GET执行标准化。POST `/studies/{sid}/modules/A02/actions/normalization`接收相同expected版本和`action:preview|publish`。preview提交`normalization_preview`后台任务，仅写runtime本研究预览，不改研究；publish还需stamp、reviewer、note、confirmed:true、accept_omit:boolean及accept_source_exception:boolean，调用既有normalization.publish生成待复核结果。范围未决、上游失效、回收站和忙碌均禁止，后台再次核验三个输入及预览指纹。身份例外和缺库例外必须分别明确接受；无预选、不代签、不启动A03。全排除允许既有空结果流程，但预览须突出空疾病集合。历史标准化和科学规则保持。

## 2026-10-17 疾病范围核验前置及来源身份防混用

ModuleView增加`disease_scope`：`{enabled,disabled_reason_zh,expected_a00,expected_run,expected_staging,items,choices}`。items包含当前完整scope_groups及`source_name,source_url,identity_warning,direct_allowed`，不受明细分页筛选影响。A02提示框下默认展开，全部范围选项来自后端，不预选本病。
POST `/studies/{sid}/modules/A02/actions/scope_review`：`{expected_a00,expected_run,expected_staging,decisions:[{scope_id,scope}],reviewer,note,confirmed:true}`，必须完整覆盖当前条目且不重复。`a02_scope_review`任务调用既有run_disease的scope_change批次入口，保存新候选，不批准、不运行下游。版本、令牌、回收站和忙碌校验沿用分库上传；后台再次核验。来源文件内检索词与当前研究不符时，拒绝将对应组标为direct，仍可保留待核验或排除。
新上传OMIM Excel使用`omim_xlsx_v2`，旧omim_xlsx接口上传自动升级到该解析分支；历史旧结果按旧格式可复算。新分支识别官方页尾说明而不生成候选。GeneCards/OMIM有可识别检索标题时必须同时匹配本次检索元信息与A00官方词；缺标题明确展示无法自动核对，不能声称已验证。旧来源不回写；旧错库文件显示身份警告，须由用户更换或做范围决定。

## 2026-10-17 A02失败来源定向重试

新增POST `/studies/{sid}/modules/A02/actions/retry_sources`：JSON `{expected_a00,expected_run,expected_staging,databases,reason}`，databases为当前获取失败的OTP/TTD/PharmGKB非空去重列表；只重取选中失败来源。沿用令牌、来源版本、回收站和忙碌校验，后台`a02_sources_retry`进入统一run_disease产生新的待复核A02，其他来源和历史保持。返回202 `{task,created,message_zh}`；版本过期409，不自动重试提交或批准。SourceUploadItem增加可选`can_retry`；状态来自归档source_status。失败或缺资料时数字显示“未取得”，成功空结果才显示0。原始失败查询轨迹随失败来源另存，不作为候选发布。

## 2026-10-16 新建研究与独立项目目录（用户授权）

新增POST `/studies`：`{request_id,formula,herbs,disease,mesh_term,mesh_id,operator,analysis_purpose}`。request_id为`create_`加32位小写十六进制；用途由用户明确选择formal_research或workflow_test。只接受上述字段，不接受客户端MeSH证据、批准、路径或自动计算选项。服务器固定人类9606和“仅本病，不纳入亚型”，复用原NLM核对函数；失败不建研究。核对成功只调用Workflow.create，形成A00待复核，无reviews及后台任务。

首次201；同request_id及同登记的重复请求200并返回原项目，不重复建档，修改字段冲突409。响应`{study_id,run_id,created,directory,message_zh}`。去重记录位于私有runtime/study-creation，A00保存服务器creation_request_id供重启或记录丢失后核对；每次新建操作使用新request_id，同方剂同病也独立目录。session.capabilities新增create_study。

StudyView新增`storage:{directory,folders:[{name,label_zh}]}`，目录仅供查看和复制，不接受页面指定任意文件路径。六类目录为intake、raw、normalized、runs、reviews、reports；各项目所有版本及复核保持原有存储规则。新版首页及研究页提供新建入口，成功进入该项目A00；此功能不代表新疾病全流程已验收。

## 2026-10-15 只读页面性能约定

页面状态仍来自Workflow.view。只读实例在单次请求内复用目录解析及已核验JSON的解析结果；每次独立读取仍逐文件核验SHA-256，不以修改时间代替内容校验。同研究、同manifest版本的并发状态读取合并执行，完成即移除，不缓存已完成状态；每个请求取得独立副本。复核、提交、任务及后台计算继续使用原Workflow，下载仍要求同研究登记及指纹一致。接口字段与权限不变。

## 2026-10-15 初版验收的接续与回收站边界

既有`POST /studies/{sid}:continue`与`POST /tasks/{tid}:retry`在研究处于回收站时返回423 `TRASHED_READONLY`，不建立新任务；恢复后才可显式继续或重试。后台对扩展A06只在A05已批准、所需首位命中图齐备且A07缺失/失效时生成报告。已有有效A07待复核时保持版本，已发布时返回流程完成，不重复生成或撤销现有发布。无显著KEGG时不要求补图。仍无新的研究创建或批量计算端点。

## 2026-10-14 A05排名首位命中定位图

ModuleView新增可选`ranked_pathway_maps`：`{enabled,expected_a05,disabled_reason_zh,semantics_zh,items}`；items为`{ranking,id,name_en,name_zh,count,adjusted_p,not_in_current_kgml,png_url,caption_zh}`。统计显著性与Count两个Top1直接取当前已确认A05展示排名，命中身份与数值保留；无显著条目不补图。
POST `/studies/{sid}/modules/A05/actions/ranked_pathway_maps` JSON`{expected_a05}`→202后台`a05_pathway_maps`。只制作两张KEGG原生图，使用固定pathview1.46.0；红色表示本批命中，不表示表达方向、激活或疗效。官方KGML/底图原件、下载URL/时间/指纹、命中表与节点映射独立归档。
GET `/studies/{sid}/files/ranked_maps_ID.序号`仅下载该研究登记并核验指纹的文件。历史/失效/回收站只读；新图绑定A05结果及确认展示，不更换current/runs/reviews，不代签既有机制通路推荐审批。

## 2026-10-14 A06出图资料与A07顶部下载

中英显示第四版：DrawingPair新增可选`compound_name_en`；DockingTrialInfo.matrix.rows新增`label_zh,label_en`，matrix新增`display_version,heatmap_svg`。名称按稳定compound_id连接同源A03与已归档核查，缺译不猜译。SVG与PNG共用紧凑矩阵几何及右侧纵向色标，8×8范围、完整225格评分范围、原评分、红蓝配色和A/B保持。
`bilingual_display_records`独立附件绑定A06、trial_packet与名称证据，由后台Workflow公开方法只追加PNG/SVG/XLSX/CSV；不更换current/runs/reviews，历史、失效及回收站不能生成新版本。下载键`bilingual_display_ID.序号`仅读取登记文件并核对指纹；trial_view只显示与当前A06及trial_packet同源的最新附件。

ModuleView新增可选`docking_artifacts`：`{enabled,disabled_reason_zh,expected_a06,eligible_count,ready_count,pairs,images,bundles}`。
组合行`{pair_key,compound_id,compound_name_zh,target_id,target_zh,score,eligible,package_url}`；资格以同源原始评分≤−8为本轮整理范围，不是科学通过阈值。未达范围及NA不自动生成包。
图片行`{artifact_id,name_zh,caption_zh,pair_key,created_at,url,width,height}`，同A06版本追加留存；历史和回收站只读。图片不自动纳入已批准报告。

POST `/studies/{sid}/modules/A06/actions/figure`：multipart单一`upload`（PNG/JPEG，≤16MiB），字段`expected_a06,caption,pair_key`（组合可留空）→202后台`a06_figure`完整解码并归档。
POST `/studies/{sid}/modules/A06/actions/pair_packages`：JSON`{expected_a06,pair_keys}`→202后台`a06_pair_packages`仅为选中且原值≤−8的组合生成PDB/PSE/PML、同源Top-1、输入及参数，然后自动形成所选下载合集；不运行Vina。重复请求复用已完成包，失败保留资料供重试。用户已更正为只提供按需按钮，不预先批量制作；接口内部登记`request_version=A06.drawing.on_demand.2`，旧批量请求不得恢复执行。
POST `/studies/{sid}/modules/A06/actions/pair_bundle`：同样JSON→202后台`a06_pair_bundle`只打包已有组合包，未准备组合拒绝；下载包仅含选中组合。
GET `/studies/{sid}/files/dock_artifact_ID.序号`只接受该研究归档索引中的文件，逐字节核验，不接受任意路径。所有写入经Workflow公开方法和写锁，绑定当前有效A06；不更换运行、批准和报告。
A07下载卡置于标题之后、结论之前；报告下载键及内容保持原契约。

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

## A06两遍方案及成分选择（2026-10-11）
新增ModuleView.compound_selection及docking_preparation：只读当前来源、草案、资料状态和人工方案，不推算科学成功。
POST /studies/{sid}/modules/A03_SELECT/actions/selection：{expected_a03,expected_select,selected,manual_supplements,reviewer,reason,confirmed:true}，后台a03_selection调用既有选择规则，生成待复核版本，不自动批准。
POST /studies/{sid}/modules/A06_PREP/actions/two_pass_plan：{expected_source,expected_plan_id,confirmed_target_ids,reviewer,note,confirmed:true,plan}，后台a06_plan仅保存A06.two_pass.plan.1。plan含policy_version、compounds、receptors、package_id、pymol_executable；每受体保留first/second结构方案及原因，第二遍实验/AlphaFold，核查项不足不可批量确认。
POST /studies/{sid}/modules/A06_PREP/actions/material：{expected_source,compound_id,cid,name,content_base64}，仅独立归档用户提供的来源SDF，身份待后续准备核验，不生成三维构象、不自动批准。
以上写入口均核对当前研究、批准来源、过期/历史/回收站/任务忙碌，使用原令牌和同源保护。计算入口继续关闭；保存完整方案不表示严格质控或对接成功。

POST .../modules/A06_PREP/actions/check_two_pass：{expected_source,plan}→{items:[{target_id,valid,bulk_allowed,reason_zh}],calculation_started:false}；无写入，只校验完整当前受体草案。valid只表示字段/来源满足人工确认要求，不能显示为科学通过。明确NA项valid=true且bulk_allowed=false；未提供资料/格式失败两者均false。
后台任务payload沿用manager既定字段，重试使用同一内部plan_id，已保存同一请求不重复追加；更换来源/方案后旧请求阻断。结果契约需同源input_key、Vina版本和完整组合覆盖；completed必须Top-1及实际归档姿势指纹通过，NA须null评分和原因。本轮未新增真实计算入口。

## A06成分核查与矩阵展示 v1
ModuleView新增docking_review（A03_SELECT/A06_PREP/A06当前页；历史页null）。
字段为enabled、reason_zh、review_id、proposal（研究级不可变资料；schema_version、study_id、binding、compounds、excluded、display、source_files、note_zh、planned_pairs）、matrix（status_zh、ready、heatmap/table的rows/columns/cells、full_pair_count、score_range）。
compounds逐项包含compound_id、name、name_zh、cid、herbs、intersection_count、main_rank、identity_prechecked、identity_state_zh、source_3d_state_zh、manual_reason_zh、evidence_zh。预核对不表示人工批准；数据缺失/冲突不可全选为已核对。
display记录heatmap_compounds/heatmap_targets/table_compounds/table_targets以及A优先、Degree降序、HGNC编号稳定展示的规则；完整受体仍保留，展示裁切不改变计算范围。
selection请求兼容旧字段；存在本轮草案时须额外传expected_docking_review，API与后台均核验草案编号、源版本及身份预核对资格，拒绝旧草案和未核实身份。保存仍生成待复核结果。
草案通过Workflow公开方法在写锁内追加docking_review_records；不改current/runs/reviews，不签署身份、不执行科学工具。结果适配仅接受当前批准成分与完整A/B受体、同源准备输入和完整结果契约，检查真实Top-1姿势指纹；无本轮评分仅显示待计算。
新矩阵科研单蓝渐变，越负越深；NA灰色，不填零，不隐去无评分行列。旧热图规则及历史版本保持。
可选proposal.acetic_trace提供当前来源冲突对照（bulk/detail/official）、归档计数与逐行trace；网页只读显示原始基因、来源条目、HGNC映射及当前交集成员，不重新归属靶点。planned_pairs保存全部待确认组合，评分为null；matrix.result_version、score_range、cells.color/text_color仅从同一有效结果生成。


## A06受体资料核查包（2026-10-11）
ModuleView.docking_preparation新增可选metadata_review：{review_id,created_at,note_zh,execution_allowed:false,approval:null,compounds,receptors}。compounds为当前已批准成分的中文名、CID、来源三维状态和指纹证据；receptors为完整当前A/B名单、UniProt、官方身份说明、第一/二遍待核查状态、候选实验结构摘要和历史失败。候选含PDB、官方链接、方法、分辨率、目标作者链及序列长度、共晶组分及作者链；这些仅为元数据，不能据此显示严格/探索质控通过。检索范围和未核实的突变、结合域、配体定位/共价关系必须说明。
核查包通过Workflow.save_receptor_review公开方法在写锁内追加至decisions/A06_receptor_review，并由manifest.receptor_review_records索引。绑定当前source_key，核对已批准名单、A/B、来源文件、禁用执行及未批准状态；历史/回收站不提供操作，上游变更后旧包不展示。结构准备、P2Rank、AlphaFold模型、重对接和Vina均不触发。原two_pass_plan与material写接口不变。


## A06矩阵配色第二版（用户于2026-10-11确认）
新增A06.matrix.display.2：冰蓝#A7D5E5→莓果红#B7326B，越负越偏莓果红，NA灰色。旧display.1单蓝版本保留。matrix新增palette{id,high_color,low_color,na_color,unit,label_zh}及heatmap_svg:string|null；SVG使用同批完整score_range，含实际色标、单位与NA说明。无真实评分时SVG为null；恒值使用中间色，全部NA不编造数值范围。前端只显示服务端色值/说明并下载同源SVG和PNG，不推算科学评分。
通过Workflow.save_matrix_display公开方法只追加展示配置至decisions/A06_matrix_display和manifest.matrix_display_records，绑定已批准成分和当前source_key、核查草案编号；展示窗口保持，名单和审批不变。过期配置不回退旧配色，明确待重新绑定。导出与专业报告A06章节共用matrix_exports和matrix_report_section，验证同批矩阵与色值。


## A06核查草案暂存（2026-10-12）
POST .../modules/A06_PREP/actions/two_pass_draft：{expected_source,expected_plan_id,expected_draft_id,plan,checked_target_ids,reviewer,note}→201 {draft,message_zh}。允许来源绑定且身份范围完整的未完成字段，只暂存人工输入，不生成运行、不批准方案、不启动计算；核验人/说明可暂空。服务端追加decisions/A06_two_pass_draft和manifest.two_pass_draft_records，保存原请求，重试内容一致才返回旧记录。未知字段、质控/评分/执行字段、跨研究、旧来源或过期草案均阻断。
docking_preparation新增expected_draft_id及draft|null（draft_id、created_at、reviewer、note、checked_target_ids），plan优先显示与当前来源及完整方案版本一致的最新草案。刷新可恢复填写与合法逐项勾选；整体确认框永不自动恢复勾选。新完整方案使旧草案成为历史；上游改变后不回退早期草案。
存在有效草案时，two_pass_plan确认请求必须额外携带expected_draft_id并与最新版本匹配；无草案的旧请求仍兼容。完整确认、结构质控与结果批准保持原规则，草案不因字段齐全被视为已确认。


## 2026-10-12 A06集中核对与一次提交
现有check_two_pass响应和docking_preparation新增confirmation：{ready,receptor_count,compound_count,planned_pair_count,normal_target_ids,pending,unavailable,execution_allowed:false,note_zh}。pending与unavailable逐项为{kind,id,label_zh,reason_zh}，使用既有完整校验器生成；字段齐全不是结构质控通过。确认窗口只在用户主动勾选整体核对后提交正常受体完整ID；明确NA项在同一窗口逐项核对，不参与全选。未完成时只显示缺口，可保存草案，不提交完整确认。原完整方案请求、研究版本、令牌和独立审批保持。


## A06获准来源原件核查（2026-10-12）
docking_preparation新增source_review（当前同上游A06.source_review.1原件及只读核查，approval:null、execution_allowed:false）。既有metadata_review显示已取同身份三维及原始坐标清点，不能显示当前质控通过。source_review.choices仅是需用户核对的替代构象或路线建议，未选择不代填。
草案和完整方案请求新增可选expected_source_review_id；当前有来源原件核查包时必传并核对，旧无核查包请求兼容。原件更新使旧草案或完整方案不再作为当前确认，历史保留。所有研究写入仍经公开Workflow，当前source_key、名单、来源CID、原件字节及版本全部核对。资料获取授权不等于方案确认或真实计算授权。

GET /studies/{sid}/source_reviews/{review_id}/files/{file_key}仅下载该研究索引内已归档且指纹完整的原件，无任意路径参数；旧版本可只读追溯。source_review.choices为{kind:altloc|route,target_id,symbol,pdb_id,round:first|second,options,reason_zh,proposal?}。原始缺失记录仅供核查，不按数量自动判定口袋完整。

## A06真实结构质控任务（2026-10-12用户明确继续）

新增私有任务a06_quality，仅接受当前研究已登记A06.quality.authorization.1授权与方案、来源版本，执行来源三维准备、受体准备、P2Rank与参考配体Top-1重对接。没有新增网页启动或批量评分端点；不能通过hidden参数解锁研究成分对接。任务经Workflow生产入口发布A06.two_pass.execution.1新版A06_PREP，预测口袋证据未人工确认及环境待核定时handoff_blocked保持；不代签结果。旧科学结果校验保持。任务进度、日志、失败、取消和版本过期按既有接口处理。

DockingPreparationInfo新增quality_status_zh：仅从绑定当前已确认方案的真实A06_PREP归档或活动任务读取。未完成、过期与已归档分别说明；前端不根据已确认方案推算质控通过。

## A06扩大覆盖与集中采用（第二版）
ModuleView新增docking_coverage：{enabled,disabled_reason_zh,expected_run,expected_source,campaign_id,expected_decision_id,confirmed,draft,rows,counts,batch_docking_allowed:false,note_zh}。counts分别为strict、exploration、unavailable、receptors，技术资格与人工采用分开；rows包含target_id、symbol、candidate_grade、ppi_order、pdb_id、rmsd_A、quality_zh、status_zh、reason_zh、eligible、adopted、selected、spec及可折叠的attempts摘要。仅完整证据可确认；第一遍失败不靠更换同一结构口袋绕过。
POST .../modules/A06_PREP/actions/coverage_selection：{expected_run,expected_source,campaign_id,expected_decision_id,selected_target_ids,reviewer,note,confirmed:boolean}。false仅追加草案并刷新恢复；true需核验人、依据和非空可用范围，追加人工采用决定及A06.coverage.confirmed.4准备版本。未解决项只阻断对应组合；主要五仍需至少五个已采用严格受体。采用确认不批准结果、不运行批量评分。安全、写锁、忙碌/回收站/来源与版本检查均保留。
新增私有a06_coverage任务：仅用研究索引登记的A06.coverage.authorization.2执行独立候选资料与结构质控，产生A06.coverage.execution.4。技术候选全部待采纳，旧证据和失败历史保留；没有公开批量计算端点。

采用确认POST返回202后台a06_coverage_confirm，接口只读校验、后台由完整校验器产生新准备版本；草案返回201。任务失败保留原技术归档，旧请求不自动重签。

第四版追加最终证据审计：原位点相关范围与必要伙伴/金属再核对，单体模型不能绕过环境；当前输入包含实际采用证据及历史完整包指纹，失败历史不回写。conditions给出main_results、exploration与prepared_pairs，均由后端归档读取。只读请求内复用已核验不可变数据，写入/下一请求重新核验；旧窗口expected_run先阻断，不重复构造整张页面。

## A06独立全覆盖试算（2026-10-13用户明确授权真实计算）
新增私有a06_trial后台任务，通过TrialWorkflow.begin_trial/finish_trial独立账本发布15×15真实试算；不更换current、正式结果或reviews。绑定已批准来源、准备、方案、来源原件与展示名单；失败重试沿用私有请求并重新检查版本。ModuleView.docking_trial只读返回225格、服务端色值、两位小数展示所需原始精度、组合/区域进度、受体处理证据及索引下载。未完整完成时无评分矩阵。GET files/trial_ID.index仅访问该研究已完成试算索引且指纹匹配的文件，无任意路径。POST actions/trial_review仅接受trial_id、reviewer、note、confirmed，保存独立核查；不代签正式A06、不运行计算，回收站/过期/忙碌阻断。页面支持现有任务日志、取消、失败重试。


## A06扩展试算交接（2026-10-14）
当前A06/A06_PREP新增可选trial_handoff：{run_id,active,trial_id,review_url,note_zh,reviewer,note}。仅A06.trial.handoff.1当前运行提供，历史页面不提供。review_url跳转本批A06；reviewer/note取绑定的已确认试算核查，仅预填不预选决定。新A06依赖显示其实际parent_runs（A03/A03_SELECT/A04），全局旧依赖契约保持；正式可复核性仍来自内核。


## 本批准备关联（2026-10-14）
ModuleView新增可选trial_preparation，仅当前A06_PREP页提供：{link_id,created_at,active,read_only,reason_zh,a06_run_id,trial_id,result_url,source_url,reviewer,reviewed_at,note,a06_reviewer,a06_reviewed_at,receptors,compounds,history_rows,legacy_run_id}。数据来自Workflow核验的独立A06.trial.preparation_link.1关联及同批归档；不更换current或新增科研reviews。历史页面不提供当前关联。GET files/{prep_link_id}.{index}仅下载研究索引内关联的files，逐字节验证；包括原件、准备文件及原核查记录，无任意路径。
新增状态scope_confirmed，中文“准备范围已核查（扩展试算）”；不等于approved，不开放复核或自动继续。原准备状态留在历史区。导航、标题与待办均使用Workflow视图；关联失效为stale，不自动沿用。progress新增completed（正式批准及本批准备已核查的关口数）与scope_confirmed，approved保持原含义；仅有关联的研究显示完成关口及数量明细。
