# api/ — 本机 JSON 接口契约（前端与后端的唯一约定）

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
| 400 | BAD_REQUEST | JSON 或编号格式错误 |
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
