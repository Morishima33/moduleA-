// 只运行当前已确认交集的A04，跟踪后台任务，不代签或推进其他模块。
import { Alert, Button, message } from 'antd';
import { useState } from 'react';
import type { PpiRunInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

// 后端决定能否运行和当前版本；按钮启动独立A04任务。
export default function PpiRun({ studyId, info }: { studyId: string; info: PpiRunInfo }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  async function start() {
    setBusy(true);
    try {
      const result = await api.runPpi(studyId, { expected_a03: info.expected_a03, expected_a04: info.expected_a04, reason: '用户在A04页面明确启动已确认版式的双分支PPI计算' });
      app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
      if (result.task.state === 'failed') message.error(result.task.error_zh || '后台任务启动失败');
      else message.success(result.message_zh);
    } catch (error) { message.error(errorText(error)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <section className="card">
    <h2 style={{ marginTop: 0 }}>A04 PPI计算</h2>
    <p className="small muted">使用当前已通过的A03交集，生成两分支两轮结果及同源图表；保留历史，完成后等待复核。</p>
    <Button type="primary" disabled={!info.enabled} loading={busy} onClick={start}>{info.expected_a04 ? '重新计算A04（保留历史）' : '开始计算A04'}</Button>
    {!info.enabled && <Alert style={{ marginTop: 12 }} type="info" message={info.disabled_reason_zh} />}
  </section>;
}
