// 文件用途：本机接口（/api/v1）返回数据的 TypeScript 类型；字段与 src/modulea/api/AGENTS.md 契约一一对应。
// 改字段前先改契约文件，再改这里；前端不自行推算状态。

/** 新研究的明确登记；物种、范围及核对证据由服务端生成。 */
export interface NewStudyInput {
  request_id: string;
  formula: string;
  herbs: string;
  disease: string;
  mesh_term: string;
  mesh_id: string;
  operator: string;
  analysis_purpose: 'formal_research' | 'workflow_test';
}
export interface CreatedStudy {
  study_id: string;
  run_id: string;
  created: boolean;
  directory: string;
  message_zh: string;
}
export interface ProjectStorage {
  directory: string;
  folders: { name: string; label_zh: string }[];
}

/** 独立参数预览仅读目录并调用原校验器，不提供研究执行。 */
export type PlanValue = string | number | boolean;
export interface AnalysisParameter {
  label: string; default: PlanValue; type: 'number' | 'integer' | 'boolean' | 'enum';
  unit?: string; min?: number; min_exclusive?: number; max?: number; resolution?: number;
  choices?: (string | number)[]; active_when?: Record<string, PlanValue>;
}
export interface CompiledAnalysisPlan {
  schema_version: string; mode: 'standard' | 'personalized'; parameters: Record<string, PlanValue>;
  fixed: Record<string, unknown>; parameter_hash: string;
  warnings: { code: string; message_zh: string }[];
}
export interface AnalysisParameterCatalog {
  schema_version: string; parameters: Record<string, AnalysisParameter>; fixed: Record<string, unknown>;
  execution_ready: boolean; message_zh: string;
  preview: {
    version: string; preview_only: true; message_zh: string;
    groups: {key: string; title_zh: string; stage_zh: string; status: string; status_zh: string;
      description_zh: string; fields: string[]; advanced_fields: string[]}[];
    details: Record<string, {help_zh: string; choices_zh?: Record<string, string>}>;
    source_rules: {name: string; rule_zh: string}[]; fixed_rules_zh: string[];
  };
}
export interface AnalysisPlanValidation { plan: CompiledAnalysisPlan; impact: unknown; execution_available: false }

/** 新模式建档只固定初始方案和资料预检，不授权自动执行。 */
export interface CreationMaterials {
  references:{id:string;label_zh:string;status:string;filename:string;sha256:string|null;bytes:number|null;detail_zh:string}[];
  references_verified:boolean;research_sources:{database:string;status:string;reason_zh:string}[];
  execution_available:false;reason_zh:string;
}
export interface PlanA01Info {
  supported:boolean;protocol_version:string;acquire_enabled:boolean;publish_enabled:boolean;
  acquire_blockers:string[];publish_blockers:string[];expected_a00:string;expected_a01:string;
  expected_plan_id:string;expected_staging:string;parameter_hash:string;
  parameters:{ob_min:number|null;dl_min:number|null};missing_databases:string[];processed:boolean;message_zh:string;
}
export interface PlanA05Info {
  supported:boolean;enabled:boolean;blockers:string[];protocol_version:string;completed:boolean;applicable:boolean;
  expected_a00:string;expected_a03:string;expected_a05:string;expected_plan_id:string;parameter_hash:string;message_zh:string;
  parameters:{include_go?:boolean;include_kegg?:boolean;adjusted_p_max?:number;min_term_size?:number;max_term_size?:number;
    go_plot_top?:number;go_table_top?:number;kegg_plot_top?:number;kegg_table_top?:number};
}
export interface PlanA05DisplayChoice {ID:string;decision:'retain'|'exclude'|'defer';reason:string}
export interface PlanA05Translation {ID:string;english:string;zh:string;reason:string}
export interface PlanA05DisplayDecision {excluded_ids:string[];uncertain_decisions:PlanA05DisplayChoice[];translations:PlanA05Translation[];confirmed:true}
export interface PlanA05DisplayRow extends Record<string,unknown> {
 ID:string;Description:string;english:string;Count:number;'p.adjust':number;description_zh:string;translation_status:string;
 classification_status?:string;classification_zh?:string;reason_zh?:string;proposed_exclusion?:boolean;
 excluded?:boolean;deferred?:boolean;decision?:PlanA05DisplayChoice|null;
}
export interface PlanA05DisplayInfo {
 supported:boolean;enabled:boolean;blockers:string[];expected_a05:string;expected_display_id:string;expected_input_hash:string;
 plan_id:string;parameter_hash:string;parameters:Record<string,number|boolean>;message_zh:string;
 current:null|{display_id:string;a05_run_id:string;decision:PlanA05DisplayDecision|null;
   downloads:{index:number;name:string;url:string}[];
   presentation:{tables:Record<string,PlanA05DisplayRow[]>;missing_translations:string[];unresolved_classifications:string[];
     excluded_ids:string[];deferred_ids:string[];decisions_confirmed:boolean;ready_for_display:boolean;scientific_approval:false;note_zh:string;
     groups:{group:string;included:boolean;significant_count:number|null;retained_count:number|null;plot_count:number|null;table_count:number|null}[]}};
}
export interface PlanSystemValidationReceipt {
 validation_id:string;module_id:string;run_id:string;passed:boolean;label_zh:string;created_at:string;error_zh:string|null;
 scientific_status:{result_outcome:string;handoff_blocked:boolean;ready_for_successor:boolean;note_zh:string};
}
export interface PlanSystemValidationsInfo {
 supported:boolean;message_zh:string;history:PlanSystemValidationReceipt[];
 items:{module_id:string;run_id:string;enabled:boolean;blockers:string[];
  request:null|{expected_run_id:string;expected_input_hash:string};current:PlanSystemValidationReceipt|null}[];
}
export interface PlanReportsInfo {
 supported:boolean;enabled:boolean;blockers:string[];expected_report_run_id:string|null;expected_input_hash:string;message_zh:string;
 history:{run_id:string;created_at:string;active:boolean;approved:boolean;status_zh:string;
   downloads:{label_zh:string;name:string;url:string}[]}[];
}
export interface PlanStagesInfo {
  plan_mode?: 'standard' | 'personalized' | null;
 schema_version:string;supported:boolean;expected_input_hash:string;expected_a00:string;expected_plan_id:string;parameter_hash:string;
 parameters:Record<string,unknown>;stages:{stage:string;enabled:boolean;blockers:string[];current_run:string|null;active:boolean;approved:boolean}[];message_zh:string;
}
export interface PlanCompoundRow {
 compound_id:string;name:string;herbs:string|string[];intersection_count:number;mixed_degree:number;in_network:boolean;
 selection_score?:number;selection_role?:string;
}
export interface PlanCompoundsInfo {
 supported:boolean;enabled:boolean;blockers:string[];expected_a00:string;expected_a03:string;expected_selection:string;
 expected_plan_id:string;expected_input_hash:string;parameter_hash:string;target_count:number|null;metric:string|null;
 ranking:PlanCompoundRow[];identity_pending:string[];current:boolean;current_summary:Record<string,unknown>|null;
 current_selected:PlanCompoundRow[];message_zh:string;
}
export interface PlanSelectionUiInfo {
 supported:boolean;input_hash:string;expected_a00:string;expected_a03:string;expected_a03_select:string;expected_a04:string;
 expected_plan_id:string;parameter_hash:string;parameters:Record<string,unknown>;newer_draft:boolean;
 selection:{selection_id:string;plan_id:string;selection:{mode:string;requested_count:number;actual_count:number;
  selected:{target_id:string;symbol:string;degree:number;bc:number;cc:number;selection_order:number;candidate_grade:string|null}[]}}|null;
 selection_review:{review_id:string;decision:Decision;reviewer:string;note:string}|null;
 current_input:{input_id:string;packet:{pair_count:number;compounds:{compound_id:string;name:string}[];receptors:{target_id:string;symbol:string}[]}}|null;
 operations:Record<'selection'|'review'|'input',{enabled:boolean;blockers:string[]}>;message_zh:string;
}
export interface PlanPreparationUiInfo {
 supported:boolean;enabled:boolean;blockers:string[];input_hash:string;expected_input_id:string;
 expected_preparation_run_id:string|null;parameters:Record<string,unknown>;message_zh:string;
 scope:{pair_count:number;compounds:{compound_id:string;name:string}[];receptors:{target_id:string;symbol:string}[]}|null;
 current:{run_id:string;version:string;active:boolean;matches_input:boolean;completed:boolean;approved:boolean;
  summary:Record<string,unknown>|null}|null;
 steps:{key:string;label:string;available:boolean;module:string;target:string;detail_zh:string}[];
}
export interface PlanCreationPreflight {
  schema_version:string;preflight_id:string;input_hash:string;plan:CompiledAnalysisPlan;
  mesh_verification:{preferred_term:string;mesh_id:string;status:string};materials:CreationMaterials;
  expires_at:string;can_create:boolean;execution_available:false;message_zh:string;
}
export interface CreatedPlanStudy extends CreatedStudy {plan_id:string;mode:'standard'|'personalized';parameter_hash:string;execution_available:false}
export interface CreationPlanInfo {
  schema_version:string;initial_plan_id:string;initial_a00_run_id:string;initial_plan:CompiledAnalysisPlan;
  current_plan_id:string|null;current_plan:CompiledAnalysisPlan|null;materials_at_creation:CreationMaterials;
  preflight_id:string;execution_available:false;reason_zh:string;
}

