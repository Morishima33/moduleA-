// 文件用途：访问本机 JSON 接口的唯一出口。负责拼接地址、携带操作令牌、把错误统一转成 ApiError。
import type {
  ApiErrorBody, BatchReviewResponse, Decision, GlobalInboxEntry, ModuleView, ReviewResponse, RunItem,
  Session, StudyCard, StudyView, TablePage, Task,
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

/** 发送请求并解析 JSON；非 2xx 时抛出 ApiError */
async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown, retried = false): Promise<T> {
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

// 各端点的薄封装；路径与契约第 3 节一致
export const api = {
  /** 核对MeSH后建立独立研究，仅保存登记。 */
  createStudy: (body: import('./types').NewStudyInput) => request<import('./types').CreatedStudy>('POST', '/studies', body),
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
  inbox: () => request<{ items: GlobalInboxEntry[] }>('GET', '/inbox'),
  /** 任务列表 */
  tasks: (p: { study?: string; active?: boolean }) => request<{ items: Task[] }>('GET', `/tasks${qs({ study: p.study, active: p.active ? 1 : undefined })}`),
  /** 任务详情 */
  task: (tid: string) => request<Task>('GET', `/tasks/${tid}`),
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

/** 把任意异常转成中文说明 */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.messageZh; // 接口错误直接用中文说明
  if (e instanceof Error) return e.message; // 其他错误用原始说明
  return String(e); // 兜底
}
