// 文件用途：访问本机 JSON 接口的唯一出口。负责拼接地址、携带操作令牌、把错误统一转成 ApiError。
import type {
  ApiErrorBody, BatchReviewResponse, Decision, GlobalInboxEntry, ModuleView, ReviewResponse, RunItem,
  Session, StudyCard, StudyView, WorkspaceView, TablePage, Task,
} from './types';

// 开发模式下直连本机接口（可用环境变量 VITE_API_BASE 覆盖）；生产构建与后端同源，用相对路径
const DEV_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || 'http://127.0.0.1:8799';
/** 接口前缀 */
export const API_BASE = import.meta.env.DEV ? `${DEV_BASE.replace(/\/$/, '')}/api/v1` : '/api/v1';

/** 接口错误：保留 HTTP 状态、错误码和中文说明 */
export class ApiError extends Error {
  status: number; // HTTP 状态码
  code: string; // 契约中的错误码，例如 STALE_VERSION
  messageZh: string; // 面向用户的中文说明
  retryable: boolean; // 是否可以稍后重试
  details: Record<string, unknown>; // 附加信息
  constructor(status: number, code: string, messageZh: string, retryable = false, details: Record<string, unknown> = {}) {
    super(messageZh); // 让 Error.message 也是中文说明
    this.status = status;
    this.code = code;
    this.messageZh = messageZh;
    this.retryable = retryable;
    this.details = details;
  }
}

// 内存中保存的操作令牌（不写入浏览器存储）
let token: string | null = null;

// 只合并尚未完成的同URL读取；不保留完成结果。写请求前后清空，避免旧读挡住写后刷新。
const pendingReads = new Map<string, Promise<unknown>>();

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown, retried = false): Promise<T> {
  if (method === 'POST') {
    pendingReads.clear();
    try { return await sendRequest<T>(method, path, body, retried); }
    finally { pendingReads.clear(); }
  }
  let pending = pendingReads.get(path);
  if (!pending) {
    pending = sendRequest<T>(method, path, body, retried);
    pendingReads.set(path, pending);
  }
  try {
    // 每个调用者得到独立JSON容器，避免一个组件修改另一个组件的响应。
    return structuredClone(await pending) as T;
  } finally {
    if (pendingReads.get(path) === pending) pendingReads.delete(path);
  }
}

/** 发送请求并解析 JSON；非 2xx 时抛出 ApiError */
async function sendRequest<T>(method: 'GET' | 'POST', path: string, body?: unknown, retried = false): Promise<T> {
  const headers: Record<string, string> = {}; // 请求头
  if (method === 'POST') {
    if (!token) await loadSession(); // 写请求前确保已取得令牌
    if (!(body instanceof FormData)) headers['Content-Type'] = 'application/json'; // multipart边界由浏览器生成
    headers['X-ModuleA-Token'] = token || ''; // 携带令牌
  }
  let res: Response; // 网络响应
  try {
    res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
  } catch {
    // 网络层失败（服务未启动等）
    throw new ApiError(0, 'NETWORK', '无法连接本机服务，请确认工作台服务仍在运行', true);
  }
  const text = await res.text(); // 先取文本，避免空正文解析出错
  let data: unknown = null; // 解析后的数据
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null; // 非 JSON 正文按空处理
  }
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error; // 契约规定的错误结构
    // 令牌失效：重新获取一次令牌后重试
    if (res.status === 403 && err?.code === 'BAD_TOKEN' && !retried) {
      token = null;
      await loadSession();
      return request<T>(method, path, body, true);
    }
    throw new ApiError(res.status, err?.code || 'HTTP_' + res.status, err?.message_zh || `请求失败（HTTP ${res.status}）`, !!err?.retryable, err?.details || {});
  }
  return data as T; // 成功时返回数据
}

/** 读取会话信息并保存令牌 */
export async function loadSession(): Promise<Session> {
  const s = await request<Session>('GET', '/session'); // 取会话
  token = s.token; // 保存令牌供写请求使用
  return s;
}

