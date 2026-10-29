// 文件用途：展示新方案成分数量、排序及原A03资料，明确提交后台生成，结果另行复核。
import { Alert, Button, Checkbox, Input, Table } from 'antd';
import { useState } from 'react';
import type { PlanCompoundsInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 只读归档排名和名单，页面不计算选择范围或提交人工批准。 */
export default function PlanCompounds({studyId,info}:{studyId:string;info:PlanCompoundsInfo}) {
 const app=useApp();const [operator,setOperator]=useState('');const [reason,setReason]=useState('');
 const [confirmed,setConfirmed]=useState(false);const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 async function execute(){setBusy(true);setNotice(null);try{
  const r=await api.executePlanCompounds(studyId,{expected_a00:info.expected_a00,expected_a03:info.expected_a03,
   expected_selection:info.expected_selection,expected_plan_id:info.expected_plan_id,expected_input_hash:info.expected_input_hash,
   operator,reason,confirmed:true});
  app.trackTasks([r.task]);app.openTasks(r.task.task_id);setConfirmed(false);setNotice(r.message_zh);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));setConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
 return <section className="card" id="plan-compounds" style={{scrollMarginTop:90}}><h2>按本方案生成成分名单</h2>
  <p>{info.message_zh}</p><p>目标 {info.target_count??'—'} 项，按{info.metric==='mixed_degree'?'混合 Degree':'不同交集靶点数'}排序。<a href={`#/studies/${studyId}/A00`}>查看方案和参数</a></p>
  {!info.enabled&&<Alert type={info.current?'info':'warning'} showIcon message={info.blockers.join('；')}/>}
  {info.identity_pending.length>0&&<Alert type="warning" message={'当前身份或来源待补：'+info.identity_pending.join('、')} description="后台会核查本方案实际入选项，入选项待补时停止，不以低排名对象替换。"/>}
  <h3>原 A03 完整排名（保留原顺序）</h3>
  <Table aria-label="本次A03完整成分排名" size="small" rowKey="compound_id" scroll={{x:650}} pagination={{pageSize:10}} dataSource={info.ranking} columns={[
   {title:'成分',dataIndex:'name'},{title:'药味来源',dataIndex:'herbs',render:(v:string|string[])=>Array.isArray(v)?v.join('、'):v},
   {title:'不同交集靶点数',dataIndex:'intersection_count'},{title:'混合 Degree',dataIndex:'mixed_degree'},
   {title:'交集关系',render:(_,r)=>r.in_network?'有交集关系':'无交集关系，不纳入'}]}/>
  {info.current&&<><h3>本方案已归档名单（{info.current_selected.length} 项）</h3>
   <Table aria-label="本方案已归档成分名单" size="small" rowKey="compound_id" scroll={{x:550}} pagination={{pageSize:10}} dataSource={info.current_selected} columns={[
    {title:'成分',dataIndex:'name'},{title:'排序值',dataIndex:'selection_score'},{title:'纳入原因',dataIndex:'selection_role'}]}/>
   <p>不足目标时按实际数量保存；边界并列可能超过目标。结果是否允许下游使用，以本模块独立复核为准。</p></>}
  <div className="stack" style={{gap:12,marginTop:16}}>
   <Input aria-label="方案成分执行人" placeholder="执行人" maxLength={2000} value={operator} disabled={busy||!info.enabled} onChange={e=>{setOperator(e.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="方案成分执行依据" rows={2} placeholder="核对成分身份、药味来源及本方案后填写执行依据" maxLength={2000} value={reason} disabled={busy||!info.enabled} onChange={e=>{setReason(e.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy||!info.enabled} onChange={e=>setConfirmed(e.target.checked)}>已核对本方案及成分来源，确认生成名单；结果另行复核</Checkbox>
   <Button type="primary" loading={busy} disabled={!info.enabled||!operator.trim()||!reason.trim()||!confirmed} onClick={execute}>生成本方案成分名单（待复核）</Button>
   {notice&&<Alert showIcon message={notice}/>}
  </div>
 </section>;
}