/** 研究级只读追溯摘要；完整结果通过页面上的显式导出下载。 */
export interface TraceModuleSummary {
  module_id: string;
  label_zh: string;
  run_id: string | null;
  state: string;
  result: { outcome?: string | null; summary?: Record<string, unknown>; anomalies?: unknown[]; table_names?: string[] } | null;
  table_names: string[];
}
export interface TraceSummary {
  trace_version: string;
  study_id: string;
  workflow_profile: string | null;
  current: Record<string, string | null>;
  modules: TraceModuleSummary[];
  plans: { plan_id: string | null; state: string | null; created_at: string | null }[];
  file_count: number;
  read_only: true;
  export_json_url: string;
  export_csv_url: string;
  message_zh: string;
}

/** 状态码：与契约第 2 节一致 */
export type StateCode =
  | 'idle' | 'ready' | 'running' | 'incomplete' | 'failed' | 'waiting' | 'empty'
  | 'review' | 'hold' | 'returned' | 'approved' | 'stale' | 'published' | 'unavailable' | 'history' | 'scope_confirmed' | 'prepared' | 'execution_confirmed';

/** 复核决定的三种取值 */
export type Decision = 'approved' | 'rejected' | 'pending';

/** 接口错误正文 */
export interface ApiErrorBody {
  error: { code: string; message_zh: string; details: Record<string, unknown>; retryable: boolean };
}

/** 三库原件获取：显示服务端事实，原确认只在用户明确点击重试时提交。 */
export interface SystemAcquisitionRequest {
 request_id:string;expected_a00:string;expected_plan_id:string;expected_input_hash:string;author:string;note:string;confirmed:true;
}
/** 新登记受限原件只暂存，GET不解析、不启动任务或确认登记。 */
export interface SystemDiseaseManualSourcesInfo {
 supported:boolean;enabled:boolean;blockers:string[];busy:boolean;expected_a00:string|null;expected_plan_id:string|null;expected_input_hash:string|null;
 disease_identity_zh:string;message_zh:string;formats:Record<string,string[]>;
 sources:{database:string;name:string;query:string;retrieved_at:string;version:string;format:string;bytes:number;sha256:string;status_zh:string}[];
}
/** 疾病五库原件资格与逐库事实，不把缺失或查询失败显示为0。 */
export interface SystemDiseaseAcquisitionInfo {
  historical_candidate?:{run_id:string;candidate_records:number|null;source_limitations_zh:string[];message_zh:string};
 supported:boolean;enabled:boolean;blockers:string[];busy:boolean;expected_a00:string|null;expected_plan_id:string|null;expected_input_hash:string;
 disease_identity_zh:string;automatic_databases:string[];manual_databases:string[];message_zh:string;
 requests:{request_id:string;request:SystemAcquisitionRequest;plan_id:string;created_at:string;state:string;state_label_zh:string;
  retry_enabled:boolean;retry_blockers:string[];message_zh:string;
  publication?:{enabled:boolean;blockers:string[];published_run_id:string|null;candidate_count_text_zh:string;message_zh:string;
   request:Pick<SystemSourceBindingRequest,'expected_acquisition_request_id'|'expected_record_sha256'|'expected_input_hash'>|null};
  display_sources:{database:string;state:string;state_label_zh:string;records_text_zh:string;reason_zh:string}[]}[];
}

/** 独立科学输入绑定的实际预期字段，不接受浏览器路径或参数覆盖。 */
export interface SystemSourceBindingRequest {
 request_id:string;expected_acquisition_request_id:string;expected_record_sha256:string;expected_input_hash:string;
 author:string;note:string;confirmed:true;
}
export interface SystemAcquisitionInfo {
 supported:boolean;enabled:boolean;blockers:string[];busy:boolean;expected_a00:string|null;expected_plan_id:string|null;expected_input_hash:string;
 screening_parameters:{ob_min:number;dl_min:number}|null;message_zh:string;
 requests:{request_id:string;request:SystemAcquisitionRequest;plan_id:string;created_at:string;state:string;state_label_zh:string;
  screening_parameters:{ob_min:number;dl_min:number};display_sources:{database:string;state_label_zh:string;reason_zh:string}[];
  retry_enabled:boolean;retry_blockers:string[];message_zh:string;record_count:number;failure_count:number;source_receipt_count:number;
  binding?:{enabled:boolean;blockers:string[];bound:boolean;request:Pick<SystemSourceBindingRequest,'expected_acquisition_request_id'|'expected_record_sha256'|'expected_input_hash'>|null}}[];
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
  progress: { approved: number; completed?: number; scope_confirmed?: number; total: number; segments: { module_id: string; code: StateCode; label_zh: string }[] };
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
/** 同页读取仍返回原研究及模块；模块错误单独呈现，不能误报研究不存在。 */
export interface WorkspaceView {
  study: StudyView;
  module: ModuleView | null;
  module_error: (ApiErrorBody['error'] & { status: number }) | null;
}

/** 只用于首屏，归档状态、操作权限和结果仍来自 WorkspaceView。 */
export interface StudyOpening {
  study: StudyInfo;
  nav: { group_zh: string; modules: Pick<NavModule, 'module_id' | 'title_zh' | 'sub'>[] }[];
}

export interface StudyView {
  storage?: ProjectStorage;
  study: StudyInfo;
  purpose: Purpose | null;
  archive_ok: boolean;
  archive_error_zh: string | null;
  progress: { approved: number; completed?: number; scope_confirmed?: number; total: number };
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
  review_at_intersection?: boolean;
  parallel_after_approval?: boolean;
  current: ReviewRecord | null;
  history: ReviewRecord[];
  can_review: boolean;
  allowed_decisions: Decision[];
  blocked_reason_zh: string | null;
  blockers?: ReviewBlocker[];
  expected_review_id: string | null;
  run_id: string | null;
  batch_with: string | null;
  continue: { available: boolean; note_zh: string };
  already_approved: boolean;
}
/** 归档文件 */
export interface FileItem { key: string; role: string; name: string; path: string; bytes: number | null; sha256: string | null; inline: boolean }

/** 同版本对接出图包与用户回传图片，资格及数量均由后端提供。 */
export interface DrawingPair {
  compound_name_en?: string;
  pair_key: string; compound_id: string; compound_name_zh: string; target_id: string; target_zh: string;
  score: number | null; eligible: boolean; package_url: string | null;
}
export interface DockingArtifactInfo {
  enabled: boolean; disabled_reason_zh: string; expected_a06: string; eligible_count: number; ready_count: number;
  pairs: DrawingPair[];
  images: {artifact_id: string; name_zh: string; caption_zh: string; pair_key: string; created_at: string; url: string; width: number; height: number}[];
  bundles: {artifact_id: string; name_zh: string; url: string; pair_keys: string[]}[];
}
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
  receptors: { name: string; display_name?: string; order: number; pdb: string | null; rmsd: number | null; status_zh: string; role_zh: string }[];
  rows: { compound_id: string; compound_name: string; cells: { receptor: string; value: number | null }[] }[];
  omitted: { kind: string; name: string; reason_zh: string }[];
}
/** A05 富集前列条目 */
export interface EnrichItem { id: string; description: string; count: number; gene_ratio: string; p_adjust: number; rich_factor: number }
/** A04 第一轮前 10 */
export interface PpiTopItem { symbol: string; degree: number; bc: number; cc: number; round2: boolean; bar: number }
/** A03 韦恩图 */
export interface Venn { formula_only: number; both: number; disease_only: number; formula_total: number; disease_total: number; layout?: 'overlap' | 'disjoint' | 'empty_formula' | 'empty_disease' | 'empty_both' }
/** A07 研究线索 */
export interface Lead { title_zh: string; fact_zh: string; next_zh: string }
/** A07 报告文件 */
export interface ReportFile { role: string; label_zh: string; key: string | null; path: string; sha256: string }
/** A07 纳入通路 */
export interface PathwayItem { id: string; name_zh: string; status_zh: string; hits: number }

