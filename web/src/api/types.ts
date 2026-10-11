// 文件用途：本机接口（/api/v1）返回数据的 TypeScript 类型；字段与 src/modulea/api/AGENTS.md 契约一一对应。
// 改字段前先改契约文件，再改这里；前端不自行推算状态。

/** 状态码：与契约第 2 节一致 */
export type StateCode =
  | 'idle' | 'ready' | 'running' | 'incomplete' | 'failed' | 'waiting' | 'empty'
  | 'review' | 'hold' | 'returned' | 'approved' | 'stale' | 'published' | 'unavailable' | 'history';

/** 复核决定的三种取值 */
export type Decision = 'approved' | 'rejected' | 'pending';

/** 接口错误正文 */
export interface ApiErrorBody {
  error: { code: string; message_zh: string; details: Record<string, unknown>; retryable: boolean };
}

/** GET /session 的返回 */
export interface Session {
  token: string; // 写请求令牌
  version: string; // 服务版本
  platform: string; // 运行平台
  capabilities: Record<string, boolean>; // 能力开关
  decisions_zh: Record<Decision, string>; // 决定中文名
}

/** 研究用途（例如流程测试） */
export interface Purpose {
  analysis_purpose: string;
  banner_zh: string;
  severity: 'warning' | 'info' | string;
}

/** 后台任务 */
export interface Task {
  task_id: string;
  study_id: string;
  kind: string;
  kind_zh: string;
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
  state_zh: string;
  requested_by: string;
  message_zh: string | null;
  error_zh: string | null;
  progress: { step_zh: string; done: number; total: number } | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/** 研究基本信息 */
export interface StudyInfo {
  study_id: string;
  title_zh: string;
  formula_zh: string | null;
  herbs_zh: string[];
  disease: { name_zh: string | null; mesh_term: string | null; mesh_ui: string | null };
  kind: string | null;
  workflow_profile: string | null;
  trashed: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** 下一步提示 */
export interface NextStep {
  module_id: string | null;
  code: string;
  text_zh: string;
}

/** 首页研究卡片 */
export interface StudyCard {
  study: StudyInfo;
  purpose: Purpose | null;
  archive_ok: boolean;
  archive_error_zh: string | null;
  progress: { approved: number; total: number; segments: { module_id: string; code: StateCode; label_zh: string }[] };
  next_step: NextStep | null;
  todo_count: number;
  active_task: Task | null;
}

/** 导航中的一个模块 */
export interface NavModule {
  module_id: string;
  title_zh: string;
  sub: boolean;
  code: StateCode;
  label_zh: string;
}

/** 待办条目（研究内） */
export interface InboxEntry {
  module_id: string;
  code: StateCode;
  label_zh: string;
  text_zh: string;
}

/** 跨研究待办条目 */
export interface GlobalInboxEntry extends InboxEntry {
  study_id: string;
  study_title_zh: string;
}

/** 研究页 */
export interface StudyView {
  study: StudyInfo;
  purpose: Purpose | null;
  archive_ok: boolean;
  archive_error_zh: string | null;
  progress: { approved: number; total: number };
  nav: { group_zh: string; modules: NavModule[] }[];
  next_step: NextStep | null;
  inbox: InboxEntry[];
  active_tasks: Task[];
  management: { expected_action_id: string | null };
}

/** 关键数字卡片 */
export interface Kpi { label_zh: string; value: unknown; text: string; note_zh: string; source: string | null }
/** 数量变化链中的一步 */
export interface FlowStep { label_zh: string; value: unknown; text: string; note_zh: string; delta_zh: string; kind: 'main' | 'plain' | 'end' }
/** “本轮你只需核对这些”条目 */
export interface FocusItem { tier: 'must_handle' | 'should_know'; title_zh: string; body_zh: string; impact_zh: string; blocks: string[]; source_table?: string }
/** 参数与版本条目 */
export interface ParamItem { label_zh: string; value: unknown; origin: 'recorded' | 'outline' | 'decision' | 'run_config' | string }
/** 复核记录 */
export interface ReviewRecord {
  review_id: string;
  decision: Decision;
  reviewer: string;
  note: string;
  created_at: string;
  batch: unknown;
  previous_review_id?: string | null;
}
/** 模块复核信息 */
export interface ReviewInfo {
  current: ReviewRecord | null;
  history: ReviewRecord[];
  can_review: boolean;
  allowed_decisions: Decision[];
  blocked_reason_zh: string | null;
  expected_review_id: string | null;
  run_id: string | null;
  batch_with: string | null;
  continue: { available: boolean; note_zh: string };
  already_approved: boolean;
}
/** 归档文件 */
export interface FileItem { key: string; role: string; name: string; path: string; bytes: number | null; sha256: string | null; inline: boolean }
/** 可分页明细表的索引 */
export interface TableIndex { name: string; kind: 'rows' | 'object'; row_count: number | null; columns: string[] }
/** 运行历史条目 */
export interface RunItem {
  run_id: string;
  order_zh: string;
  created_at: string | null;
  reason_zh: string | null;
  outcome: string | null;
  review_decision: Decision | null;
  is_current: boolean;
}

/** A06 热图 */
export interface Heatmap {
  unit: string;
  orientation: string;
  color_rule_zh: string;
  min: number;
  max: number;
  receptors: { name: string; order: number; pdb: string | null; rmsd: number | null; status_zh: string; role_zh: string }[];
  rows: { compound_id: string; compound_name: string; cells: { receptor: string; value: number | null }[] }[];
  omitted: { kind: string; name: string; reason_zh: string }[];
}
/** A05 富集前列条目 */
export interface EnrichItem { id: string; description: string; count: number; gene_ratio: string; p_adjust: number; rich_factor: number }
/** A04 第一轮前 10 */
export interface PpiTopItem { symbol: string; degree: number; bc: number; cc: number; round2: boolean; bar: number }
/** A03 韦恩图 */
export interface Venn { formula_only: number; both: number; disease_only: number; formula_total: number; disease_total: number }
/** A07 研究线索 */
export interface Lead { title_zh: string; fact_zh: string; next_zh: string }
/** A07 报告文件 */
export interface ReportFile { role: string; label_zh: string; key: string | null; path: string; sha256: string }
/** A07 纳入通路 */
export interface PathwayItem { id: string; name_zh: string; status_zh: string; hits: number }

/** 分库资料入口；格式与当前版本由后端确定。 */
export interface SourceUploadInfo {
  enabled: boolean; disabled_reason_zh: string;
  expected_a00: string; expected_run: string; expected_staging: string;
  note_zh: string; can_process: boolean; process_reason_zh: string; query_zh: string;
  sources: SourceUploadItem[];
}
export interface SourceUploadItem {
  database: string; label_zh: string; status_zh: string; hint_zh: string;
  uploaded_name: string | null; sha256: string | null; download_url: string | null;
  formats: { value: string; label_zh: string; accept: string; template_url: string }[];
}

/** 模块专属数据（第 6 节）；各模块只有其中一部分键 */
export interface Special {
  venn?: Venn;
  component_top?: { compound_id: string; name: string; herbs: string; main_rank: number; intersection_count: number; mixed_degree: number }[];
  component_top_note_zh?: string;
  ppi_top?: PpiTopItem[];
  ppi_dual?: PpiDual;
  ppi_identity?: PpiIdentity;

