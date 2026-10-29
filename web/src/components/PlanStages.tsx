// 文件用途：统一展示新版阶段的真实依赖、阻塞及明确执行；不计算科学资格。
import { Alert, Button, Checkbox, Input, Select, Table } from 'antd';
import { useState } from 'react';
import type { PlanStagesInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 单次明确操作固定当前输入指纹，结果归档后仍等待对应复核。 */
export default function PlanStages({studyId,info}:{studyId:string;info:PlanStagesInfo}) {
 const app=useApp();const [stage,setStage]=useState<string|undefined>(undefined);const [operator,setOperator]=useState('');
 const [reason,setReason]=useState('');const [confirmed,setConfirmed]=useState(false);const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 const selected=info.stages.find(r=>r.stage===stage);
 async function execute(){if(!stage)return;setBusy(true);setNotice(null);try{
  const r=await api.executePlanStage(studyId,{stage,expected_a00:info.expected_a00,expected_plan_id:info.expected_plan_id,
   expected_input_hash:info.expected_input_hash,operator,reason,confirmed:true});
  app.trackTasks([r.task]);app.openTasks(r.task.task_id);setConfirmed(false);setNotice(r.message_zh);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));setConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
 return <section className="card" id="plan-stages" style={{scrollMarginTop:90}}><h2>本方案阶段接续</h2><p>{info.message_zh}</p>
  <p>本方案 STRING 最低置信度：{String(info.parameters['a04.required_score']??'—')}。<a href={`#/studies/${studyId}/A00`}>查看方案和参数</a></p>
  <Table size="small" rowKey="stage" pagination={false} scroll={{x:620}} dataSource={info.stages} columns={[
   {title:'阶段',dataIndex:'stage',width:60},{title:'当前结果',width:140,render:(_,r)=>r.current_run?(r.approved?'已复核通过':r.active?'已归档，待核对':'已失效，历史保留'):'尚无结果'},
   {title:'执行条件',width:420,render:(_,r)=>r.enabled?'可按本方案执行':r.blockers.join('；')}]}/>
  <div className="stack" style={{gap:12,marginTop:16}}>
   <Select aria-label="新方案执行阶段" placeholder="选择要明确执行的就绪阶段" value={stage} disabled={busy} style={{width:'100%'}}
    options={info.stages.map(r=>({value:r.stage,label:r.stage+' · '+(r.enabled?'可执行':'条件未齐'),disabled:!r.enabled}))}
    onChange={v=>{setStage(v);setConfirmed(false);}}/>
   <Input aria-label="阶段执行人" placeholder="执行人" maxLength={2000} value={operator} disabled={busy} onChange={e=>{setOperator(e.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="阶段执行依据" rows={2} maxLength={2000} placeholder="填写本次执行依据" value={reason} disabled={busy} onChange={e=>{setReason(e.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}>已核对本方案和当前输入，确认执行所选阶段；结果另行复核</Checkbox>
   <Button type="primary" loading={busy} disabled={!selected?.enabled||!operator.trim()||!reason.trim()||!confirmed} onClick={execute}>执行已确认阶段</Button>
   {notice&&<Alert showIcon message={notice}/>}
  </div>
 </section>;
}