/** 分库资料入口；格式与当前版本由后端确定。 */
export interface SourceUploadInfo {
  plan_managed?:boolean;
  enabled: boolean; disabled_reason_zh: string;
  expected_a00: string; expected_run: string; expected_staging: string;
  note_zh: string; can_process: boolean; process_reason_zh: string; query_zh: string;
  sources: SourceUploadItem[];
  acquisition?: {enabled: boolean; databases: string[]; latest: SourcePreviewSummary | null} | null;
  mapping_preview?: {enabled: boolean; latest: SourcePreviewSummary | null} | null;
  verification?: {enabled: boolean; version: string; coverage: {database: string; herb: string; records: number; complete: boolean; availability: string; basis: string}[]; issues_count: number} | null;
}
export interface SourcePreviewSummary {preview_id: string; databases: {database: string; status: string; status_zh?: string; message_zh?: string; error_zh?: string; candidates_count?: number}[]}
export interface DiseaseCandidate {candidate_id: string; disease_id: string; disease_name: string; reason_zh: string; records_count: number | null; source_url: string; scope: string; source_rows: string[]; direct_gene_eligible: boolean}
export interface DiseaseCandidatePage {preview_id: string; database: string; status_zh: string; error_zh?: string; total: number; page: number; size: number; items: DiseaseCandidate[]; current: boolean; note_zh: string}
export interface SourceUploadItem {
  can_retry?: boolean; // 由后端判断当前失败来源可否重取
  database: string; label_zh: string; status_zh: string; hint_zh: string;
  uploaded_name: string | null; sha256: string | null; download_url: string | null;
  formats: { value: string; label_zh: string; accept: string; template_url: string }[];
}

/** 模块专属数据（第 6 节）；各模块只有其中一部分键 */
/** 已归档准备依据和原始Top-1只读关联；不提供科研采用或确认操作。 */
export interface FoundationEvidence {
  schema_version:string;read_only:true;integrity:'verified'|'failed';message_zh:string;error_zh:string;
  study_id?:string;run_id?:string;input_key?:string;
  preparation:{target_id:string;symbol:string;attempt:number;structure_id:string|null;state:string;state_zh:string;
    quality:string|null;reason_zh:string;attempt_reason_zh:string;chains:string[]|null;uniprot:string|null;
    reference:Record<string,string>|null;reference_contacts?:{chains:string[];basis_zh:string}|null;pocket_method:string|null;top1_rmsd:number|null;
    pocket_complete_zh:string;environment_resolved_zh:string;environment_note_zh:string;
    missing_atoms_zh:string[]|null;unobserved_residues_zh:string[]|null;environment_components_zh:string[]|null;
    box:{center:number[];size:number[]}|null;downloads:{label_zh:string;name:string;url:string;sha256:string}[]}[];
  scores:{compound_id:string;compound_name:string;target_id:string;symbol:string;state:string;state_zh:string;score:number|null;
    quality:string|null;reason_zh:string;top_mode:number|null;pose_sha256:string|null;
    box:{center:number[];size:number[]}|null;top1_download_url?:string;context_download_url?:string;
    downloads:{label_zh:string;name:string;url:string;sha256:string}[]}[];
}

export interface Special {
  native_scores?:NativeScoreDisplay;
  system_rescue?:SystemRescueDisplay;
  rescue_presentation?:RescuePresentationBootstrap;
  foundation_evidence?:FoundationEvidence;
  source_diagnostics?:{object_type?:string;object_id?:string;failure_stage?:string;failure_code?:string;retryable?:boolean;reason_zh?:string}[];
  historical_disease_source?:{message_zh:string};
  system_component_publication?: {source_binding_protocol:string;message_zh:string;identity_tools_available:boolean};
  venn?: Venn;
  component_top?: { compound_id: string; name: string; herbs: string; main_rank: number; intersection_count: number; mixed_degree: number }[];
  component_top_note_zh?: string;
  ppi_top?: PpiTopItem[];
  ppi_dual?: PpiDual;
  ppi_identity?: PpiIdentity;

  enrichment_top?: Record<string, EnrichItem[]>;
  plan_enrichment?:{groups:{group:string;included:boolean;state_zh:string}[];tables:Record<string,Record<string,unknown>[]>;threshold_zh:string;note_zh:string};
  enrichment_display_tables?: Record<string, EnrichmentCatalogRow[]>;
  enrichment_graphs?: Partial<Record<'go' | 'kegg', { url: string; caption_zh: string }>>;
  heatmap?: Heatmap;
  conclusion_zh?: string;
  leads?: Lead[];
  limits?: string[];
  pathway?: PathwayItem[];
  report_files?: ReportFile[];
}

/** 同批受体补救展示；原值、颜色、原因与可下载证据均由后端给出。 */
export interface RescueDownload {label_zh:string;name:string;url:string;sha256:string;bytes?:number}
export interface RescueCell {
  compound_id:string;target_id:string;score:number|null;score_text:string;display_score:string;
  state:string;state_zh:string;quality:string;reason_zh:string;source_kind:string;source_zh:string;
  color:string;text_color:string;downloads:RescueDownload[];evidence_url?:string;
}
export interface RescueMatrix {
  rows:{compound_id:string;name:string;name_en:string;name_zh:string;label:string;name_scope?:string;name_scope_note_zh?:string}[];
  columns:{target_id:string;symbol:string;label:string;quality:string;candidate_grade:string}[];
  cells:RescueCell[][];
}
export interface SystemRescueDisplay {
  input_key?:string;focus_url?:string;acceptance_url?:string;presentation_url?:string;
  presentation_revision?:RescuePresentationRevision;
  schema_version:'A06.system_rescue.display.1'|'A06.system_rescue.display.2'|'A06.system_rescue.display.3';
  science_version:'A06.system_rescue.1'|'A06.system_rescue.2';read_only:true;study_id:string;run_id:string;unit:string;
  score_range:[number|null,number|null];colour_note_zh:string;scope_note_zh:string;review_note_zh:string;
  summary_rows:{label_zh:string;text:string}[];table:RescueMatrix;heatmap:RescueMatrix;
  initial_focus:{compound_ids:string[];target_ids:string[]};downloads:RescueDownload[];
  figures:(RescueDownload&{image_url:string;role:string})[];
  receptor_preparation:{target_id:string;symbol?:string;state:string;state_zh:string;quality?:string;reason_zh?:string}[];
}

