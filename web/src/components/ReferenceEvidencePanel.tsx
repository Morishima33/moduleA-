// 文件用途：展示新版A06共晶候选并提交明确参考核查；不自动选择、不直接批准。
import { Alert, App as AntApp, Button, Checkbox, Collapse, Input, Select, Skeleton, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText, ApiError } from '../api/client';
import type { ReferenceChoice, ReferenceReviewInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 选择只能提交稳定键；候选资格和失败原因全部来自服务端。 */
export default function ReferenceEvidencePanel({ studyId }: { studyId: string }) {
  const app = useApp();
  const { message } = AntApp.useApp();
  const [info, setInfo] = useState<ReferenceReviewInfo | null>(null);
  const [choices, setChoices] = useState<ReferenceChoice[]>([]);
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef({ signature: '', id: '' });

  useEffect(() => {
    let current = true;
    api.a06References(studyId).then(value => {
      if (!current) return;
      setInfo(value);
      const saved = value.saved_reviews?.[0]?.request?.choices || [];
      setChoices(saved);
      setConfirmed(false);
      request.current = { signature: '', id: '' };
      setError('');
    }).catch(e => { if (current) { setInfo(null); setError(errorText(e)); } });
    return () => { current = false; };
  }, [studyId, app.refreshTick]);

  function choose(targetId: string, value?: ReferenceChoice) {
    const selected = value ? [{ target_id: value.target_id, candidate_key: value.candidate_key,
      reference_key: value.reference_key }] : [];
    setChoices(old => [...old.filter(row => row.target_id !== targetId), ...selected]);
    setConfirmed(false);
  }

  async function submit() {
    if (!info?.enabled || !info.expected_input_id || !info.expected_preparation_run_id || !confirmed) return;
    const content = { expected_input_id: info.expected_input_id, expected_preparation_run_id: info.expected_preparation_run_id,
      reviewer, note, confirmed: true as const, choices };
    const signature = JSON.stringify(content);
    if (signature !== request.current.signature) request.current = { signature, id: 'refreq_' + crypto.randomUUID().replace(/-/g, '') };
    setBusy(true); setError('');
    try {
      const result = await api.reviewA06References(studyId, { ...content, request_id: request.current.id });
      message.success(result.message_zh);
      setConfirmed(false);
      if (result.task) { app.trackTasks([result.task]); app.openTasks(result.task.task_id); }
      app.bumpRefresh();
    } catch (e) {
      setError(errorText(e));
      if (e instanceof ApiError && e.status === 409) setConfirmed(false);
    } finally { setBusy(false); }
  }

  if (error && !info) return <Alert type="error" showIcon message="共晶候选读取失败" description={error} />;
  if (!info) return <section className="card"><Skeleton active paragraph={{ rows: 3 }} /></section>;
  if (!info.supported) return null;
  return <section className="card stack" id="a06-reference-evidence">
    <div>
      <h2 style={{ margin: 0, fontSize: 17 }}>共晶参考证据核查</h2>
      <p className="small muted" style={{ marginBottom: 0 }}>{info.reason_zh}</p>
    </div>
    {error && <Alert type="error" showIcon message={error} />}
    {!info.items.length && <Alert type="info" message="当前准备没有可显示的共晶候选" description="保留原准备状态，不自动选择或补入参考配体。" />}
    {info.items.map(row => {
      const chosen = choices.find(item => item.target_id === row.target_id);
      return <div key={row.target_id}>
        <strong>{row.symbol} <span className="small muted">{row.target_id}</span></strong>
        <Select style={{ width: '100%', marginTop: 6 }} disabled={!info.enabled || busy}
          aria-label={`${row.symbol}共晶参考`} value={chosen ? `${chosen.candidate_key}|${chosen.reference_key}` : undefined}
          placeholder="不核定，保留原准备状态" allowClear
          onChange={value => { const candidate = row.options.find(item => `${item.candidate_key}|${item.reference_key}` === value); choose(row.target_id, candidate && candidate.selectable ? candidate : undefined); }}
          options={row.options.map(item => ({ value: `${item.candidate_key}|${item.reference_key}`, disabled: !item.selectable,
            label: `${item.pdb_id} · ${item.component_id} · ${item.name || '未命名'}：${item.reason_zh}` }))} />
        <Collapse size="small" style={{ marginTop: 6 }} items={row.options.map((item, index) => ({ key: String(index), label: <span>{item.pdb_id}／{item.component_id} <Tag color={item.selectable ? 'cyan' : 'default'}>{item.selectable ? '可提交核查' : '暂不可用'}</Tag></span>, children: <div className="small"><p>{item.reason_zh}</p><a href={item.source_url} target="_blank" rel="noreferrer">查看公开结构来源</a></div> }))} />
      </div>;
    })}
    {info.enabled && <div className="stack">
      <Input aria-label="共晶参考核查人" placeholder="实际核查人" value={reviewer} onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} disabled={busy} />
      <Input.TextArea aria-label="共晶参考核查依据" placeholder="填写本轮参考选择依据" value={note} onChange={e => { setNote(e.target.value); setConfirmed(false); }} disabled={busy} />
      <Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={busy}>我已核对候选来源和稳定键，同意提交本次共晶参考核查</Checkbox>
      <Button type="primary" loading={busy} disabled={busy || !confirmed || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>提交共晶参考复核</Button>
    </div>}
  </section>;
}