/** 把查询参数对象转成 ?a=1&b=2（忽略空值） */
function qs(params: Record<string, string | number | undefined | null>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '') // 去掉空参数
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`); // 编码
  return parts.length ? '?' + parts.join('&') : '';
}

/** 保留后端焦点URL的回执和输入绑定；已有输入冲突时拒绝发送，不覆盖为另一批。 */
function rescueFocusPath(url:string,inputKey:string,compounds:string[],targets:string[]):string {
  const path=url.replace(/^\/api\/v1/,'');const index=path.indexOf('?');
  const query=new URLSearchParams(index<0?'':path.slice(index+1));
  const existing=query.getAll('expected_input_key');
  if(existing.length>1||(existing.length===1&&existing[0]!==inputKey))throw new Error('焦点图输入版本已改变，请刷新。');
  query.set('expected_input_key',inputKey);query.set('compounds',JSON.stringify(compounds));query.set('targets',JSON.stringify(targets));
  return (index<0?path:path.slice(0,index))+'?'+query.toString();
}

// 各端点的薄封装；路径与契约第 3 节一致
export const api = {
  /** 后端版本目录与明确视图均只读，不能自行替换回执SHA。 */
  rescuePresentationDirectory:(url:string)=>request<import('./types').RescuePresentationDirectory>('GET',url.replace(/^\/api\/v1/,'')),
  rescuePresentation:(url:string)=>request<import('./types').SystemRescueDisplay>('GET',url.replace(/^\/api\/v1/,'')),
  publishRescuePresentation:(url:string,body:import('./types').RescuePresentationRequest)=>
    request<{task:Task;created:boolean;message_zh:string}>('POST',url.replace(/^\/api\/v1/,''),body),
  acceptanceBundle:(url:string)=>request<import('./types').AcceptanceBundle>('GET',url.replace(/^\/api\/v1/,'')),
  /** 只读取已登记完整包；明确生成仍沿原任务令牌。 */
  acceptanceArchives:(url:string)=>request<import('./types').RescueAcceptanceArchiveDirectory>('GET',url.replace(/^\/api\/v1/,'')),
  publishAcceptanceArchive:(url:string,body:import('./types').RescueAcceptanceArchiveRequest)=>
    request<{task:Task;created:boolean;message_zh:string}>('POST',url.replace(/^\/api\/v1/,''),body),
  /** 后端登记的同源证据地址；仅发GET，不从浏览器传入路径或科学参数。 */
  rescueEvidence:(url:string)=>request<import('./types').RescueEvidence>('GET',url.replace(/^\/api\/v1/,'')),
  /** 用户只提交稳定对象选择，焦点格子与色标由后端返回。 */
  rescueFocus:(url:string,inputKey:string,compounds:string[],targets:string[])=>
    request<{run_id:string;input_key:string;heatmap:import('./types').RescueMatrix;score_range:[number|null,number|null]}>(
      'GET',rescueFocusPath(url,inputKey,compounds,targets)),
  /** 明确展开读取二版入口；实际执行只按返回的显式协议选址，不改请求正文。 */
  receptorRescue:(sid:string)=>request<import('./types').ReceptorRescueInfo>('GET',`/studies/${sid}/analysis-plan/receptor-rescue-v2`),
  executeReceptorRescue:(sid:string,body:import('./types').ReceptorRescueRequest,protocol:'A06.system_rescue.1'|'A06.system_rescue.2'='A06.system_rescue.1')=>
    request<{task:Task;created:boolean;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/${protocol==='A06.system_rescue.2'?'receptor-rescue-v2':'receptor-rescue'}/execute`,body),
  /** 只读目录与明确展示修订，沿用操作令牌；不会重算科学结果或生成Word。 */
  displayRevisions:(sid:string)=>request<import('./types').DisplayRevisionInfo>('GET',`/studies/${sid}/analysis-plan/display-revisions`),
  reviseDisplay:(sid:string,body:import('./types').DisplayRevisionRequest)=>request<import('./types').DisplayRevisionResponse>('POST',`/studies/${sid}/analysis-plan/display-revisions`,body),
  systemExports:(sid:string)=>request<import('./types').SystemExportsInfo>('GET',`/studies/${sid}/analysis-plan/system-exports`),
  exportSystemResults:(sid:string,body:import('./types').SystemExportRequest)=>request<{task:Task;created:boolean;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-exports`,body),
  historicalDiseaseSources:(sid:string)=>request<import('./types').HistoricalDiseaseSourcesInfo>('GET',`/studies/${sid}/analysis-plan/historical-disease-sources`),
  publishHistoricalDiseaseSources:(sid:string,body:Record<string,unknown>)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/historical-disease-sources/publish`,body),
  componentIdentityProbes:(sid:string)=>request<import('./types').ComponentIdentityProbeInfo>('GET',`/studies/${sid}/analysis-plan/component-identity-probes`),
  probeComponentIdentities:(sid:string,body:import('./types').ComponentIdentityProbeRequest)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/component-identity-probes/execute`,body),
  componentIdentityEvidence:(sid:string)=>request<import('./types').ComponentIdentityEvidence>('GET',`/studies/${sid}/analysis-plan/component-identity-evidence`),
  /** 统一批次只读及明确执行，沿用令牌与过期保护。 */
  systemPipeline: (sid:string)=>request<import('./types').SystemPipelineInfo>('GET',`/studies/${sid}/analysis-plan/system-pipeline`),
  systemAcquisition: (sid:string)=>request<import('./types').SystemAcquisitionInfo>('GET',`/studies/${sid}/analysis-plan/system-acquisition`),
  systemDiseaseAcquisition: (sid:string)=>request<import('./types').SystemDiseaseAcquisitionInfo>('GET',`/studies/${sid}/analysis-plan/disease-acquisition`),
  systemDiseaseManualSources:(sid:string)=>request<import('./types').SystemDiseaseManualSourcesInfo>('GET',`/studies/${sid}/analysis-plan/disease-manual-sources`),
  uploadSystemDiseaseManualSource:(sid:string,data:FormData)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/disease-manual-sources`,data),
  acquireSystemDiseaseSources: (sid:string,body:import('./types').SystemAcquisitionRequest)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/disease-acquisition/execute`,body),
  publishSystemDiseaseCandidates: (sid:string,body:import('./types').SystemSourceBindingRequest)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/disease-acquisition/publish`,body),
  acquireSystemSources: (sid:string,body:import('./types').SystemAcquisitionRequest)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-acquisition/execute`,body),
  bindSystemSources: (sid:string,body:import('./types').SystemSourceBindingRequest)=>request<{task:Task;request_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-acquisition/bind`,body),
  startSystemPipeline: (sid:string,body:Record<string,unknown>)=>request<{task:Task;batch_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-pipeline/start`,body),
  continueSystemPipeline: (sid:string,body:{batch_id:string;expected_input_hash:string})=>request<{task:Task;batch_id:string;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-pipeline/continue`,body),
  /** 新版阶段不接旧continue，不接收浏览器科学参数或来源路径。 */
  executePlanStage:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/stages/execute`,body),
  /** 名单只在后台按实际方案生成，客户端不提交科学选择结果。 */
  executePlanCompounds:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a03-selection/execute`,body),
  /** 原后台选择、独立复核和固定输入分别由明确操作调用。 */
  generatePlanReceptors:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a04-selection`,body),
  reviewPlanReceptors:(sid:string,id:string,body:Record<string,unknown>)=>request<{review:unknown}>('POST',`/studies/${sid}/analysis-plan/a04-selection/${id}/reviews`,body),
  savePlanPreparationInput:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a06-preparation-input`,body),
  /** 明确准备只绑定本批输入和版本，不从浏览器接收科学参数或文件路径。 */
  startPlanPreparation:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/preparation-ui`,body),
  /** 新版富集实际使用不可变方案，浏览器不传统计参数或结果。 */
  runPlanA05:(sid:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a05`,body),
  savePlanA05Display:(sid:string,action:'prepare'|'confirm',body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a05-display/${action}`,body),
  /** 明确核对同批归档，不能上传passed标记或人工批准。 */
  executePlanSystemValidation:(sid:string,body:{request_id:string;expected_run_id:string;expected_input_hash:string})=>
    request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/system-validations/execute`,body),
  /** 同批事实和图件由后台重建，浏览器只提交明确生成依据。 */
  generatePlanReport:(sid:string,body:{request_id:string;expected_report_run_id:string|null;expected_input_hash:string;author:string;note:string;confirmed:true})=>
    request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/reports/generate`,body),
  /** 新方案任务独立于旧固定参数获取/整理入口。 */
  acquirePlanA01: (sid:string,body:Record<string,unknown>) => request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a01/acquire`,body),
  publishPlanA01: (sid:string,body:Record<string,unknown>) => request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/analysis-plan/a01/publish`,body),
  /** 口袋GET不执行准备；POST仅留存明确选择并后台复验。 */
  planPockets: (sid: string) => request<import('./types').PlanPocketInfo>('GET', `/studies/${sid}/analysis-plan/a06-pockets`),
  reviewPlanPockets: (sid: string, body: import('./types').PlanPocketRequest) =>
    request<{task?: Task; run_id?: string; created: boolean; message_zh: string}>('POST', `/studies/${sid}/analysis-plan/a06-pockets/reviews`, body),
  /** 共晶参考只读候选与明确选择复核；首次不预选。 */
  a06References: (sid: string) => request<import('./types').ReferenceReviewInfo>('GET', `/studies/${sid}/analysis-plan/a06-references`),
  reviewA06References: (sid: string, body: unknown) =>
    request<{task?: Task; review_id?: string; created: boolean; message_zh: string}>('POST', `/studies/${sid}/analysis-plan/a06-references/reviews`, body),
  /** 已完成参考复核后，明确绑定新版准备版本。 */
  a06ReferencePreparation: (sid: string) => request<import('./types').ReferencePreparationInfo>('GET', `/studies/${sid}/analysis-plan/a06-reference-preparation-v2`),
  bindA06ReferencePreparation: (sid: string, body: unknown) =>
    request<{task?: Task; run_id?: string; created: boolean; message_zh: string}>('POST', `/studies/${sid}/analysis-plan/a06-reference-preparation-v2`, body),
  /** 正式评分只读闸门；不提交评分任务。 */
  a06ScoringReadiness: (sid: string) => request<import('./types').ScoringReadinessInfo>('GET', `/studies/${sid}/analysis-plan/a06-scoring-readiness`),
  /** A06整体复核材料包只读汇总；不代替人工复核。 */
  a06ReviewPacket: (sid: string) => request<import('./types').ReferenceReviewPacket>('GET', `/studies/${sid}/analysis-plan/a06-review-packet`),
  a06ReviewPacketExport: (sid: string) => `/api/v1/studies/${sid}/analysis-plan/a06-review-packet/export.json`,
  validateA06Scoring: (sid: string, body: unknown) => request<import('./types').ScoringValidation>('POST', `/studies/${sid}/analysis-plan/a06-scoring/validate`, body),
  prepareA06Reviewable: (sid: string, body: unknown) => request<{task?:Task;created:boolean;run_id?:string;message_zh:string}>('POST', `/studies/${sid}/analysis-plan/a06-reviewable-preparation`, body),
  executeA06PlanScoring: (sid: string, body: unknown) => request<{task?:Task;created:boolean;run_id?:string;message_zh:string}>('POST', `/studies/${sid}/analysis-plan/a06-scoring`, body),
  a06PlanScoringExport: (sid: string) => `/api/v1/studies/${sid}/analysis-plan/a06-scoring/export.csv`,
  /** 目录和校验均不创建研究、不提交任务。 */
  analysisParameters: () => request<import('./types').AnalysisParameterCatalog>('GET', '/analysis-plans/parameters'),
  validateAnalysisPlan: (specification: {mode: 'standard' | 'personalized'; parameters?: Record<string, import('./types').PlanValue>}) =>
    request<import('./types').AnalysisPlanValidation>('POST', '/analysis-plans/validate', {specification}),
  automaticPairs: (sid:string,batch:string,page=1,q='') => request<import('./types').AutomaticPage<import('./types').AutomaticPair>>('GET',`/studies/${sid}/automatic_docking/${batch}/pairs${qs({page,size:20,q})}`),
  automaticEvidence: (sid:string,batch:string,key:string) => request<import('./types').AutomaticPair>('GET',`/studies/${sid}/automatic_docking/${batch}/pairs/${key}`),
  automaticFiles: (sid:string,batch:string,page=1,q='') => request<import('./types').AutomaticPage<import('./types').AutomaticFile>>('GET',`/studies/${sid}/automatic_docking/${batch}/files${qs({page,size:20,q})}`),
  automaticMatrix: (sid:string,batch:string,compound_ids?:string[],target_ids?:string[]) => request<import('./types').AutomaticMatrixResponse>('GET',`/studies/${sid}/automatic_docking/${batch}/matrix${qs({compound_ids:compound_ids?.join(','),target_ids:target_ids?.join(',')})}`),
  automaticDisplay: (sid:string,body:{expected_a06:string;batch_id:string;compound_ids:string[];target_ids:string[]}) => request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/modules/A06/actions/automatic_display`,body),
  /** 只连接资料，不准备或评分。 */
  automaticConnect: (sid: string, expected_binding: string) => request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A06_PREP/actions/automatic_connect`, {expected_binding}),
  /** 用户主动一次授权，后台连续执行固定策略。 */
  automaticRun: (sid: string, body: import('./types').AutomaticRequest) => request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A06_PREP/actions/automatic_run`, body),
  automaticStart: (sid: string, body: Omit<import('./types').AutomaticRequest, 'expected_connection_id'> & {expected_connection_id: string | null}) => request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A06_PREP/actions/automatic_start`, {...body, continuation_version:'A06.connect_run.1'}),
  /** 核对MeSH后建立独立研究，仅保存登记。 */
  createStudy: (body: import('./types').NewStudyInput) => request<import('./types').CreatedStudy>('POST', '/studies', body),
  preflightPlanStudy: (intake: Omit<import('./types').NewStudyInput,'request_id'>, specification:{mode:'standard'|'personalized';parameters?:Record<string,import('./types').PlanValue>}) =>
    request<import('./types').PlanCreationPreflight>('POST','/analysis-plans/creation/preflight',{intake,specification}),
  createPlanStudy: (body:{request_id:string;preflight_id:string;expected_input_hash:string;confirmed:true}) =>
    request<import('./types').CreatedPlanStudy>('POST','/analysis-plans/creation',body),
  creationPlanExport: (sid:string) => `/api/v1/studies/${sid}/analysis-plan/creation/export.json`,
  /** 明确点击后制作当前确认范围两个首位通路命中图。 */
  rankedPathwayMaps: (sid: string, expected_a05: string) =>
    request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A05/actions/ranked_pathway_maps`, {expected_a05}),
  /** 上传用户制作的PNG/JPEG，后台验证后绑定A06另存。 */
  uploadDockingFigure: (sid: string, body: FormData) =>
    request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A06/actions/figure`, body),
  /** 只整理或汇集明确选中的对接组合。 */
  drawingPackages: (sid: string, action: 'pair_packages' | 'pair_bundle', body: {expected_a06: string; pair_keys: string[]}) =>
    request<{task: Task; message_zh: string}>('POST', `/studies/${sid}/modules/A06/actions/${action}`, body),
  /** 首页研究卡片 */
  studies: () => request<{ items: StudyCard[] }>('GET', '/studies'),
  /** 回收站研究卡片 */
  trash: () => request<{ items: StudyCard[] }>('GET', '/trash'),
  /** 研究页 */
  study: (sid: string) => request<StudyView>('GET', `/studies/${sid}`),
  workspace: (sid: string, moduleId?: string, runId?: string) =>
    request<WorkspaceView>('GET', `/studies/${sid}/workspace${qs({ module_id: moduleId, run_id: runId })}`),
  /** 当前研究只读追溯摘要；完整结果由页面显式下载。 */
  studyTrace: (sid: string) => request<import('./types').TraceSummary>('GET', `/studies/${sid}/trace`),
  /** 模块页；runId 用于查看历史版本 */
  module: (sid: string, mid: string, runId?: string | null) => request<ModuleView>('GET', `/studies/${sid}/modules/${mid}${qs({ run_id: runId })}`),
  /** 运行历史 */
  runs: (sid: string, mid: string) => request<{ items: RunItem[] }>('GET', `/studies/${sid}/modules/${mid}/runs`),
  /** 明细表分页 */
  table: (sid: string, mid: string, name: string, p: { page?: number; size?: number; q?: string; runId?: string | null }) =>
    request<TablePage>('GET', `/studies/${sid}/modules/${mid}/tables/${name}${qs({ page: p.page, size: p.size, q: p.q, run_id: p.runId })}`),
  /** 分库上传；仍经过令牌与统一错误处理 */
  uploadSource: (sid: string, mid: string, body: FormData) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/${mid}/actions/upload`, body),
  /** 保存当前完整疾病范围清单，单独生成待核查版本。 */
  reviewDiseaseScope: (sid: string, body: {expected_a00: string; expected_run: string; expected_staging: string; decisions: {scope_id: string; scope: string}[]; reviewer: string; note: string; confirmed: boolean}) =>
    request<{task: Task; created: boolean; message_zh: string}>('POST', `/studies/${sid}/modules/A02/actions/scope_review`, body),
  /** 显式准备预览或发布标准化结果，整体复核仍独立进行。 */
  normalization: (sid: string, body: {expected_a00: string; expected_a01: string; expected_a02: string; action: 'preview' | 'publish'; stamp?: string; reviewer?: string; note?: string; confirmed?: boolean; accept_omit?: boolean; accept_source_exception?: boolean}) =>
    request<{task: Task; created: boolean; message_zh: string}>('POST', `/studies/${sid}/modules/A02/actions/normalization`, body),
  /** 只重取指定失败来源，绑定当前A00与A02。 */
  retrySources: (sid: string, body: { expected_a00: string; expected_run: string; expected_staging: string; databases: string[]; reason: string }) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/A02/actions/retry_sources`, body),
  /** 整理当前已上传三库，结果停在复核 */
  processSources: (sid: string, body: { expected_a00: string; expected_run: string; expected_staging: string; reason: string }) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/A01/actions/process_sources`, body),
  /** 固定官方来源获取与只读候选预览，当前A02不变。 */
  acquireSources: (sid: string, body: {expected_a00: string; expected_run: string; expected_staging: string; databases: string[]; reason: string}) =>
    request<{task: Task; created: boolean; message_zh: string}>('POST', `/studies/${sid}/modules/A01/actions/acquire_sources`, body),
  mappingPreview: (sid: string, body: {expected_a00: string; expected_run: string; expected_staging: string; databases: string[]; reason: string}) =>
    request<{task: Task; created: boolean; message_zh: string}>('POST', `/studies/${sid}/modules/A02/actions/mapping_preview`, body),
  sourcePreview: (sid: string, id: string, database: string, page=1) =>
    request<import('./types').DiseaseCandidatePage>('GET', `/studies/${sid}/source_previews/${id}${qs({database, page, size:25})}`),
  resolveSources: (sid: string, body: {expected_a00: string; expected_run: string; expected_staging: string; reviewer: string; note: string; confirmed: boolean; confirm_coverage: boolean; omit_unresolved: boolean}) =>
    request<{task: Task; created: boolean; message_zh: string}>('POST', `/studies/${sid}/modules/A01/actions/resolve_sources`, body),
  environment: () => request<{code:{commit:string | null; branch:string | null; dirty:boolean | null}; note_zh:string; references:{label_zh:string; detail_zh:string}[]}>('GET', '/environment'),
  /** 只生成A04，停在复核；不自动运行富集和对接 */
  runPpi: (sid: string, body: { expected_a03: string; expected_a04: string; reason: string }) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/A04/actions/run_ppi`, body),
  /** 人工确认补查方案后生成新的待复核A04 */
  identityPlan: (sid: string, body: import('./types').IdentityPlanRequest) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/A04/actions/identity_plan`, body),
  /** A05人工确认展示范围或图表版式；后台生成新版本，不代签 */
  confirmEnrichmentDisplay: (sid: string, body: import('./types').EnrichmentDisplayRequest) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', `/studies/${sid}/modules/A05/actions/display_confirmation`, body),
  /** 仅生成两梯队名单，不启动对接或代签 */
  dockingCandidates: (sid: string, mid: string, body: { expected_a03: string; expected_a04: string; expected_a04_review: string; reason: string }) =>
    request<{ task: Task; created: boolean; message_zh: string }>('POST', '/studies/' + sid + '/modules/' + mid + '/actions/docking_candidates', body),
  /** 新名单生成待复核版本，保存不等于通过。 */
  saveCompoundSelection:(sid:string,body:unknown)=>request<{task:Task;created:boolean;message_zh:string}>('POST','/studies/'+sid+'/modules/A03_SELECT/actions/selection',body),
  /** 草案校验只返回可确认资格，不执行科学工具。 */
  checkTwoPass:(sid:string,body:unknown)=>request<{items:import('./types').PlanRowCheck[];confirmation:import('./types').TwoPassConfirmation}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/check_two_pass',body),
  saveTwoPassDraft:(sid:string,body:unknown)=>request<{draft:import('./types').TwoPassDraftInfo;message_zh:string}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/two_pass_draft',body),
  saveTwoPass:(sid:string,body:unknown)=>request<{task:Task;created:boolean;message_zh:string}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/two_pass_plan',body),
  uploadDockingMaterial:(sid:string,body:unknown)=>request<{material:import('./types').DockingMaterial;message_zh:string}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/material',body),
  /** 保存本轮核查草案或集中采用，保持令牌和统一错误处理。 */
  saveTrialReview:(sid:string,body:unknown)=>request<{message_zh:string}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/trial_review',body),
  saveCoverageSelection:(sid:string,body:unknown)=>request<{message_zh:string;task?:Task}>('POST','/studies/'+sid+'/modules/A06_PREP/actions/coverage_selection',body),
  /** 单个模块复核 */
  review: (sid: string, mid: string, body: { run_id: string; expected_review_id: string | null; decision: Decision; reviewer: string; note: string; after: 'save' | 'continue' }) =>
    request<ReviewResponse>('POST', `/studies/${sid}/modules/${mid}/reviews`, body),
  /** A01+A02 一次提交 */
  batchReview: (sid: string, body: { reviewer: string; entries: Record<string, { run_id: string; expected_review_id: string | null; action: 'decide' | 'preserve'; decision: Decision | ''; note: string }> }) =>
    request<BatchReviewResponse>('POST', `/studies/${sid}/reviews:batch`, body),
  /** 手动推进到下一人工关口 */
  continue: (sid: string) => request<{ task: Task; created: boolean }>('POST', `/studies/${sid}:continue`, {}),
  /** 移入回收站 */
  trashStudy: (sid: string, body: { operator: string; reason: string; expected_action_id: string | null; confirm: true }) =>
    request<{ action: unknown }>('POST', `/studies/${sid}:trash`, body),
  /** 从回收站恢复 */
  restoreStudy: (sid: string, body: { operator: string; reason: string; expected_action_id: string | null; confirm: true }) =>
    request<{ action: unknown }>('POST', `/studies/${sid}:restore`, body),
  /** 跨研究待办 */
  inbox: async () => {
    // 等本轮React效果登记关键页面读取；仅等当前workspace，不等持续轮询或inbox自身。
    await Promise.resolve();
    const pages = [...pendingReads].filter(([path]) => path.split('?')[0].endsWith('/workspace')).map(([, pending]) => pending);
    await Promise.allSettled(pages);
    return request<{ items: GlobalInboxEntry[] }>('GET', '/inbox');
  },
  /** 任务列表 */
  tasks: (p: { study?: string; active?: boolean }) => request<{ items: Task[] }>('GET', `/tasks${qs({ study: p.study, active: p.active ? 1 : undefined })}`),
  /** 任务详情 */
  task: (tid: string) => request<Task>('GET', `/tasks/${tid}`),
  taskScientificProgress:(tid:string)=>request<import('./types').ScientificProgress>('GET',`/tasks/${tid}/scientific-progress`),
  nativeCompute:(sid:string)=>request<import('./types').NativeComputeInfo>('GET',`/studies/${sid}/native-compute`),
  executeNativeCompute:(sid:string,stage:string,body:Record<string,unknown>)=>request<{task:Task;message_zh:string}>('POST',`/studies/${sid}/native-compute/${stage}`,body),
  /** 增量日志 */
  taskLog: (tid: string, offset: number) => request<{ offset: number; next_offset: number; text: string }>('GET', `/tasks/${tid}/log${qs({ offset })}`),
  /** 取消任务 */
  cancelTask: (tid: string) => request<Task>('POST', `/tasks/${tid}:cancel`, {}),
  /** 重试任务 */
  retryTask: (tid: string) => request<{ task: Task; created: boolean }>('POST', `/tasks/${tid}:retry`, {}),
};

/** 归档文件下载地址；inline 为 true 时图片内嵌显示 */
export function fileUrl(sid: string, key: string, inline = false): string {
  return `${API_BASE}/studies/${sid}/files/${encodeURIComponent(key)}${inline ? '?inline=1' : ''}`;
}

/** 将后端返回的下载相对地址转换为开发或生产页面可用地址。 */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${import.meta.env.DEV ? DEV_BASE : ''}${path}`;
}

/** 把任意异常转成中文说明 */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.messageZh; // 接口错误直接用中文说明
  if (e instanceof Error) return e.message; // 其他错误用原始说明
  return String(e); // 兜底
}