/** 原生评分复用同一矩阵形状，独立版本，不冒充旧Windows补救结果。 */
export type NativeScoreDisplay=Omit<SystemRescueDisplay,'schema_version'|'science_version'|'summary_rows'|'receptor_preparation'> & {
  schema_version:'A06.platform_display.1';science_version:'A06.platform_execution.1';
};

/** 只读组合证据；区域选择和失败事实全部由后端提供。 */
export interface RescueEvidence {
  schema_version:'ModuleA.rescue_evidence.1';read_only:true;study_id:string;run_id:string;input_key:string;
  compound_id:string;target_id:string;state:string;score:number|null;source_zh:string;region_note_zh:string;
  regions:{region_id:string;state:string;state_zh:string;score:number|null;reason_zh:string;
    selected:boolean;downloads:RescueDownload[]}[];
  context:Record<string,unknown>;downloads:RescueDownload[];
}

/** 准备、组合和区域分别计数；未知总量保持null，不由前端补算。 */
export interface ScientificProgress {
  supported:boolean;available:boolean;message_zh:string;run_id?:string;updated_at?:string;
  current_object_zh?:string;estimate_seconds?:number|null;estimate_note_zh?:string;region_total_note_zh?:string;
  preparation?:ScientificCounts;pairs?:ScientificCounts;regions?:ScientificCounts;
}
export interface ScientificCounts {
  total:number|null;completed:number;reused:number;new:number;succeeded:number;failed:number;pending:number|null;na?:number;
}

/** 本平台各阶段资格与固定输入由后端提供，客户端仅记录明确选择。 */
export interface NativeComputeInfo {
  supported:boolean;protocol:string;notice_zh:string;
  stages:{key:'prepare'|'qualify'|'score';label_zh:string;enabled:boolean;blockers_zh:string[];resumable:boolean;
    request_template:Record<string,unknown>}[];
  pockets:{target_id:string;symbol:string;state:string;reason_zh:string;
    options:{pocket_key:string;eligible:boolean;pdb_id?:string;reason_zh:string}[]}[];
}

export interface AcceptanceBundle {
  schema_version:'ModuleA.acceptance_bundle.1';study_id:string;run_id:string;input_key:string;
  enabled:boolean;blockers_zh:string[];translation_missing_ids:string[];download_url:string;note_zh:string;
  files:{path:string;sha256:string;bytes:number}[];
  presentation_revision?:RescuePresentationRevision;
  archive_url?:string;archive_required?:boolean;registered_source_bytes?:number;
}

/** 完整包与图表回执分别绑定，下载URL携带两份SHA，不在前端计算科研状态。 */
export interface RescueAcceptanceArchiveItem {
  archive_id:string;receipt_sha256:string;archive_sha256:string;bytes:number;created_at:string;
  matches_input:boolean;download_url:string;
}
export interface RescueAcceptanceArchiveDirectory {
  run_id:string;revision_id:string;input_key:string;receipt_sha256:string;matches_input:boolean;
  enabled:boolean;blockers_zh:string[];expected_input_hash:string|null;required_source_bytes:number|null;
  current:RescueAcceptanceArchiveItem|null;history:RescueAcceptanceArchiveItem[];generate_url:string;read_only:true;
}
export interface RescueAcceptanceArchiveRequest {
  request_id:string;expected_run_id:string;expected_revision_id:string;expected_revision_sha256:string;
  expected_input_key:string;expected_input_hash:string;author:string;note:string;confirmed:true;
}

/** 明确修订由回执及原输入绑定；中文名称记录数不等于已核结构数。 */
export interface RescuePresentationRevision {
  revision_id:string;receipt_sha256:string;input_key:string;input_hash:string;matches_input:boolean;
  name_counts:{chinese:number;source_term_only:number;original_proper_name:number};
  allowed_original_name_ids:string[];
}
export interface RescuePresentationItem {
  revision_id:string;receipt_sha256:string;input_key:string;created_at:string;matches_input:boolean;view_url:string;
}
export interface RescuePresentationDirectory {
  run_id:string;enabled:boolean;blockers_zh:string[];expected_input_hash:string|null;translation_missing_ids:string[];
  current:RescuePresentationItem|null;history:RescuePresentationItem[];read_only:true;
  current_view?:SystemRescueDisplay|null;
}
export type RescuePresentationBootstrap = {directory:RescuePresentationDirectory} | {error_zh:string};
export interface RescuePresentationRequest {
  request_id:string;expected_run_id:string;expected_input_hash:string;author:string;note:string;confirmed:true;
}

/** 补救执行只提交当前来源版本和明确操作依据，不接收科学参数。 */
export interface ReceptorRescueRequest {
  request_id:string;expected_preparation_run_id:string;expected_scoring_run_id:string;
  expected_input_hash:string;author:string;note:string;confirmed:true;
}
/** 准备页按用户点击惰性读取；续做必须原样使用后端给出的已登记request。 */
export interface ReceptorRescueInfo {
  schema_version:'A06.system_rescue.1'|'A06.system_rescue.2';enabled:boolean;busy:boolean;blockers:string[];
  expected_preparation_run_id:string|null;expected_scoring_run_id:string|null;expected_input_hash:string|null;
  current_run_id:string|null;state:'ready'|'incomplete'|'complete'|'blocked';request?:ReceptorRescueRequest|null;
}

/** 本版待核原件只读整理；原查询返回量不等于可采用身份数。 */
export interface ComponentIdentityProbeRequest {request_id:string;expected_a01:string;expected_input_hash:string;author:string;note:string;confirmed:true}
export interface HistoricalDiseaseSourcesInfo {
 schema_version:string;supported:boolean;enabled:boolean;busy:boolean;blockers:string[];notice_zh:string;expected_a00:string|null;expected_plan_id:string|null;expected_input_hash:string|null;expected_source_hashes:Record<string,string>;
 sources:{database:string;source:{version:string;retrieved_at:string};archive:{sha256:string}}[];
 records:{created_at:string;notice_zh:string;request:{request_id:string;author:string;note:string;user_decision:string}}[];
}
export interface ComponentIdentityProbeInfo {
 schema_version:string;supported:boolean;enabled:boolean;busy:boolean;blockers:string[];message_zh:string;expected_a01:string|null;expected_input_hash:string;
 targets:{target_id:string}[];
 records:{probe_id:string;created_at:string;state:string;message_zh:string;request:ComponentIdentityProbeRequest;candidate_coverage_complete:boolean;coverage_message_zh:string;
  rows:{target_id:string;message_zh:string;issues:Record<string,unknown>[];adopted:false}[];
  queries:{label_zh:string;state:string;http_status:number|null;retrieved_at:string;reused:boolean;error_zh:string}[];
  downloads:{label_zh:string;url:string}[]}[];
}

export interface ComponentIdentityEvidence {
 schema_version:string;supported:boolean;read_only:true;study_id:string;expected_a01:string|null;expected_input_hash:string;message_zh:string;
 stats:null|{source_rows:number;protein_query_groups:number;source_without_target_rows:number;other_identity_rows:number;display_groups:number};
 units:{unit_id:string;database:string;kind:string;raw_name:string;raw_target_ids:string[];original_reason_zh:string;
  records:Record<string,unknown>[];record_count:number;file_indices:number[];response_state:string;response_records:number|null;
  original_url?:string;query?:string;protein_candidates:{accession:string;recommended_name:string;alternative_names:string[];taxid:number|null;genes:string[]}[]}[];
 files:{index:number;label_zh:string;file:{path:string;bytes:number;sha256:string;role:string};url?:string}[];
 export_json_url?:string;export_csv_url?:string;
}

