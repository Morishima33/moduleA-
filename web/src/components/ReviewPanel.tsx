// 文件用途：右侧复核栏。显示与否、可选决定、是否可“继续”全部以接口的 state.code / review 字段为准；
// 提交时带 run_id 与 expected_review_id，版本冲突（409 STALE_VERSION）时提示并自动重新加载。
import { Alert, App as AntApp, Button, Form, Input, Space, Tooltip } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError, api, errorText } from '../api/client';
import type { Decision, ModuleView, Task } from '../api/types';
import { decisionLabel, useApp } from '../lib/appContext';
import { fmtTime } from '../lib/format';
import { stateStyle } from '../lib/theme';
import BatchReviewModal from './BatchReviewModal';
import DecisionPicker from './DecisionPicker';
import {PreparationSource} from './TrialPreparation';

// 契约第 2 节：这些状态不显示复核表单
const NO_FORM = new Set(['idle', 'ready', 'running', 'incomplete', 'failed', 'stale', 'unavailable', 'history']);
// 这些状态已通过，复核栏收起
const SETTLED = new Set(['approved', 'published']);
// 各种不显示表单的状态的说明（对应原型《模块状态样式一览》“复核栏”一行）
const NO_FORM_TEXT: Record<string, string> = {
  idle: '上游尚未通过，本模块还没有可复核的结果。上游通过后系统会自动生成，并停在复核关口。',
  ready: '可以开始。请按本页“操作顺序”完成操作；生成结果后在这里复核。',
  running: '后台运行中。运行结束前不显示复核表单，你可以先去复核其他模块。',
  incomplete: '上次运行没有完整提交（可能中断），目前没有可复核的结果。可在后台任务面板查看日志或重试。',
  failed: '执行失败：这不是“0 条结果”。失败原因见上方说明和后台任务面板；资料补齐或重试后再复核。',
  stale: '已失效：上游已有新版本，本结果不能再交给下游使用。旧文件全部保留可查。',
  unavailable: '归档未就绪，暂不能复核。',
  history: '正在查看历史版本（只读），不能在这里复核。',
};
// 复核人姓名的本机记忆键（仅为方便填写，读写失败不影响功能）
const REVIEWER_KEY = 'modulea.reviewer';

/** 读取上次填写的复核人 */
function rememberedReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) || '';
  } catch {
    return ''; // 浏览器禁止存储时返回空
  }
}

/** 记住复核人 */
function rememberReviewer(name: string) {
  try {
    window.localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    // 忽略存储失败
  }
}

/** 组件参数 */
interface Props {
  studyId: string; // 研究编号
  view: ModuleView; // 模块页数据
  onSaved: (task: Task | null) => void; // 保存成功：刷新数据，有任务时打开任务面板
  onStale: () => void; // 版本冲突：重新加载
}