  enrichment_top?: Record<string, EnrichItem[]>;
  enrichment_display_tables?: Record<string, EnrichmentCatalogRow[]>;
  enrichment_graphs?: Partial<Record<'go' | 'kegg', { url: string; caption_zh: string }>>;
  heatmap?: Heatmap;
  conclusion_zh?: string;
  leads?: Lead[];
  limits?: string[];
  pathway?: PathwayItem[];
  report_files?: ReportFile[];
}

/** 模块页 */
export interface ModuleView {
  docking_review?:DockingReviewInfo|null;
  compound_selection?:CompoundSelectionInfo|null;
  docking_preparation?:DockingPreparationInfo|null;
  docking_candidates?: DockingCandidatesInfo | null;
  module: { module_id: string; title_zh: string; group_zh: string; purpose_zh: string; sub: boolean; depends_on: string[] };
  state: { code: StateCode; label_zh: string; reason_zh: string | null; raw_state: string; is_empty_result: boolean; handoff_blocked: boolean; can_review: boolean };
  purpose: Purpose | null;
  run: {
    run_id: string; artifact_id: string | null; order_zh: string; created_at: string | null; finished_at: string | null;
    reason_zh: string | null; parent_runs: Record<string, string>; is_current: boolean; is_active: boolean;
  } | null;
  outcome: 'success' | 'empty' | 'failed' | 'partial' | null;
  kpis: Kpi[];
  flow: FlowStep[];
  flow_note_zh: string;
  focus: FocusItem[];
  params: ParamItem[];
  table: { columns: { key: string; label_zh: string }[]; rows: Record<string, unknown>[]; row_count: number; source_table: string | null } | null;
  special: Special;
  review: ReviewInfo;
  downstream: { note_zh: string; modules: { module_id: string; title_zh: string; code: StateCode; label_zh: string }[] };
  trace: { label_zh: string; value: unknown }[];
  files: FileItem[];
  tables: TableIndex[];
  history: RunItem[];
  tasks: Task[];
  historical: boolean;
  source_uploads?: SourceUploadInfo | null;
  ppi_run?: PpiRunInfo | null;
  identity_plan?: IdentityPlanInfo | null;
  enrichment_display?: EnrichmentDisplayInfo | null;
}

/** 明细表分页返回 */
export type TablePage =
  | { kind: 'rows'; name?: string; columns: string[]; total: number; page: number; size: number; items: Record<string, unknown>[] }
  | { kind: 'object'; name?: string; data: unknown };

/** 复核提交的返回 */
export interface ReviewResponse { review: ReviewRecord; task: Task | null; message_zh: string }
/** 批量复核的返回 */
export interface BatchReviewResponse { reviews: unknown; task: Task | null; message_zh: string }

/** 双分支第二轮归档排名，网页不重新计算名次 */
export interface PpiDualRow { target_id: string; symbol: string; degree: number; bc: number; cc: number; rank: number; bc_rank?: number; cc_rank?: number; mean_rank?: number }
export interface PpiDual { network_round?: 1 | 2; degree_round?: 1 | 2; network?: { url: string; caption_zh: string } | null; version: string; counts: Record<string, number>; thresholds: Record<string, unknown>[]; degree_rows: PpiDualRow[]; bc_cc_rows: PpiDualRow[]; note_zh: string; network_note_zh: string }

// A04专用任务由后端核验研究和上游版本，网页只显示和传回绑定。
export interface PpiRunInfo { enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a04: string }

// 只读待核验身份，显示归档原值；不提供代签或自动身份替换。
export interface PpiIdentityRow { target_id: string; symbol: string; returned: string; reason_zh: string }
export interface PpiIdentity { total: number; source_table: string; note_zh: string; rows: PpiIdentityRow[] }

// 保存的是人工补查方案；身份与模块是否可通过仍由科学归档和Workflow决定。
export interface IdentityPlanInfo { enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a04: string; expected_decision_id: string | null; latest: { decision_id: string; reviewer: string; note_zh: string; created_at: string; check_ids: string[]; omit_ids: string[]; applied_run_id: string | null; pending_count: number | null; evidence_url?: string | null; error_zh?: string; status_zh: string } | null }
// A05确认绑定研究运行；候选、排名和是否可写均来自归档接口。
export interface EnrichmentCatalogRow { ID: string; Description: string; description_zh: string; translation_status: string; Count: number; 'p.adjust': number; RichFactor: number; gene_symbols: string; proposed?: boolean; reason_zh?: string; evidence_url?: string }
export interface EnrichmentDisplayInfo { kegg_ready: boolean; kegg_reason_zh: string; enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a05: string; expected_decision_id: string | null; exclusions_confirmed: boolean; layout_confirmed: boolean; excluded_ids: string[]; missing_translations: string[]; catalog: EnrichmentCatalogRow[]; retained_count: number; excluded_count: number; significant_count: number; latest: { reviewer: string; note_zh: string; created_at: string; applied: boolean; status_zh: string } | null }
export interface EnrichmentDisplayRequest { expected_a03: string; expected_a05: string; expected_decision_id: string | null; action: 'exclusions' | 'layout'; reviewer: string; note: string; excluded_ids: string[]; confirmed: true }

export interface IdentityPlanRequest { expected_a03: string; expected_a04: string; expected_decision_id: string | null; reviewer: string; note: string; check_ids: string[]; omit_ids: string[]; confirmed: true }

// 两梯队名单只读后台归档，前端不自行相交或排名。
export interface DockingCandidateRow {
  target_id: string; symbol: string; degree: number; bc: number; cc: number; evidence_group?: 'A' | 'B';
}
export interface DockingCandidatesInfo {
  enabled: boolean; disabled_reason_zh: string;
  expected_a03: string; expected_a04: string; expected_a04_review: string;
  preparation_note_zh: string;
  data: null | { group_id: string; rule_zh: string; note_zh: string;
    source_runs: { A03: string; A04: string }; group_a: DockingCandidateRow[]; group_b: DockingCandidateRow[];
    counts: { a: number; b: number; degree_top10: number; bc_cc_top15: number; degree_top15: number };
  };
}

/** 对接成分选择与两遍方案来自后端，字段完整不表示质控已通过。 */
export interface CompoundChoiceRow { compound_id:string; name:string; herbs:string[]|string; intersection_count:number; main_rank:number; eligible:boolean; suggestion_zh:string }
export interface CompoundSelectionInfo { enabled:boolean; disabled_reason_zh:string; expected_a03:string; expected_select:string; rows:CompoundChoiceRow[]; current_selected:string[]; previous_rows:CompoundChoiceRow[]; previous_active:boolean; rule_zh:string }
export interface StructureSpec { source_type:'experimental'|'alphafold'; uniprot:string; chains:string[]; pocket:'reference'|'p2rank'; pdb_id?:string; model_id?:string; sequence_start?:number; sequence_end?:number; altloc?:string|null; reference_code?:string; reference_chain?:string; reference_sequence?:string }
export interface TwoPassRow {target_id:string;symbol:string;candidate_grade:string;first:StructureSpec|null;first_reason:string;second:StructureSpec|null;second_reason:string;unavailable:boolean;reason:string}
export interface TwoPassCompound {compound_id:string;status:'use'|'unavailable'|null;cid?:string;reason:string;protonation_policy?:string;material_id?:string}
export interface TwoPassPlan {policy_version:string;package_id:string;pymol_executable:string;compounds:TwoPassCompound[];receptors:TwoPassRow[]}
export interface PlanRowCheck {target_id:string;valid:boolean;bulk_allowed:boolean;reason_zh:string}
export interface DockingMaterial {material_id:string;compound_id:string;cid:string;name:string;state_zh:string}
export interface DockingPreparationInfo {enabled:boolean;disabled_reason_zh:string;expected_source:string;expected_plan_id:string|null;policy_version:string;plan:TwoPassPlan;checks:PlanRowCheck[];materials:DockingMaterial[];context:{receptors:DockingCandidateRow[];compounds:{compound_id:string;name:string;herbs:string[]}[]};planned_pair_count:number;execution_allowed:false;status_zh:string;latest?:{reviewer:string;note:string;created_at:string}|null}

// 研究核查草案与同批矩阵只读，身份预核查不代替人工确认。
export interface DockingReviewCompound extends CompoundChoiceRow {name_zh:string;cid:string;identity_prechecked:boolean;identity_state_zh:string;source_3d_state_zh:string;evidence_zh:string;manual_reason_zh:string}
export interface DockingMatrixCell {compound_id:string;target_id:string;state:string;score:number|null;reason_zh:string;color:string;text_color:string}
export interface DockingMatrixSlice {rows:DockingReviewCompound[];columns:(DockingCandidateRow&{candidate_grade:string;quality_zh:string})[];cells:DockingMatrixCell[][]}
export interface DockingMatrixInfo {ready:boolean;status_zh:string;full_pair_count:number;score_range:[number|null,number|null]|null;result_version:string|null;heatmap:DockingMatrixSlice;table:DockingMatrixSlice}
export interface DockingReviewInfo {enabled:boolean;reason_zh:string;review_id:string|null;proposal:{acetic_trace?:SourceIdentityTrace;compounds:DockingReviewCompound[];excluded:{compound_id:string;name_zh:string;reason_zh:string}[];note_zh:string;receptors:DockingCandidateRow[]}|null;matrix:DockingMatrixInfo|null}

// 来源冲突追溯只读；计数及逐行映射来自归档，不在网页重新归属靶点。
export interface SourceIdentityTrace {bulk:Record<string,string>;detail:Record<string,string>;official:{cid:string;url:string;properties:{MolecularFormula:string;InChIKey:string}}[];raw_rows:number;normalized_rows:number;unique_targets:number;intersection_targets:number;outside_intersection:number;trace:{source_row:number;raw_target_id:string;raw_symbol:string;database_source_titles:string[];target_id:string;symbol:string;in_current_intersection:boolean}[];live_confirmation?:{same_as_archived:boolean;cas_query_cid:number}}
