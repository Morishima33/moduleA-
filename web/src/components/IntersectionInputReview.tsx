// 文件用途：在生成 A03 前一次核对方剂和疾病两侧输入。
import { Alert, Button, Checkbox, Input, Skeleton, Space, Table } from 'antd';
import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import type { A03InputPreview, ModuleView } from '../api/types';
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
  const [preview, setPreview] = useState<A03InputPreview | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  useEffect(() => {
    let current = true;
    Promise.all(['A01', 'A02'].map(id => api.module(studyId, id)))
      .then(items => { if (current) setViews(items); })
      .catch(error => { if (current) { setFailed(true); setFeedback(errorText(error)); } })
      .finally(() => { if (current) setLoaded(true); });
    api.a03InputPreview(studyId).then(result => {
      if (current) setPreview(previous => previous?.token === result.preview?.token ? previous : result.preview);
    }).catch(error => {
      if (current) { setFailed(true); setFeedback(errorText(error)); }
    });
    return () => { current = false; };
  }, [studyId, app.refreshTick]);
  useEffect(() => setAccepted([]), [preview?.token]);
  const allApproved = views.length === 2 && views.every(item => item.review.already_approved);
  const ready = views.length === 2 && views.every(item => item.review.already_approved ||
    (item.review.can_review && item.review.allowed_decisions.includes('approved')));
  const required = (['A01', 'A02'] as const).filter(module => preview?.issues[module].length);
  const canConfirm = preview ? preview.purpose === 'workflow_test' && required.every(module => accepted.includes(module)) : ready;

  async function submit() {
    if (!canConfirm || allApproved || busy || saving || !reviewer.trim() || !note.trim()) return;
    setSaving(true); setFailed(false); setFeedback('');
    try {
      const entries = Object.fromEntries(views.map(view => [view.module.module_id, {
        run_id: view.review.run_id || '', expected_review_id: view.review.expected_review_id,
        action: view.review.already_approved ? 'preserve' as const : 'decide' as const,
        decision: view.review.already_approved ? '' as const : 'approved' as const,
        note: note.trim(),
      }]));
      const result = preview
        ? await api.confirmA03Input(studyId, { token: preview.token, reviewer: reviewer.trim(), note: note.trim(), omit: required, confirmed: true })
        : await api.batchReview(studyId, { reviewer: reviewer.trim(), entries, continue_to_a03: true, expected_plan_id: planId });
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
    {!preview && views.map(view => <div key={view.module.module_id}>
      <strong>{view.module.module_id} · {view.state.label_zh}</strong>
      {view.kpis.length > 0 && <div className="small muted">
        {view.kpis.slice(0, 4).map(item => `${item.label_zh} ${item.text}`).join(' · ')}
      </div>}
      <div>{view.review.blockers?.map(item => item.title_zh).join('、') || view.state.reason_zh}</div>
      <Button size="small" href={hrefFor({ page: 'study', studyId, moduleId: view.module.module_id })}>查看{view.module.title_zh}</Button>
    </div>)}
    {preview && <>
      <p style={{ margin: 0 }}>已按本批原规则核实方剂靶点 {preview.available_targets.A01} 个、疾病靶点 {preview.available_targets.A02} 个。展开下方清单核对仍待处理的条目和依据。</p>
      {required.map(module => <div key={module}>
        <details>
          <summary>{module} · {preview.issues[module].length} 条身份或来源记录待核</summary>
          <EvidenceTable rows={preview.issues[module]} />
        </details>
        {preview.purpose === 'workflow_test' && <Checkbox
          checked={accepted.includes(module)} disabled={busy || saving}
          onChange={event => setAccepted(old => event.target.checked ? [...old, module] : old.filter(item => item !== module))}>
          本次流程测试暂不采用 {module} 上述 {preview.issues[module].length} 条，保留原件与核查依据
        </Checkbox>}
      </div>)}
      {!!preview.issues.scope.length && <details>
        <summary>A02 · {preview.issues.scope.length} 组范围证据尚不足，按原规则暂缓纳入</summary>
        <EvidenceTable rows={preview.issues.scope} scope />
      </details>}
      {preview.purpose !== 'workflow_test' && <Alert type="warning" message="正式研究须补齐身份依据后才能计算交集。" />}
    </>}
    {(ready || preview?.purpose === 'workflow_test') && !allApproved && <Space direction="vertical" style={{ width: '100%' }}>
      <Input aria-label="两侧输入复核人" placeholder="填写复核人" value={reviewer} onChange={event => setReviewer(event.target.value)} maxLength={60} />
      <Input.TextArea aria-label="两侧输入复核依据" placeholder="填写共同的复核依据" value={note} onChange={event => setNote(event.target.value)} maxLength={2000} />
      <Button type="primary" loading={saving} disabled={busy || !canConfirm || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>
        {preview ? '确认处理范围并复算 A03 图表' : '通过两侧输入并生成 A03 图表'}
      </Button>
    </Space>}
    {busy && <p className="small muted">后台正在处理本研究，任务结束后可提交。</p>}
    {feedback && <Alert type={failed ? 'error' : 'info'} showIcon message={feedback} />}
  </section>;
}

const reasons: Record<string, string> = {
  identity_verified_no_hgnc: '已有身份依据，缺 HGNC 对应',
  non_gene_object: '非单个基因',
  unmapped: '尚无可用映射',
  ambiguous_or_conflicting: '存在多候选或身份冲突',
};

function EvidenceTable({rows, scope = false}: {rows: A03InputPreview['issues']['A01']; scope?: boolean}) {
  const parts = (...values: (string | number | undefined)[]) => values.filter(Boolean).join(' · ') || '—';
  return <Table size="small" rowKey={(row, index) => String(row.issue_key || row.issue_id || row.scope_id || index)}
    dataSource={rows} pagination={{pageSize: 10, showSizeChanger: false}} scroll={{x: 670}} columns={[
      {title: '原始条目', render: (_, row) => scope ? parts(row.database, row.disease_term, row.disease_id)
        : parts(row.database, row.raw_symbol, row.raw_id || row.raw_target_id, row.raw_compound_id, row.herb)},
      {title: '原因', render: (_, row) => parts(row.reason_zh || row.reason ||
        reasons[String(row.status || row.identity_status)] || row.status || row.identity_status)},
      {title: '证据定位', render: (_, row) => parts(row.source_ref, row.source_line, row.candidate_ids,
        row.ncbi_gene_id && 'NCBI ' + row.ncbi_gene_id, row.target_name || row.disease_id)},
    ]} />;
}
