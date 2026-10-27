// 文件用途：独立核查已归档预测口袋，提交明确选择；科学判断全部来自服务端。
import { Alert, App as AntApp, Button, Checkbox, Collapse, Input, Select, Skeleton, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText, ApiError } from '../api/client';
import type { PlanPocketInfo, PlanPocketRequest } from '../api/types';
import { useApp } from '../lib/appContext';
import { hrefFor } from '../lib/route';

/** 参数、证据和选择按研究与准备运行绑定，刷新到新版本时清空未提交确认。 */
export default function PlanPocketPage({studyId}: {studyId: string}) {
  const app = useApp();
  const {message} = AntApp.useApp();
  const [info, setInfo] = useState<PlanPocketInfo | null>(null);
  const [error, setError] = useState('');
  const [choices, setChoices] = useState<Record<string, string | null>>({});
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tick, setTick] = useState(0);
  const binding = useRef('');
  const request = useRef({signature: '', id: ''});

  // 只读GET；新请求或离开页面后忽略旧响应。
  useEffect(() => {
    let current = true;
    api.planPockets(studyId).then(value => {
      if (!current) return;
      const key = `${studyId}:${value.expected_input_id}:${value.expected_preparation_run_id}`;
      if (key !== binding.current) {
        binding.current = key;
        const saved = new Map((value.saved_decisions || []).map(row => [row.target_id, row.pocket_key]));
        setChoices(Object.fromEntries(value.items.map(row => [row.target_id, saved.get(row.target_id) || null])));
        setConfirmed(false);
        request.current = {signature: '', id: ''};
      }
      setInfo(value); setError('');
    }).catch(e => { if (current) { setError(errorText(e)); setInfo(null); setConfirmed(false); } });
    return () => { current = false; };
  }, [studyId, app.refreshTick, tick]);

  /** 一次提交完整清单；同内容网络重试沿用请求号，过期时刷新且不自动重交。 */
  async function submit() {
    if (!info?.enabled || !info.expected_input_id || !info.expected_preparation_run_id || !confirmed) return;
    const content = {expected_input_id: info.expected_input_id,
      expected_preparation_run_id: info.expected_preparation_run_id,
      reviewer, note, confirmed: true as const,
      decisions: info.items.map(row => ({target_id: row.target_id, pocket_key: choices[row.target_id] || null}))};
    const signature = JSON.stringify(content);
    if (signature !== request.current.signature) request.current = {signature, id: 'pocketreq_' + crypto.randomUUID().replace(/-/g, '')};
    const body: PlanPocketRequest = {...content, request_id: request.current.id};
    setSaving(true); setError('');
    try {
      const result = await api.reviewPlanPockets(studyId, body);
      if (result.task?.state === 'failed') {
        setError(result.task.error_zh || '后台启动失败，请查看任务日志');
      } else {
        message.success(result.message_zh);
        setConfirmed(false);
        if (result.task) { app.trackTasks([result.task]); app.openTasks(result.task.task_id); }
        app.bumpRefresh();
      }
    } catch (e) {
      setError(errorText(e));
      if (e instanceof ApiError && e.status === 409) { setConfirmed(false); setTick(n => n + 1); }
    } finally { setSaving(false); }
  }

  return <main className="stack" style={{maxWidth: 1100, margin: '24px auto', padding: '0 16px'}}>
    <section className="card">
      <div style={{display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12}}>
        <h1 style={{margin: 0, fontSize: 24}}>新版预测口袋核查</h1>
        <Button href={hrefFor({page: 'study', studyId, moduleId: 'A06_PREP'})}>返回对接准备</Button>
      </div>
      <p>核查同批结构与两次首位预测，明确采用哪个位点作为探索线索。</p>
      <Alert type="info" showIcon message="本页只保存口袋采用决定，评分仍关闭"
        description="采用预测口袋不代表已经验证真实结合位点。未选口袋的受体按原第二版准备状态保留；修订后保留全部历史。"/>
    </section>
    {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => setTick(n => n + 1)}>重新读取</Button>}/>}
    {!info ? (error ? null : <Skeleton active/>) : !info.supported ? <Alert type="warning" showIcon message={info.reason_zh}/> : <>
      <section className="card" style={{overflowWrap: 'anywhere'}}>
        <Alert type={info.testing ? 'warning' : 'info'} showIcon message={info.study_label_zh} description={info.purpose_zh}/>
        <p className="small muted">当前准备：{info.expected_preparation_run_id}<br/>证据来源：{info.source_preparation_run_id}</p>
        {info.current_summary && <Alert type="info" message={`本版可用组合 ${info.current_summary.ready_pairs}，NA ${info.current_summary.na_pairs}，已评分 ${info.current_summary.scored_pairs}`}
          description={info.current_summary.message_zh}/>}
        {!info.enabled && <Alert type="warning" message={info.reason_zh}/>}
      </section>
      {info.items.map(row => <section className="card" key={row.target_id}>
        <h2 style={{fontSize: 18}}>{row.symbol} <span className="small muted">{row.target_id}</span></h2>
        <p className="small muted">原第二版状态：{row.state} · {row.reason_zh}</p>
        <label htmlFor={`pocket-${row.target_id}`}>本次采用的预测口袋</label>
        <Select id={`pocket-${row.target_id}`} aria-label={`${row.symbol}本次采用的预测口袋`} style={{display: 'block', width: '100%', margin: '8px 0'}}
          disabled={!info.enabled || saving} value={choices[row.target_id] || ''}
          onChange={value => {setChoices(old => ({...old, [row.target_id]: value || null})); setConfirmed(false);}}
          options={[{value: '', label: '按原第二版状态保留（不采用预测口袋）'},
            ...row.options.filter(option => option.pocket_key).map(option => ({value: option.pocket_key!,
              label: `${option.pdb_id} · ${option.eligible ? '证据可采用' : option.reason_zh}`, disabled: !option.eligible}))]}/>
        <Collapse items={row.options.map((option, i) => ({key: String(i), label: <span>{option.pdb_id} · <Tag color={option.eligible ? 'cyan' : 'default'}>{option.eligible ? '证据一致' : '暂不可采用'}</Tag></span>,
          children: <div className="small" style={{overflowWrap: 'anywhere'}}>
            <p>{option.reason_zh}</p><p>UniProt：{option.uniprot || '—'}；链：{option.chains?.join(', ') || '—'}</p>
            <p>预测残基：{option.mapped_residues?.join(' ') || '—'}</p>
            <p>搜索盒中心：{option.box?.center.join(', ') || '—'}；尺寸：{option.box?.size.join(', ') || '—'} Å</p>
            <p>口袋指纹：{option.pocket_key || '未形成'}</p>
            {option.prediction_files?.map(file => <p key={file.path}>原始预测：{file.path}<br/>SHA-256：{file.sha256}</p>)}
          </div>}))}/>
      </section>)}
      <section className="card stack">
        <label>实际核查人<Input aria-label="实际核查人" value={reviewer} maxLength={2000} onChange={e => {setReviewer(e.target.value); setConfirmed(false);}} disabled={!info.enabled || saving}/></label>
        <label>核查依据<Input.TextArea aria-label="核查依据" value={note} maxLength={2000} onChange={e => {setNote(e.target.value); setConfirmed(false);}} disabled={!info.enabled || saving}/></label>
        <Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={!info.enabled || saving}>我已核对本次选择及证据，同意按上述清单保存探索位点决定</Checkbox>
        <Button type="primary" loading={saving} disabled={!info.enabled || !confirmed || !reviewer.trim() || !note.trim()}
          onClick={() => void submit()}>保存口袋决定并复验</Button>
      </section>
    </>}
  </main>;
}
