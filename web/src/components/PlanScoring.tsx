// 文件用途：新版同批评分的明确执行入口与结果摘要；科学资格和参数均由后端提供。
import { Alert, Button, Checkbox, Collapse, Descriptions, Input } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { PlanScoringInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 一次明确确认只执行本批，默认不勾选，不更改人工复核决定。 */
export default function PlanScoring({ studyId, moduleId, info }: { studyId: string; moduleId: string; info: PlanScoringInfo }) {
  const app = useApp();
  const [operator, setOperator] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const sequence = useRef(0);
  useEffect(() => {
    sequence.current += 1; setConfirmed(false); setError(''); setMessage(''); setBusy(false);
    return () => { sequence.current += 1; };
  }, [studyId, info.current_run_id, info.expected_preparation_run_id, info.expected_preparation_review_id, app.refreshTick]);
  if (!info.supported) return null;

  /** 仅将版本、执行说明和明确确认提交给后端；禁止网页提供科学参数。 */
  async function submit() {
    if (!info.enabled || busy || !confirmed || !operator.trim() || !note.trim()) return;
    const call = ++sequence.current;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await api.executeA06PlanScoring(studyId, {
        request_id: 'scoreq_' + crypto.randomUUID().replace(/-/g, ''),
        expected_preparation_run_id: info.expected_preparation_run_id,
        expected_preparation_review_id: info.expected_preparation_review_id,
        expected_input_id: info.expected_input_id, expected_a06_run_id: info.current_run_id,
        operator, note, confirmed: true,
      });
      if (result.task) { app.trackTasks([result.task]); app.openTasks(result.task.task_id); }
      if (call === sequence.current) { setMessage(result.message_zh); setConfirmed(false); }
      app.bumpRefresh();
    } catch (e) {
      if (call === sequence.current) { setError(errorText(e)); setConfirmed(false); }
    } finally { if (call === sequence.current) setBusy(false); }
  }

  return <section className="card" id="a06-plan-scoring">
    <h2 style={{ fontSize: 17 }}>新版同批评分</h2>
    <Alert type={info.state === 'completed' ? 'success' : info.enabled ? 'info' : 'warning'} showIcon message={info.reason_zh} />
    {info.parameters && <Descriptions size="small" column={1} style={{ marginTop: 12 }} items={[
      {key:'pairs',label:'固定组合／准备可用／准备NA',children:`${info.pair_count} ／ ${info.ready_pairs} ／ ${info.na_pairs}`},
      {key:'parameters',label:'本批Vina参数',children:`搜索投入 ${info.parameters.exhaustiveness}；最多姿势 ${info.parameters.num_modes}；能量差 ${info.parameters.energy_range_kcal_mol} kcal/mol；随机种子 ${info.parameters.seed}`},
    ]} />}
    {info.summary && <div className="small" id="a06-plan-scoring-summary" style={{ marginTop: 8 }}>
      有效评分 {info.summary.scored_pairs}；评分失败 {info.summary.failed_pairs}；准备NA {info.summary.na_pairs}；
      严格组合 {info.summary.strict_scored_pairs}；探索组合 {info.summary.exploratory_scored_pairs}。
      <div style={{ display:'flex',flexWrap:'wrap',gap:8,marginTop:10 }}>
        <Button href={api.a06PlanScoringExport(studyId)}>下载本批完整评分 CSV</Button>
        {moduleId !== 'A06' && <Button href={`#/studies/${studyId}/A06`}>查看本批评分与人工复核</Button>}
      </div>
    </div>}
    {info.enabled && <Collapse style={{ marginTop: 12 }} items={[{ key:'execute',label:info.state === 'failed' ? '保留失败记录并明确重试' : '明确确认并执行本批评分',children:
      <div className="stack">
        <Input aria-label="评分执行人" placeholder="评分执行人" value={operator} maxLength={2000} disabled={busy}
          onChange={e=>{setOperator(e.target.value);setConfirmed(false);}} />
        <Input.TextArea aria-label="评分执行依据" placeholder="执行依据" value={note} maxLength={2000} disabled={busy}
          onChange={e=>{setNote(e.target.value);setConfirmed(false);}} />
        <Checkbox disabled={busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>确认按本批已复核参数执行，NA保留，评分结果另行复核</Checkbox>
        <Button type="primary" loading={busy} disabled={busy||!confirmed||!operator.trim()||!note.trim()} onClick={()=>void submit()}>执行本批评分</Button>
      </div>,
    }]} />}
    {message && <Alert type="success" style={{ marginTop:10 }} showIcon message={message} />}
    {error && <Alert type="error" style={{ marginTop:10 }} showIcon message={error} />}
  </section>;
}
