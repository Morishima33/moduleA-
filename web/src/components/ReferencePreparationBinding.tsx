// 文件用途：将已完成的共晶参考核查明确绑定到新版准备；只提交用户确认，不自动批准。
import { Alert, App as AntApp, Button, Checkbox, Input, Skeleton, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText, ApiError } from '../api/client';
import type { ReferencePreparationInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 绑定请求只使用服务端返回的同源编号，页面不接受路径或科学参数。 */
export default function ReferencePreparationBinding({ studyId }: { studyId: string }) {
  const app = useApp();
  const { message } = AntApp.useApp();
  const [info, setInfo] = useState<ReferencePreparationInfo | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef({ signature: '', id: '' });

  useEffect(() => {
    let current = true;
    api.a06ReferencePreparation(studyId).then(value => { if (current) { setInfo(value); setError(''); setConfirmed(false); } })
      .catch(e => { if (current) { setInfo(null); setError(errorText(e)); } });
    return () => { current = false; };
  }, [studyId, app.refreshTick]);

  async function submit() {
    if (!info?.enabled || !info.expected_input_id || !info.expected_preparation_run_id || !info.reviews?.[0]?.review_id || !confirmed) return;
    const content = { expected_input_id: info.expected_input_id, expected_preparation_run_id: info.expected_preparation_run_id,
      expected_review_id: info.reviews[0].review_id, reviewer, note, confirmed: true as const };
    const signature = JSON.stringify(content);
    if (signature !== request.current.signature) request.current = { signature, id: 'refprep_' + crypto.randomUUID().replace(/-/g, '') };
    setBusy(true); setError('');
    try {
      const result = await api.bindA06ReferencePreparation(studyId, { ...content, request_id: request.current.id });
      message.success(result.message_zh);
      setConfirmed(false);
      if (result.task) { app.trackTasks([result.task]); app.openTasks(result.task.task_id); }
      app.bumpRefresh();
    } catch (e) {
      setError(errorText(e));
      if (e instanceof ApiError && e.status === 409) setConfirmed(false);
    } finally { setBusy(false); }
  }

  if (error && !info) return <Alert type="error" showIcon message="参考准备状态读取失败" description={error} />;
  if (!info) return <section className="card"><Skeleton active paragraph={{ rows: 2 }} /></section>;
  if (!info.supported) return null;
  if (info.state === 'bound') return <section className="card" id="a06-reference-preparation-binding"><Alert type="success" showIcon message="参考证据已绑定新版准备" description={info.reason_zh} /><Tag color="blue">评分仍关闭</Tag></section>;
  if (!info.enabled) return <section className="card" id="a06-reference-preparation-binding"><Alert type="info" showIcon message={info.reason_zh} description="完成共晶参考复核后，才能绑定新版准备版本。" /></section>;
  return <section className="card stack" id="a06-reference-preparation-binding">
    <h2 style={{ margin: 0, fontSize: 17 }}>复算共晶参考并生成新版准备</h2>
    <Alert type="warning" showIcon message="需要再次明确确认" description="系统将复核参考证据、更新准备矩阵并保留历史；仍不会批准模块或启动成分×受体评分。" />
    {error && <Alert type="error" showIcon message={error} />}
    <Input aria-label="参考准备绑定人" placeholder="实际绑定核查人" value={reviewer} onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} disabled={busy} />
    <Input.TextArea aria-label="参考准备绑定依据" placeholder="填写将参考证据纳入新版准备的依据" value={note} onChange={e => { setNote(e.target.value); setConfirmed(false); }} disabled={busy} />
    <Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={busy}>我已核对参考复核结果，同意生成新版准备版本</Checkbox>
    <Button type="primary" loading={busy} disabled={busy || !confirmed || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>绑定到新版准备</Button>
  </section>;
}
