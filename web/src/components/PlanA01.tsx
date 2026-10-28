// 文件用途：按本研究方案显式获取与整理A01；资格、参数和缺口均由后端提供。
import { Alert, Button, Checkbox, Collapse, Input, Space } from 'antd';
import { useState } from 'react';
import type { PlanA01Info, Task } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 获取只留原件；整理生成待复核结果，页面加载从不启动任务。 */
export default function PlanA01({ studyId, info }: { studyId: string; info: PlanA01Info }) {
  const app = useApp();
  const [databases, setDatabases] = useState<string[]>(info.missing_databases);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{error:boolean;text:string}|null>(null);
  /** 用户明确点击后提交原版本绑定，失败刷新而不静默改用新草稿。 */
  async function submit(action: 'acquire'|'publish') {
    setBusy(true); setNotice(null);
    try {
      const body = { expected_a00:info.expected_a00, expected_a01:info.expected_a01,
        expected_plan_id:info.expected_plan_id, expected_staging:info.expected_staging, reason };
      const result:{task:Task;message_zh:string} = action === 'acquire'
        ? await api.acquirePlanA01(studyId, {...body, databases}) : await api.publishPlanA01(studyId, body);
      app.trackTasks([result.task]); app.openTasks(result.task.task_id); setConfirmed(false);
      setNotice({error:result.task.state==='failed',text:result.message_zh}); app.bumpRefresh();
    } catch(e) { setNotice({error:true,text:errorText(e)}); setConfirmed(false); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <section className="card" id="plan-a01-tasks">
    <h2>按本研究方案获取与整理三库</h2>
    <p>本批 TCMSP 门槛：OB ≥ {info.parameters.ob_min ?? '待保存方案'}%，DL ≥ {info.parameters.dl_min ?? '待保存方案'}。HERB 不附加 OB/DL；BATMAN 仅采用 known 关系。</p>
    <Alert type="info" showIcon message={info.message_zh}/>
    <p>尚缺原件：{info.missing_databases.join('、') || '三库原件均已归档，仍须科学整理校验'}</p>
    <div className="stack" style={{gap:12,marginTop:12}}>
      <Checkbox.Group aria-label="本方案获取数据库" options={['TCMSP','HERB','BATMAN']} value={databases}
        disabled={busy || !info.acquire_enabled} onChange={v=>{setDatabases(v as string[]);setConfirmed(false);}}/>
      <Input.TextArea aria-label="新方案A01操作依据" placeholder="填写本次获取或整理依据" maxLength={2000} rows={2}
        value={reason} disabled={busy} onChange={e=>{setReason(e.target.value);setConfirmed(false);}}/>
      <Checkbox checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}>已核对当前方案和所选资料，确认执行本次操作；结果另行整体复核</Checkbox>
      <Space wrap>
        <Button type="primary" loading={busy} disabled={!info.acquire_enabled || !databases.length || !confirmed || !reason.trim()}
          onClick={()=>submit('acquire')}>按本方案获取所选库</Button>
        <Button loading={busy} disabled={!info.publish_enabled || !confirmed || !reason.trim()}
          onClick={()=>submit('publish')}>按本方案整理并生成待复核结果</Button>
      </Space>
      {info.acquire_blockers.length>0 && <Alert type="warning" message={'获取条件：'+info.acquire_blockers.join('；')}/>}
      {info.publish_blockers.length>0 && <Alert type="warning" message={'整理条件：'+info.publish_blockers.join('；')}/>}
      {notice && <Alert type={notice.error?'error':'info'} showIcon message={notice.text}/>}
      <Collapse items={[{key:'binding',label:'查看本批方案及来源指纹',children:<p style={{overflowWrap:'anywhere'}}>方案：{info.expected_plan_id || '未保存'}<br/>参数指纹：{info.parameter_hash || '未保存'}<br/>原件清单：{info.expected_staging || '未提供'}</p>}]}/>
    </div>
  </section>;
}