/** 复核栏 */
export default function ReviewPanel({ studyId, view, onSaved, onStale }: Props) {
  const { session } = useApp(); // 决定中文名
  const { message } = AntApp.useApp(); // 轻提示
  const [form] = Form.useForm(); // 表单
  const [changeOpen, setChangeOpen] = useState(false); // 已通过时是否展开“更改决定”
  const [saving, setSaving] = useState<'save' | 'continue' | null>(null); // 正在提交的方式
  const [error, setError] = useState<string | null>(null); // 提交错误
  const [success, setSuccess] = useState<string | null>(null); // 决定已保存的说明
  const [taskFailed, setTaskFailed] = useState(false); // 保存后后台启动是否失败
  const [batchOpen, setBatchOpen] = useState(false); // 批量复核弹窗
  const decision = Form.useWatch('decision', form) as Decision | undefined; // 当前选择的决定

  const r = view.review; // 复核信息
  const code = view.state.code; // 状态码
  const style = stateStyle(code); // 状态配色

  // 切换模块或运行时重置表单状态
  useEffect(() => {
    setChangeOpen(false);
    setError(null);
    setSuccess(null);
    setTaskFailed(false);
    const prior = view.module.module_id === 'A06' && view.trial_handoff?.active ? view.trial_handoff : undefined;
    form.setFieldsValue({ decision: undefined, note: prior?.note || '', reviewer: rememberedReviewer() || prior?.reviewer || '' });
  }, [view.module.module_id, view.run?.run_id, form]);

  /** 提交单个模块复核 */
  const submit = async (after: 'save' | 'continue') => {
    let v: { decision: Decision; reviewer: string; note: string }; // 表单值
    try {
      v = await form.validateFields(); // 校验必填
    } catch {
      return; // 校验未通过，表单上已有提示
    }
    if (!r.run_id) return; // 没有可复核的运行
    setSaving(after);
    setError(null);
    setSuccess(null);
    setTaskFailed(false);
    try {
      const res = await api.review(studyId, view.module.module_id, {
        run_id: r.run_id, // 本次复核的运行
        expected_review_id: r.expected_review_id, // 并发保护
        decision: v.decision,
        reviewer: v.reviewer.trim(),
        note: v.note.trim(),
        after,
      });
      rememberReviewer(v.reviewer.trim()); // 记住复核人
      form.setFieldsValue({ decision: undefined, note: '' }); // 清空决定与意见，避免重复提交
      setSuccess(res.message_zh); // 显示接口返回的说明
      setTaskFailed(res.task?.state === 'failed'); // 保存成功与任务启动分别显示
      if (res.task?.state === 'failed') message.warning(res.message_zh);
      else message.success(res.message_zh);
      setChangeOpen(false);
      onSaved(res.task); // 刷新数据；有任务时打开任务面板
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_VERSION') {
        // 版本冲突：提示并自动重新加载
        message.warning('状态已更新，已自动刷新，请核对后重新提交。');
        setError('状态已更新，请核对最新内容后重新提交。（' + e.messageZh + '）');
        onStale();
      } else {
        setError(errorText(e)); // 其他错误显示中文说明
      }
    } finally {
      setSaving(null);
    }
  };

  if (view.trial_preparation && !view.historical) {
    const prep = view.trial_preparation;
    return <Box title="本批准备核查来源"><Alert type={prep.active?'success':'warning'} showIcon message={prep.active?'已沿用本批核查，无需重复确认':'准备关联已失效'} description={prep.active?'本页为扩展试算准备核查，不表示全部受体严格质控通过。':prep.reason_zh}/>
      <p>{prep.reviewer} · {fmtTime(prep.reviewed_at)}</p><PreparationSource info={prep}/><Button type="primary" href={prep.result_url}>{prep.active?'前往已确认A06结果':'查看关联A06版本'}</Button></Box>;
  }
  if (view.module.module_id === 'A06_PREP' && view.trial_handoff?.active && !view.historical) {
    return <Box title="本批结果复核入口">
      <Alert type="info" showIcon message="当前225组合在A06结果页复核" description={view.trial_handoff.note_zh}/>
      <Button type="primary" href={view.trial_handoff.review_url}>前往本批A06结果复核</Button>
      <span className="small">此页保留原严格准备记录，当前批次无需重复在这里确认。</span>
    </Box>;
  }
  // —— 不显示表单的状态 ——
  if (NO_FORM.has(code) || view.historical) {
    return (
      <Box title="复核决定">
        <div style={{ padding: '10px 12px', borderRadius: 8, background: style.boxBg, border: `1px solid ${style.boxLine}`, fontSize: 14 }}>
          <strong>{view.state.label_zh}</strong>
          <div>{!view.historical && code === 'stale' && view.module.module_id === 'A07' ? '已失效：上游已有新版本，本版报告需要重新生成并复核。旧文件全部保留可查。' : NO_FORM_TEXT[view.historical ? 'history' : code] || '当前状态不需要复核。'}</div>
        </div>
        {r.current && <CurrentDecision session={session} r={r} moduleId={view.module.module_id} />}
      </Box>
    );
  }

  // —— 研究只读或接口不允许复核 ——
  if (!r.can_review) {
    return (
      <Box title="复核决定">
        <Alert type="info" showIcon message={`当前状态：${view.state.label_zh}`} description={view.state.reason_zh || '当前不能复核（例如研究在回收站中，处于只读状态）。'} />
        {r.current && <CurrentDecision session={session} r={r} moduleId={view.module.module_id} />}
      </Box>
    );
  }

  // —— 已通过：收起，只保留“更改决定” ——
  if ((r.already_approved || SETTLED.has(code)) && !changeOpen) {
    return (
      <Box title={view.state.label_zh} ok>
        {success && <Alert type={taskFailed ? "warning" : "success"} showIcon message={success} />}
        <span style={{ fontSize: 14 }}>{code === 'published' ? '两份正式报告已发布，无需重复操作。' : '本版本已通过复核，无需重复操作。'}</span>
        {r.current && <CurrentDecision session={session} r={r} moduleId={view.module.module_id} />}
        <Button style={{ alignSelf: 'flex-start' }} onClick={() => setChangeOpen(true)}>更改决定</Button>
      </Box>
    );
  }

  // —— 复核表单 ——
  const allowed = new Set(r.allowed_decisions); // 接口允许的决定
  const all: Decision[] = ['approved', 'rejected', 'pending']; // 三个决定的固定顺序
  const canContinue = r.continue.available; // 是否提供“保存并继续”
  return (
    <Box title={view.module.module_id === 'A02' && view.disease_workflow ? '第5步：整体复核' : '复核决定'}>
      <span className="small muted">
        正在复核 {view.module.module_id} · <span className="mono">{view.run?.order_zh}</span>
      </span>
      {/* 已通过后更改决定的提醒 */}
      {changeOpen && (
        <Alert type="warning" showIcon message="更改已通过的决定" description={view.module.module_id === 'A07' ? '请核对本版报告后重新填写复核决定。' : view.downstream.note_zh || '更改决定可能使下游结果失效。'} />
      )}
      {r.current && <CurrentDecision session={session} r={r} moduleId={view.module.module_id} />}
      {view.special.ppi_identity && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="请先完成身份核验" description="待核验清单已在页面标题下展开。这里保存的是整体模块复核意见，不会自动解决身份问题。" />}
      {view.normalization && <Button onClick={() => document.getElementById(view.normalization?.preview ? 'normalization-confirmation' : 'normalization-review')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>{view.normalization.preview ? '前往确认身份处理并生成结果' : '前往基因身份核查'}</Button>}
      <Form form={form} layout="vertical" requiredMark={false} disabled={!!saving}>
        {/* 决定：三选一 */}
        <Form.Item name="decision" label="决定" rules={[{ required: true, message: '请选择决定' }]} style={{ marginBottom: 12 }}>
          <DecisionPicker
            options={all.map((d) => ({ value: d, label: decisionLabel(session, d, view.module.module_id), disabled: !allowed.has(d) }))}
            blockedReason={r.blocked_reason_zh}
          />
        </Form.Item>
        {/* 复核人 */}
        <Form.Item name="reviewer" label="复核人" rules={[{ required: true, whitespace: true, message: '请填写复核人' }]} style={{ marginBottom: 12 }}>
          <Input placeholder="填写姓名" maxLength={60} />
        </Form.Item>
        {/* 意见 */}
        <Form.Item name="note" label="意见" rules={[{ required: true, whitespace: true, message: '请填写意见' }]} style={{ marginBottom: 12 }}>
          <Input.TextArea rows={3} placeholder="简要写明依据或需要修改的地方" maxLength={2000} />
        </Form.Item>
      </Form>
      {error && <Alert type="error" showIcon message={error} />}
      {success && <Alert type={taskFailed ? "warning" : "success"} showIcon message={success} />}
      {/* 提交按钮 */}
      <Space direction="vertical" style={{ width: '100%' }}>
        {canContinue && (
          <Tooltip title={decision && decision !== 'approved' ? '只有选择“通过”时才会继续生成下一步；其他决定请用“仅保存复核决定”。' : undefined}>
            <Button type="primary" block size="large" loading={saving === 'continue'} disabled={!!saving || decision !== 'approved'} onClick={() => submit('continue')}>
              保存并继续到下一人工关口
            </Button>
          </Tooltip>
        )}
        <Button block size="large" type={canContinue ? 'default' : 'primary'} loading={saving === 'save'} disabled={!!saving} onClick={() => submit('save')}>
          仅保存复核决定
        </Button>
        {changeOpen && <Button block type="text" onClick={() => setChangeOpen(false)}>取消更改</Button>}
      </Space>
      <p className="tiny muted" style={{ margin: 0 }}>
        {canContinue ? r.continue.note_zh : r.continue.note_zh ? `本次不提供“保存并继续”。${r.continue.note_zh}` : '本次不提供“保存并继续”。'}
      </p>
      <p className="tiny muted" style={{ margin: 0 }}>{view.module.module_id === 'A07' ? '通过表示本版报告已完成复核，不代表已经证明药效。' : '通过只表示本版本可交给下一步使用，不代表已经证明药效。'}</p>
      {/* A01/A02 一起提交 */}
      {r.batch_with && (
        <>
          <Button block onClick={() => setBatchOpen(true)}>与 {r.batch_with} 一起提交…</Button>
          <BatchReviewModal open={batchOpen} studyId={studyId} current={view} otherId={r.batch_with} onClose={() => setBatchOpen(false)} onSaved={onSaved} onStale={onStale} />
        </>
      )}
    </Box>
  );
}