/** 模块页 */
export interface DiseaseScopeInfo {
  enabled: boolean; disabled_reason_zh: string; expected_a00: string; expected_run: string; expected_staging: string;
  choices: { value: string; label_zh: string }[];
  saved_counts?: {value: string; label_zh: string; count: number}[];
  items: { scope_id: string; database: string; disease_term: string; disease_id: string; records: number; scope: string; source_name: string; source_url: string; identity_warning: string; direct_allowed: boolean }[];
}
// 一次授权独立版本，原件下载只采用服务器给出的索引链接。
export interface AutomaticFile {name: string; path?: string; role: string; url: string}
export interface AutomaticPair {pair_key?:string; status_zh?:string; compound_id: string; target_id: string; compound_name: string; symbol: string; state: string; quality: string; score: number | null; reason_zh: string; trace?: Record<string, unknown>; evidence_files?: AutomaticFile[]}
export interface ReferenceChoice {target_id:string; candidate_key:string; reference_key:string}
export interface ReferenceCandidate extends ReferenceChoice {pdb_id:string; component_id:string; name:string; selectable:boolean; reason_zh:string; source_url:string}
export interface ReferenceReviewInfo {supported:boolean;enabled:boolean;execution_available:false;reason_zh:string;expected_input_id?:string;expected_preparation_run_id?:string;source_preparation_run_id?:string;items:{target_id:string;symbol:string;state:string;options:ReferenceCandidate[]}[];saved_reviews?:{request?:{choices?:ReferenceChoice[]}}[]}
export interface ReferencePreparationInfo {supported:boolean;enabled:boolean;execution_available:false;reason_zh:string;expected_input_id?:string;expected_preparation_run_id?:string;source_preparation_run_id?:string;state?:'bound';summary?:Record<string,unknown>|null;reviews?:{review_id:string;request?:{choices?:ReferenceChoice[]}}[]}
export interface ScoringReadinessInfo {supported:boolean;enabled:boolean;scoring_allowed:boolean;execution_available:boolean;preflight_available?:boolean;current_run_id?:string;blockers:string[];reason_zh:string}
export interface AutomaticRequest {expected_binding: string; expected_connection_id: string; expected_a06: string | null; request_id: string; policy_version: string; reviewer: string; note: string; confirmed: boolean; reference_choices?:ReferenceChoice[]}
export interface AutomaticMatrixView {
  score_range:[number|null,number|null]; annotation?:{legend_zh?:string}; threshold_note_zh:string;
  heatmap:{rows:{compound_id:string;name_zh:string;name_en:string}[];columns:{target_id:string;symbol:string;candidate_grade:string}[]};
  table:{rows:{compound_id:string;name_zh:string;name_en:string}[];columns:{target_id:string;symbol:string;candidate_grade:string}[];cells:{compound_id:string;target_id:string;score:number|null;display_score:string;threshold_mark:string;reason_zh:string;quality:string;color:string;text_color:string}[][]};
}
export interface AutomaticMatrixResponse {view:AutomaticMatrixView; svg:string; downloads:{name:string;url:string;role:string}[]; display_id:string|null; expected_a06:string; enabled:boolean}
export interface AutomaticPage<T> {items:T[];total:number;page:number;size:number}
export interface AutomaticDockingInfo {
  active_task_kind?:string|null;
  scope?:ExtendedDockingScope;
  migration_note_zh?: string;
  enabled: boolean; disabled_reason_zh: string; expected_binding: string; expected_connection_id: string | null; expected_a06: string | null;
  counts: {compounds: number; receptors: number; pairs: number}; policy: {version: string; summary_zh: string; details_zh: string[]};
  connection: {id: string; compound_resolution_version?:string; summary: {connected_compounds: number; connected_receptors: number; exceptions: number};
    objects: {id: string; name: string; state: string; cid?: number; reason_zh: string; structures: {pdb_id?: string; model_id?: string; source_type?: string; chains: string[]; pocket: string; altloc?: string | null}[]}[]; files: AutomaticFile[]; reference_candidates?:ReferenceCandidate[]} | null;
  latest: {id: string; state: string; run_id: string | null; summary: Record<string, unknown> | null; error_zh?: string; pairs: AutomaticPair[]; files: AutomaticFile[];file_count?:number;display_id?:string|null} | null;
}
/** 后台仅从本批原始矩阵派生文件，不代表科学复核。 */
export interface SystemExportRequest {
  request_id:string;expected_module:'A06'|'A06_PREP';expected_run_id:string;
  expected_input_hash:string;author:string;note:string;confirmed:true;
}
export interface SystemExportRecord {
  export_id:string;source_module:'A06'|'A06_PREP';source_run_id:string;created_at:string;
  files:{path:string;bytes:number;sha256:string;name:string;download_url:string}[];
}
export interface SystemExportsInfo {
  schema_version:string;enabled:boolean;blockers:string[];message_zh:string;
  expected_module:'A06'|'A06_PREP'|null;expected_run_id:string|null;expected_input_hash:string|null;
  current:SystemExportRecord|null;history:SystemExportRecord[];
}
/** 同批展示只读取服务端已登记事实，不代表人工复核或科学结果变更。 */
export interface DisplayRevisionDownload {label_zh:string;name:string;url:string;bytes?:number;sha256?:string}
export interface DisplayRevisionFigure {
  key:string;module_id:string;group?:string;role:string;label_zh:string;caption_zh:string;
  image_url:string;downloads:DisplayRevisionDownload[];
}
export interface DisplayRevisionTable {
  key:string;module_id:string;label_zh:string;columns:{key:string;label_zh:string}[];
  rows:Record<string,unknown>[];total:number;preview_note_zh?:string;downloads:DisplayRevisionDownload[];
}
export interface DisplayRevisionHistory {
  revision_id:string;created_at:string;source_run_ids:Record<string,string>;matches_input?:boolean;
  downloads:DisplayRevisionDownload[];
}
export interface DisplayRevisionRecord extends DisplayRevisionHistory {
  matches_input:boolean;
  counts:{label_zh:string;text:string}[];
  translation_coverage:{required:number;verified:number;missing:string[]};
  figures:DisplayRevisionFigure[];tables:DisplayRevisionTable[];
  human_review_written:false;scientific_results_changed:false;
}
export interface DisplayRevisionInfo {
  schema_version:string;supported:boolean;enabled:boolean;blockers:string[];expected_input_hash:string|null;
  current:DisplayRevisionRecord|null;history:DisplayRevisionHistory[];
  module_current?:{module_id:string;note_zh:string;record:DisplayRevisionRecord}|null;
}
export interface DisplayRevisionRequest {request_id:string;expected_input_hash:string;author:string;note:string;confirmed:true}
export interface DisplayRevisionResponse {task?:Task;revision_id?:string;created:boolean;message_zh:string}
export interface SystemReceptorSelectionInfo {
  schema_version: string; read_only: true;
  archive_state: 'pending' | 'archived' | 'source_changed';
  selection_id: string | null; input_id: string | null;
  mode: 'degree' | 'bc_cc' | 'dual_ab' | null;
  requested_count: number | null; actual_count: number | null; boundary_ties_retained: boolean | null;
  compound_count: number | null; pair_count: number | null;
  selected: {target_id: string; symbol: string; selection_order: number; candidate_grade?: string | null;
    degree: number; bc?: number; cc?: number; mean_rank?: number}[];
  message_zh: string; scope_note_zh: string;
}
export interface ModuleView {
  receptor_rescue_available?: boolean;
  reference_workflow_supported?: boolean;
  display_revision?: DisplayRevisionInfo | null;
  system_receptor_selection?: SystemReceptorSelectionInfo | null;
  system_exports?: SystemExportsInfo | null;
  automatic_docking?: AutomaticDockingInfo | null;
  input_audit?: {formula: {run_id: string; sources: string[]; missing_sources: string[]; component_label_zh: string; component_count: number | null; target_count: number | null; relationship_count: number | null} | null;
    disease: {run_id: string; candidate_count: number | null; target_count: number | null; scope_counts: {value: string; label_zh: string; count: number; records: number}[]; empty_reason_zh: string} | null;
    checks: {kind?: 'input_update'; level: 'info' | 'warning'; label_zh: string; detail_zh: string; module_id?: string}[]} | null;
  operation_guide?: {current_step: number; note_zh: string; steps: {key: string; label_zh: string; detail_zh: string; target: string; module_id?: string; href?: string}[]} | null;
  disease_workflow?: {current_step: number; note_zh: string; next_label_zh: string; next_target: string} | null;
  normalization?: NormalizationInfo | null;
  disease_scope?: DiseaseScopeInfo | null;
  ranked_pathway_maps?: RankedPathwayMapsInfo | null;
  docking_artifacts?: DockingArtifactInfo | null;
  trial_preparation?: TrialPreparationInfo | null;
  trial_handoff?: {run_id:string;active:boolean;trial_id:string;review_url:string;note_zh:string;reviewer:string;note:string}|null;
  docking_trial?: DockingTrialInfo | null;
  docking_review?:DockingReviewInfo|null;
  compound_selection?:CompoundSelectionInfo|null;
  docking_preparation?:DockingPreparationInfo|null;
  reference_qualification?:ReferenceQualificationInfo|null;
  review_packet?:ReferenceReviewPacket|null;
  review_gate?:ReferenceReviewGate|null;
  reviewable_preparation?:ReviewablePreparationInfo|null;
  plan_scoring?:PlanScoringInfo|null;
  creation_plan?:CreationPlanInfo|null;
  plan_a01?:PlanA01Info|null;
  plan_a05?:PlanA05Info|null;
  plan_a05_display?:PlanA05DisplayInfo|null;
  plan_stages?:PlanStagesInfo|null;
  plan_system_validations?:PlanSystemValidationsInfo|null;
  plan_reports?:PlanReportsInfo|null;
  plan_compounds?:PlanCompoundsInfo|null;
  plan_selection_ui?:PlanSelectionUiInfo|null;
  plan_preparation_ui?:PlanPreparationUiInfo|null;
  scoring_readiness?:ScoringReadinessInfo|null;
  docking_coverage?:DockingCoverageInfo|null;
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

/** 新方案预测位点的只读资格与完整决定范围。 */
export interface PlanPocketInfo {
  supported: boolean; enabled: boolean; reason_zh: string; execution_available: false;
  testing?: boolean; study_label_zh?: string; purpose_zh?: string;
  expected_input_id?: string; expected_preparation_run_id?: string; source_preparation_run_id?: string;
  saved_decisions?: {target_id: string; pocket_key: string | null}[] | null;
  current_summary?: {ready_pairs: number; na_pairs: number; pair_count: number; scored_pairs: number; message_zh: string} | null;
  items: {target_id: string; symbol: string; state: string; reason_zh: string; options: {
    pocket_key: string | null; pdb_id: string; eligible: boolean; reason_zh: string;
    uniprot?: string; chains?: string[]; mapped_residues?: string[];
    prediction?: Record<string, string>; box?: {center: number[]; size: number[]};
    prediction_files?: {path: string; bytes: number; sha256: string}[];
  }[]}[];
}

/** 用户提交完整受体顺序的预测口袋采用决定。 */
export interface PlanPocketRequest {
  request_id: string; expected_input_id: string; expected_preparation_run_id: string;
  reviewer: string; note: string; confirmed: true;
  decisions: {target_id: string; pocket_key: string | null}[];
}

/** 后台生成的标准化预览，页面不计算基因身份与交接状态。 */
export interface NormalizationInfo {
  enabled: boolean; disabled_reason_zh: string; scope_note_zh: string;
  expected_a00: string; expected_a01: string; expected_a02: string;
  preview: { stamp: string; modules: { module: string; summary: Record<string, unknown>; identity_issues: Record<string, unknown>[] }[]; source_exceptions: Record<string, unknown>[] } | null;
}

/** 当前A05两种排名首位的同源命中定位图。 */
export interface RankedPathwayMapsInfo {
  enabled: boolean; expected_a05: string; disabled_reason_zh: string; semantics_zh: string;
  items: {ranking: 'statistical_significance' | 'count'; id: string; name_en: string; name_zh: string;
    count: number; adjusted_p: number; not_in_current_kgml: string[]; png_url: string; caption_zh: string}[];
}

/** 明细表分页返回 */
export type TablePage =
  | { kind: 'rows'; name?: string; columns: string[]; total: number; page: number; size: number; items: Record<string, unknown>[] }
  | { kind: 'object'; name?: string; data: unknown };

/** 复核提交的返回 */
export interface ReviewResponse { review: ReviewRecord; task: Task | null; message_zh: string }
export interface A03InputPreview {
  token: string;
  purpose: string;
  issues: Record<'A01' | 'A02' | 'scope', Record<string, string | number>[]>;
  available_targets: Record<'A01' | 'A02', number>;
}
/** 批量复核的返回 */
export interface BatchReviewResponse { reviews: unknown; task: Task | null; message_zh: string }

/** 双分支第二轮归档排名，网页不重新计算名次 */
export interface PpiDualRow { target_id: string; symbol: string; degree: number; bc: number; cc: number; rank: number; bc_rank?: number; cc_rank?: number; mean_rank?: number }
export interface PpiDual { network_round?: 1 | 2; degree_round?: 1 | 2; network?: { url: string; caption_zh: string } | null; version: string; counts: Record<string, number>; thresholds: Record<string, unknown>[]; degree_rows: PpiDualRow[]; bc_cc_rows: PpiDualRow[]; note_zh: string; network_note_zh: string }

// A04专用任务由后端核验研究和上游版本，网页只显示和传回绑定。
export interface PpiRunInfo { enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a04: string }

// 只读待核验身份，显示归档原值；不提供代签或自动身份替换。
export interface PpiIdentityRow { target_id: string; symbol: string; returned: string; reason_zh: string }
export interface PpiIdentity { total: number; source_table: string; note_zh: string; rows: PpiIdentityRow[]; scope_kind?: 'explicit_bound_test_decision'; handoff_blocked?: boolean }
export interface ReviewBlocker {
  title_zh: string;
  owner_zh: string;
  action_zh: string;
  examples: string[];
  section_id: string | null;
  href: string | null;
  file_key: string | null;
}

// 保存的是人工补查方案；身份与模块是否可通过仍由科学归档和Workflow决定。
export interface IdentityPlanInfo { enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a04: string; expected_decision_id: string | null; latest: { decision_id: string; reviewer: string; note_zh: string; created_at: string; check_ids: string[]; omit_ids: string[]; applied_run_id: string | null; pending_count: number | null; evidence_url?: string | null; error_zh?: string; status_zh: string } | null }
// A05确认绑定研究运行；候选、排名和是否可写均来自归档接口。
export interface EnrichmentCatalogRow { ID: string; Description: string; description_zh: string; translation_status: string; Count: number; 'p.adjust': number; RichFactor: number; gene_symbols: string; proposed?: boolean; reason_zh?: string; evidence_url?: string; classification_status?: 'exclude' | 'retain' | 'uncertain'; classification_zh?: string; official_name?: string }
export interface EnrichmentDisplayInfo { kegg_ready: boolean; kegg_reason_zh: string; enabled: boolean; disabled_reason_zh: string; expected_a03: string; expected_a05: string; expected_decision_id: string | null; exclusions_confirmed: boolean; layout_confirmed: boolean; excluded_ids: string[]; missing_translations: string[]; catalog: EnrichmentCatalogRow[]; retained_count: number; excluded_count: number; significant_count: number; screening?: {version: string; source_url: string; proposed_count: number; uncertain_count: number} | null; latest: { reviewer: string; note_zh: string; created_at: string; applied: boolean; status_zh: string } | null }
export interface EnrichmentDisplayRequest { expected_a03: string; expected_a05: string; expected_decision_id: string | null; action: 'exclusions' | 'layout'; reviewer: string; note: string; excluded_ids: string[]; confirmed: true; exclude_all_confirmed?: boolean }

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
export interface ExtendedDockingScope {schema_version:string;study_id:string;a03_run:string;selection_run:string|null;primary_limit:number;expanded_target:number;required_count:number;available_count:number;selected_count:number;approved:boolean;ready:boolean;reason_zh:string;proposed_ids:string[];manual_reasons:Record<string,string>;boundary_count:number;proposed_count:number;note_zh:string}
export interface CompoundSelectionInfo { enabled:boolean; disabled_reason_zh:string; expected_a03:string; expected_select:string; rows:CompoundChoiceRow[]; current_selected:string[]; current_manual_supplements?:Record<string,string>; previous_rows:CompoundChoiceRow[]; previous_active:boolean; rule_zh:string;extended_scope?:ExtendedDockingScope }
export interface StructureSpec { source_type:'experimental'|'alphafold'; uniprot:string; chains:string[]; pocket?:'reference'|'p2rank'; pdb_id?:string; model_id?:string; sequence_start?:number; sequence_end?:number; altloc?:string|null; reference_code?:string; reference_chain?:string; reference_sequence?:string }
export interface TwoPassRow {target_id:string;symbol:string;candidate_grade:string;first:StructureSpec|null;first_reason:string;second:StructureSpec|null;second_reason:string;unavailable:boolean;reason:string}
export interface TwoPassCompound {compound_id:string;status:'use'|'unavailable'|null;cid?:string;reason:string;protonation_policy?:string;material_id?:string}
export interface TwoPassPlan {policy_version:string;package_id:string;pymol_executable:string;compounds:TwoPassCompound[];receptors:TwoPassRow[]}
export interface PlanRowCheck {target_id:string;valid:boolean;bulk_allowed:boolean;reason_zh:string}
export interface ConfirmationItem {kind:"receptor"|"compound"|"configuration";id:string;label_zh:string;reason_zh:string}
export interface TwoPassConfirmation {ready:boolean;receptor_count:number;compound_count:number;planned_pair_count:number;normal_target_ids:string[];pending:ConfirmationItem[];unavailable:ConfirmationItem[];execution_allowed:false;note_zh:string}
export interface DockingMaterial {material_id:string;compound_id:string;cid:string;name:string;state_zh:string}
export interface TwoPassDraftInfo {draft_id:string;created_at:string;reviewer:string;note:string;checked_target_ids:string[]}
export interface SourceChoice {recommended_value?:string;kind:'altloc'|'route';target_id:string;symbol:string;pdb_id:string;round:'first'|'second';options:string[];reason_zh:string;proposal?:StructureSpec}
export interface SourceInspectionRow {target_id:string;symbol:string;candidate_grade:string;pdb_id:string;chains:string[];identity_matched:boolean;altloc_codes:string[];missing_residue_count:number;missing_atom_count:number;reference_count_matches:boolean|null;reference_covalent_count:number|null;reason_zh:string;file_key:string;rejected_sources?:{pdb_id:string;reason_zh:string}[];audit:Record<string,unknown>}
export interface SourceInspectionReview {review_id:string;created_at:string;note_zh:string;execution_allowed:false;approval:null;choices:SourceChoice[];receptors:SourceInspectionRow[];compounds:{compound_id:string;name_zh:string;cid:string;identity_matched:boolean;reason_zh:string;file_key:string;material_id?:string}[]}
export interface DockingPreparationInfo {
  quality_status_zh?: string; // 本轮实际质控归档状态，由服务端给出。
source_review?:SourceInspectionReview|null;expected_source_review_id?:string|null;confirmation:TwoPassConfirmation;expected_draft_id?:string|null;draft?:TwoPassDraftInfo|null;metadata_review?:ReceptorMetadataReview|null;enabled:boolean;disabled_reason_zh:string;expected_source:string;expected_plan_id:string|null;policy_version:string;plan:TwoPassPlan;checks:PlanRowCheck[];materials:DockingMaterial[];context:{receptors:DockingCandidateRow[];compounds:{compound_id:string;name:string;herbs:string[]}[]};planned_pair_count:number;execution_allowed:false;status_zh:string;latest?:{reviewer:string;note:string;created_at:string}|null}

// 新版A06绑定准备的整体复核资格；只显示服务端复算，不代替人工批准。
export interface ReferenceQualificationInfo {supported:boolean;enabled:boolean;qualified:boolean;can_enter_review:boolean;execution_available:false;current_run_id?:string;scored_pairs:number|null;checked_files?:number;summary?:Record<string,unknown>|null;blockers:string[];reason_zh:string}

// A06整体复核材料包；只读汇总版本和阻断条件，不提交人工决定。
export interface ReferenceReviewPacket {supported:boolean;review_available:boolean;execution_available:false;scoring_allowed:false;can_enter_review:boolean;current_run_id?:string;version?:string;summary?:Record<string,unknown>|null;qualification?:ReferenceQualificationInfo;scoring?:ScoringReadinessInfo;checked_files:number;blockers:string[];reason_zh:string}

export interface ReviewablePreparationInfo {supported:boolean;enabled:boolean;execution_available:false;current_run_id?:string;expected_input_id?:string|null;state?:string;reason_zh:string}

export interface PlanScoringInfo {
  supported:boolean;enabled:boolean;execution_available:boolean;protocol_version:string;
  blockers:string[];state:string;reason_zh:string;current_run_id:string|null;
  expected_preparation_run_id?:string;expected_preparation_review_id?:string;expected_input_id?:string;
  parameters?:{scoring:string;exhaustiveness:number;num_modes:number;energy_range_kcal_mol:number;seed:number};
  pair_count?:number;ready_pairs?:number;na_pairs?:number;result_run_id?:string;
  summary?:{scored_pairs:number;failed_pairs:number;na_pairs:number;strict_scored_pairs:number;exploratory_scored_pairs:number};
}

// A06人工整体复核闸门；当前只读，未满足条件时不提供提交决定。
export interface ReferenceReviewGate {supported:boolean;can_submit:boolean;allowed_decisions:string[];current_run_id?:string;checked_files?:number;blockers:string[];reason_zh:string}

// 正式评分前置预检；只读，不创建评分任务。
export interface ScoringValidation {
  protocol_version:string; supported:boolean; read_only:true; allowed:false; execution_available:false;
  current_run_id:string; source_preparation_run_id:string; input_id:string; input_key:string;
  analysis_parameter_hash:string; config_hash:string; input_hash:string; latest_preparation_review_id:string|null;
  pair_count:number; ready_pairs:number; na_pairs:number;
  scoring_parameters:{scoring:string;exhaustiveness:number;num_modes:number;energy_range_kcal_mol:number;seed:number};
  box_padding:number; requested_rmsd_max_A:number; blockers:string[]; reason_zh:string;
}

// 研究核查草案与同批矩阵只读，身份预核查不代替人工确认。
export interface DockingReviewCompound extends CompoundChoiceRow {name_zh:string;cid:string;identity_prechecked:boolean;identity_state_zh:string;source_3d_state_zh:string;evidence_zh:string;manual_reason_zh:string}
export interface DockingMatrixCell {compound_id:string;target_id:string;state:string;score:number|null;reason_zh:string;color:string;text_color:string}
export interface DockingMatrixSlice {rows:DockingReviewCompound[];columns:(DockingCandidateRow&{candidate_grade:string;quality_zh:string})[];cells:DockingMatrixCell[][]}
export interface DockingMatrixInfo {palette:{id:string;high_color:string;low_color:string;na_color:string;unit:string;label_zh:string};display_version:string;heatmap_svg:string|null;ready:boolean;status_zh:string;full_pair_count:number;score_range:[number|null,number|null]|null;result_version:string|null;heatmap:DockingMatrixSlice;table:DockingMatrixSlice}
export interface DockingReviewInfo {enabled:boolean;reason_zh:string;review_id:string|null;proposal:{acetic_trace?:SourceIdentityTrace;compounds:DockingReviewCompound[];excluded:{compound_id:string;name_zh:string;reason_zh:string}[];note_zh:string;receptors:DockingCandidateRow[]}|null;matrix:DockingMatrixInfo|null}

// 来源冲突追溯只读；计数及逐行映射来自归档，不在网页重新归属靶点。
export interface SourceIdentityTrace {bulk:Record<string,string>;detail:Record<string,string>;official:{cid:string;url:string;properties:{MolecularFormula:string;InChIKey:string}}[];raw_rows:number;normalized_rows:number;unique_targets:number;intersection_targets:number;outside_intersection:number;trace:{source_row:number;raw_target_id:string;raw_symbol:string;database_source_titles:string[];target_id:string;symbol:string;in_current_intersection:boolean}[];live_confirmation?:{same_as_archived:boolean;cas_query_cid:number}}

// 官方候选摘要仅供核查，不代表当前结构质控通过。
export interface ReceptorMetadataCandidate {source_rejected?:boolean;source_reason_zh?:string;pdb_id:string;url:string;title:string;methods:string[];resolution:number[];target_chains:{entity_id:string;chains:string[];length:number;description:string;fragment:string|null;mutation_count:number|null;reference_coverage:number|null}[];ligands:{code:string;name:string;author_chains:string[]}[];review_state_zh:string;blocked_previous_failure:boolean}
export interface ReceptorPlanProposal {route_zh:string;domain_zh:string;first_pdb_id:string|null;second_pdb_id:string|null;reference_zh:string;reason_zh:string;pending_zh:string[];alternatives:{pdb_id:string;url:string;state_zh:string;same_target:boolean}[];model_metadata?:{entry_id:string;uniprot:string;sequence_start:number;sequence_end:number;model_version:number;state_zh:string}[]}
export interface ReceptorMetadataRow {source_audit?:SourceInspectionRow;plan_proposal?:ReceptorPlanProposal;target_id:string;symbol:string;candidate_grade:string;uniprot:string;sequence_length:number;protein_name:string;identity_state_zh:string;identity_url:string;first_state_zh:string;second_state_zh:string;search_total:number;inspected_entry_count:number;candidates:ReceptorMetadataCandidate[];historical:{pdb_id:string;status_zh:string;reason_zh:string;rmsd_A:number|null;current_passed:false}|null;limitations_zh:string;current_qc_zh:string;alphafold_url:string}
export interface ReceptorMetadataReview {review_id:string;created_at:string;note_zh:string;execution_allowed:false;approval:null;compounds:{compound_id:string;name:string;name_zh:string;cid:string;herbs:string;identity_prechecked:boolean;source_3d_state_zh:string;source_3d_evidence:{path:string;sha256:string;bytes:number;is_3d:boolean}[]}[];receptors:ReceptorMetadataRow[]}

// 本轮技术核查与人工采用分别由后端记录，不在前端推算可用资格。
export interface CoverageAttempt {site_coverage?:{note_zh:string};round:number;spec:StructureSpec;reason_zh:string;top1_rmsd?:number;pocket?:{runs:Record<string,unknown>[]};confidence_facts?:{mean_plddt:number;min_plddt:number;max_bidirectional_pae_A:number};environment_audit?:{box_environment:{chain:string;residue:string;sequence:string;reason_zh:string}[]}}
export interface DockingCoverageRow {target_id:string;symbol:string;candidate_grade:string;ppi_order:number;pdb_id:string;rmsd_A:number|null;quality_zh:string;status_zh:string;reason_zh:string;eligible:boolean;adopted:boolean;selected:boolean;spec:StructureSpec|null;attempts:CoverageAttempt[]}
export interface DockingCoverageInfo {enabled:boolean;disabled_reason_zh:string;expected_run:string;expected_source:string;campaign_id:string;expected_decision_id:string|null;confirmed:boolean;draft:{selected_target_ids:string[];reviewer:string;note:string}|null;rows:DockingCoverageRow[];counts:{strict:number;exploration:number;unavailable:number;receptors:number};conditions:{main_results:boolean;exploration:boolean;prepared_pairs:number};batch_docking_allowed:false;note_zh:string}

/** 独立扩展试算，不替换严格结果及审批；原值来自服务端。 */
export interface TrialReceptor {
 target_id:string;symbol:string;candidate_grade:string;structure_id?:string;state:string;mode:string;
 processing_zh?:string;reason_zh?:string;history_quality_zh?:string;history_rmsd_A?:number|null;
 source?:{path:string}|null;spec?:unknown;regions?:unknown[];environment?:unknown;attempts?:unknown[];
 repair?:{added_atoms:unknown[];original_coordinates_unchanged:boolean}|null;
}

/** 同批准备关联只读呈现，不新增人工审批。 */
export interface PreparationFile {path:string;sha256:string;bytes:number;role?:string;url?:string|null}
export interface TrialPreparationInfo {
 link_id:string;created_at:string;active:boolean;read_only:boolean;reason_zh:string;
 a06_run_id:string;trial_id:string;result_url:string;source_url:string;
 reviewer:string;reviewed_at:string|null;note:string;a06_reviewer:string;a06_reviewed_at:string;
 legacy_run_id:string;history_rows:Record<string,unknown>[];
 receptors:(TrialReceptor & {source?:PreparationFile|null;receptor:PreparationFile;spec?:unknown})[];
 compounds:{compound_id:string;name_zh:string;cid:string;state:string;files:PreparationFile[];
   preparation:{identity?:{identity_check?:string;inchi_key?:string;formula?:string};[key:string]:unknown}}[];
}
/** 统一批次仅读服务端状态和原参数，首次确认不代签科研结论。 */
export interface PipelineParameters {parameter_hash?:string;mode_label_zh?:string;parameters?:{key:string;label_zh:string;value:string|number|boolean;unit:string}[]}
export interface SystemPipelineEvent {attempt_id:string;event:string;stage?:string;stage_label_zh:string;state_label_zh:string;state?:string;reason_zh?:string;error_zh?:string;created_at:string;report_run_id?:string}
export interface SystemPipelineInfo {
 study_label_zh:string;purpose_zh:string;busy:boolean;automatic_execution_available:boolean;
 start:PipelineParameters&{enabled:boolean;supported:boolean;blockers:string[];expected_a00:string;expected_plan_id:string;expected_input_hash:string};
 batches:(PipelineParameters&{batch_id:string;plan_id:string;expected_input_hash:string;continue_enabled:boolean;continue_blockers:string[];
  history:SystemPipelineEvent[];latest_event:SystemPipelineEvent|null})[];
}
export interface DockingTrialInfo {
 trial_id:string;state:string;stale:boolean;enabled:boolean;note_zh:string;
 progress:{step_zh:string;pairs_done:number;pairs_total:number;regions_done:number;regions_total:number};
 receptors:TrialReceptor[];downloads:{name:string;url:string}[];
 summary?:{completed:number;NA:number};
 review?:{review_id:string;reviewer:string;note:string;confirmed:boolean}|null;
 matrix?:{display_version?:string;heatmap_svg?:string;annotation_legend?:string;columns:{id:string;label:string;grade:string}[];score_range:number[]|null;
 heatmap_compounds:string[];heatmap_targets:string[];
 rows:{id:string;label:string;label_zh?:string;label_en?:string;cells:{target_id:string;score:number|null;display_score?:string;highlight?:boolean;state:string;color:string;text_color:string;
 reason_zh:string;region_id:string|null;mode:string;partial_regions:boolean}[]}[]}|null;
}
