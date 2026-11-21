// 文件用途：统一展示新版阶段的真实依赖、阻塞及明确执行；不计算科学资格。
import { Alert, Button, Input } from 'antd';
import { useState } from 'react';
import type { PlanStagesInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 单次明确操作固定当前输入指纹，结果归档后仍等待对应复核。 */
export default function PlanStages({studyId,info,stage}:{studyId:string;info:PlanStagesInfo;stage:string}) {
 const app=useApp();const [operator,setOperator]=useState('');
 const [reason,setReason]=useState('');const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 async function execute(){if(busy||!operator.trim()||!reason.trim())return;setBusy(true);setNotice(null);try{
  const r=await api.executePlanStage(studyId,{stage,expected_a00:info.expected_a00,expected_plan_id:info.expected_plan_id,
   expected_input_hash:info.expected_input_hash,operator:operator.trim(),reason:reason.trim(),confirmed:true});
  app.trackTasks([r.task]);app.openTasks(r.task.task_id);setNotice(r.message_zh);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));app.bumpRefresh();}finally{setBusy(false);}}
 return <section className="card stack" id="plan-stages" style={{scrollMarginTop:90}} aria-label={`执行 ${stage}`}>
   <div className="source-field-grid">
    <label>执行人<Input aria-label="阶段执行人" maxLength={2000} value={operator} disabled={busy} onChange={e=>setOperator(e.target.value)}/></label>
    <label>执行依据<Input aria-label="阶段执行依据" maxLength={2000} value={reason} disabled={busy} onChange={e=>setReason(e.target.value)}/></label>
   </div>
   <Button type="primary" loading={busy} disabled={!operator.trim()||!reason.trim()} onClick={execute}>按已保存方案执行 {stage}</Button>
   {notice&&<Alert showIcon message={notice}/>}
 </section>;
}