/** 复核栏外框 */
function Box({ title, ok, children }: { title: string; ok?: boolean; children: ReactNode }) {
  return (
    <section className="card" aria-label="复核决定" style={{ display: 'flex', flexDirection: 'column', gap: 12, borderColor: ok ? '#B9DCC8' : '#DCE1E5' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {ok && (
          <span aria-hidden="true" style={{ width: 28, height: 28, borderRadius: '50%', background: '#E3F2EA', color: '#17633F', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 8.5 6.5 12 13 4.5" /></svg>
          </span>
        )}
        <h2 style={{ margin: 0, fontSize: 17 }}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

/** 当前决定摘要 */
function CurrentDecision({ session, r, moduleId }: { session: ReturnType<typeof useApp>['session']; r: ModuleView['review']; moduleId: string }) {
  const c = r.current!; // 当前复核记录
  return (
    <div className="small" style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '8px 10px', background: '#F6F8F9', borderRadius: 8 }}>
      <span>当前决定：<strong>{decisionLabel(session, c.decision, moduleId)}</strong></span>
      <span className="muted">复核人 {c.reviewer} · {fmtTime(c.created_at)}</span>
      {c.note && <span className="muted" style={{ overflowWrap: 'anywhere' }}>意见：{c.note}</span>}
      <span className="muted" style={{ overflowWrap: 'anywhere' }}>复核编号 <span className="mono">{c.review_id}</span></span>
    </div>
  );
}
