// 文件用途：在生成 A03 前一次核对方剂和疾病两侧输入。
import { Alert, Button, Input, Skeleton, Space } from 'antd';
import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import type { ModuleView } from '../api/types';
import { useApp } from '../lib/appContext';
import { hrefFor } from '../lib/route';

/** 读取当前两侧，用户一次明确通过后沿后台入口生成图表。 */
export default function IntersectionInputReview({ studyId, planId, busy }: { studyId: string; planId: string; busy: boolean }) {
  const app = useApp();
  const [views, setViews] = useState<ModuleView[]>([]);
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let current = true;
    Promise.all(['A01', 'A02'].map(id => api.module(studyId, id)))
      .then(items => { if (current) setViews(items); })
      .catch(error => { if (current) { setFailed(true); setFeedback(errorText(error)); } })
      .finally(() => { if (current) setLoaded(true); });
    return () => { current = false; };
  }, [studyId]);
  const allApproved = views.length === 2 && views.every(item => item.review.already_approved);
  const ready = views.length === 2 && views.every(item => item.review.already_approved ||
    (item.review.can_review && item.review.allowed_decisions.includes('approved')));

  async function submit() {
    if (!ready || allApproved || busy || saving || !reviewer.trim() || !note.trim()) return;
    setSaving(true); setFailed(false); setFeedback('');
    try {
      const entries = Object.fromEntries(views.map(view => [view.module.module_id, {
        run_id: view.review.run_id || '', expected_review_id: view.review.expected_review_id,
        action: view.review.already_approved ? 'preserve' as const : 'decide' as const,
        decision: view.review.already_approved ? '' as const : 'approved' as const,
        note: note.trim(),
      }]));
      const result = await api.batchReview(studyId, { reviewer: reviewer.trim(), entries, continue_to_a03: true, expected_plan_id: planId });
      setFeedback(result.message_zh);
      if (result.task) { app.trackTasks([result.task]); app.openTasks(result.task.task_id); }
      app.bumpRefresh();
    } catch (error) {
      setFailed(true); setFeedback(errorText(error));
    } finally { setSaving(false); }
  }

  if (allApproved && !feedback) return null;
  return <section className="card stack" aria-label="A03交集输入复核">
    <h2 style={{ margin: 0 }}>核对两侧输入后生成交集图表</h2>
    <p style={{ margin: 0 }}>在这里一次确认方剂靶点和疾病靶点。分别保留验收记录，已有通过的结果直接沿用。</p>
    {!loaded && <Skeleton active paragraph={{ rows: 2 }} />}
    {views.map(view => <div key={view.module.module_id}>
      <strong>{view.module.module_id} · {view.state.label_zh}</strong>
      {view.kpis.length > 0 && <div className="small muted">
        {view.kpis.slice(0, 4).map(item => `${item.label_zh} ${item.text}`).join(' · ')}
      </div>}
      <div>{view.review.blockers?.map(item => item.title_zh).join('、') || view.state.reason_zh}</div>
      <Button size="small" href={hrefFor({ page: 'study', studyId, moduleId: view.module.module_id })}>查看{view.module.title_zh}</Button>
    </div>)}
    {ready && !allApproved && <Space direction="vertical" style={{ width: '100%' }}>
      <Input aria-label="两侧输入复核人" placeholder="填写复核人" value={reviewer} onChange={event => setReviewer(event.target.value)} maxLength={60} />
      <Input.TextArea aria-label="两侧输入复核依据" placeholder="填写共同的复核依据" value={note} onChange={event => setNote(event.target.value)} maxLength={2000} />
      <Button type="primary" loading={saving} disabled={busy || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>
        通过两侧输入并生成 A03 图表
      </Button>
    </Space>}
    {busy && <p className="small muted">后台正在处理本研究，任务结束后可提交。</p>}
    {feedback && <Alert type={failed ? 'error' : 'info'} showIcon message={feedback} />}
  </section>;
}
