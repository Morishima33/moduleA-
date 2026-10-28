// 文件用途：显式请求复验同批准备，随后交给现有人工复核表单决定。
import { Alert, Button, Checkbox, Collapse, Input } from 'antd';
import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import type { ReviewablePreparationInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 只提交资料复验请求；首次不确认，也不代填任何人工复核决定。 */
export default function ReviewablePreparation({ studyId, info }: { studyId: string; info: ReviewablePreparationInfo }) {
  const app = useApp();
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { setConfirmed(false); setMessage(''); setError(''); }, [studyId, info.current_run_id, app.refreshTick]);
  if (!info.supported) return null;

  /** 一次确认只生成待复核准备，后台完成后使用原人工复核表单。 */
  async function submit() {
    if (!info.enabled || !confirmed || !reviewer.trim() || !note.trim() || busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api.prepareA06Reviewable(studyId, {
        expected_preparation_run_id: info.current_run_id, expected_input_id: info.expected_input_id,
        request_id: 'reviewprep_' + crypto.randomUUID().replace(/-/g, ''), reviewer, note, confirmed: true,
      });
      setConfirmed(false); setMessage(value.message_zh);
      if (value.task) { app.trackTasks([value.task]); app.openTasks(value.task.task_id); }
      app.bumpRefresh();
    } catch (e) { setError(errorText(e)); setConfirmed(false); }
    finally { setBusy(false); }
  }

  return <section className="card" id="a06-reviewable-preparation">
    <h2 style={{ fontSize: 17 }}>进入人工整体复核</h2>
    <Alert type={info.state === 'published' ? 'info' : 'warning'} showIcon message={info.reason_zh} />
    {info.enabled && <Collapse style={{ marginTop: 12 }} items={[{ key: 'prepare', label: '复验资料并生成待复核版本', children:
      <div className="stack">
        <Input aria-label="准备复验人" placeholder="准备复验人" value={reviewer} disabled={busy} maxLength={2000}
          onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} />
        <Input.TextArea aria-label="准备复验依据" placeholder="复验依据" value={note} disabled={busy} maxLength={2000}
          onChange={e => { setNote(e.target.value); setConfirmed(false); }} />
        <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>仅复验资料并进入人工复核，不批准或评分</Checkbox>
        <Button type="primary" loading={busy} disabled={busy || !confirmed || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>生成待人工复核版本</Button>
      </div>,
    }]} />}
    {message && <Alert style={{ marginTop: 10 }} type="success" showIcon message={message} />}
    {error && <Alert style={{ marginTop: 10 }} type="error" showIcon message={error} />}
  </section>;
}
