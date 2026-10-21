// 准备页仅连接与一次确认；结果页只查看结果和复核，不重复执行表单。
import {Alert, Button, Checkbox, Collapse, Input, Select, Table, message} from 'antd';
import {useEffect, useRef, useState} from 'react';
import type {AutomaticDockingInfo, ReferenceChoice} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';
import {hrefFor} from '../lib/route';
import AutomaticResults from './AutomaticResults';

/** 一次执行确认包含明确参考配体选择；从不预选科研批准。 */
export default function AutomaticDocking({studyId,info,moduleId='A06_PREP',readOnly=false}:{studyId:string;info:AutomaticDockingInfo;moduleId?:string;readOnly?:boolean}) {
  const {bumpRefresh,openTasks}=useApp();
  const [busy,setBusy]=useState(false),[checked,setChecked]=useState(false),[reviewer,setReviewer]=useState(''),[note,setNote]=useState(''),[error,setError]=useState('');
  const [choices,setChoices]=useState<ReferenceChoice[]>([]);
  const requestId=useRef('auto_'+crypto.randomUUID().replace(/-/g,''));
  useEffect(()=>{setChecked(false);setChoices([]);requestId.current='auto_'+crypto.randomUUID().replace(/-/g,'');},[info.expected_connection_id,info.expected_a06]);
  const {connection,latest}=info;
  const usable=!!connection&&connection.summary.connected_compounds>0&&connection.summary.connected_receptors>0;
  const refs=connection?.reference_candidates||[];
  const targetIds=Array.from(new Set(refs.map(r=>r.target_id)));
  async function submit(calculate:boolean) {
    setBusy(true);setError('');
    try{
      const result=calculate?await api.automaticRun(studyId,{expected_binding:info.expected_binding,expected_connection_id:info.expected_connection_id!,expected_a06:info.expected_a06,request_id:requestId.current,policy_version:info.policy.version,reviewer:reviewer.trim(),note:note.trim(),confirmed:checked,...(info.policy.version==='A06.automatic.3'?{reference_choices:choices}:{})}):await api.automaticConnect(studyId,info.expected_binding);
      message.success(result.message_zh);openTasks(result.task.task_id);bumpRefresh();
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  const setup=<div className="stack">
    <p>当前范围：{info.counts.compounds}个成分、{info.counts.receptors}个受体，共{info.counts.pairs}组。连接不计算评分。</p>
    {!info.enabled&&<Alert type="info" showIcon message={info.disabled_reason_zh||'当前不可提交'}/>}
    <Button type={!connection?'primary':'default'} style={{alignSelf:'flex-start',whiteSpace:'normal',height:'auto'}} loading={busy} disabled={!info.enabled} onClick={()=>submit(false)}>{connection?'重新连接资料（生成新版本）':'连接本研究资料'}</Button>
    {connection&&<>
      <Alert type="info" showIcon message={`连接完成：成分${connection.summary.connected_compounds}/${info.counts.compounds}，受体${connection.summary.connected_receptors}/${info.counts.receptors}；异常${connection.summary.exceptions}项。`}/>
      <Collapse items={[{key:'objects',label:'连接对象、构型及集中异常',children:<Table rowKey="id" size="small" scroll={{x:650}} dataSource={connection.objects} columns={[
        {title:'对象',dataIndex:'name'},{title:'状态',render:(_,r)=>({connected:'连接完成',failed:'连接失败',unavailable:'资料待核对'}[r.state]||r.state)},
        {title:'来源与构型',render:(_,r)=>r.cid?`PubChem CID ${r.cid}`:r.structures.map(s=>`${s.pdb_id||s.model_id}／链${s.chains.join(',')}／${s.source_type==='alphafold'?'预测模型':s.pocket==='reference'?'共晶位点':'预测口袋探索'}`).join('；')},{title:'异常原因',dataIndex:'reason_zh'}]}/>},{key:'policy',label:'固定自动策略及适用范围',children:<ul>{info.policy.details_zh.map(t=><li key={t}>{t}</li>)}</ul>} ]}/>
      {!!refs.length&&<Collapse items={[{key:'references',label:'核定共晶参考配体（可选；未核定仍按探索处理）',children:<div className="stack"><p>候选来自本研究原始结构。请依据原文与配体身份核定；选择后仍须实际重对接和环境质控，不能直接标为严格通过。</p>{targetIds.map(id=>{const candidates=refs.filter(r=>r.target_id===id);const chosen=choices.find(c=>c.target_id===id);return <div key={id}><p>{connection.objects.find(o=>o.id===id)?.name||id}</p><Select aria-label={'共晶参考配体 '+id} allowClear style={{width:'100%'}} placeholder="不核定，保留探索路线" value={chosen?`${chosen.candidate_key}|${chosen.reference_key}`:undefined} options={candidates.map(r=>({value:`${r.candidate_key}|${r.reference_key}`,label:`${r.pdb_id}／${r.component_id}／${r.name}：${r.reason_zh}`,disabled:!r.selectable}))} onChange={value=>{setChecked(false);setChoices(old=>{const rest=old.filter(c=>c.target_id!==id);if(!value)return rest;const [candidate_key,reference_key]=value.split('|');return [...rest,{target_id:id,candidate_key,reference_key}];});}}/>{candidates.map(r=><a key={r.reference_key} href={r.source_url} target="_blank" rel="noreferrer" style={{marginRight:12}}>{r.pdb_id}／{r.component_id}来源</a>)}</div>;})}</div>} ]}/>}
      <Input aria-label="执行确认人" placeholder="执行确认人" value={reviewer} onChange={e=>setReviewer(e.target.value)} maxLength={200}/>
      <Input.TextArea aria-label="执行说明" placeholder="执行范围、共晶核定依据与用途说明" value={note} onChange={e=>setNote(e.target.value)} maxLength={2000}/>
      <Checkbox checked={checked} onChange={e=>setChecked(e.target.checked)}>我确认本次范围、上述策略及已选择的参考配体，授权准备、质控、对接和出图；结果另行复核。</Checkbox>
      <Button type="primary" style={{alignSelf:'flex-start',whiteSpace:'normal',height:'auto',padding:10}} loading={busy} disabled={!info.enabled||!usable||!checked||!reviewer.trim()||!note.trim()} onClick={()=>submit(true)}>一次确认并开始计算</Button>
    </>}
  </div>;
  return <section className="card stack" id="module-automatic-docking" style={{scrollMarginTop:90,minWidth:0}}>
    <h2 style={{margin:0}}>{moduleId==='A06_PREP'?'对接准备与执行确认':'分子对接结果'}</h2>
    {error&&<Alert type="error" showIcon message={error}/>}
    {moduleId==='A06_PREP'?<>
      {latest?<><Alert type={latest.state==='completed'?'success':'info'} showIcon message={latest.state==='completed'?'本批计算已完成，准备依据已归档':'本批已有执行记录，请到结果页查看进度及异常'}/><Button type="primary" style={{alignSelf:'flex-start'}} href={hrefFor({page:'study',studyId,moduleId:'A06'})}>前往A06查看结果与复核</Button><Collapse items={[{key:'rerun',label:'重新连接或发起新一轮计算（原批次保留）',children:setup}]}/></>:setup}
    </>:<>{latest?<AutomaticResults key={latest.id} studyId={studyId} latest={latest} readOnly={readOnly}/>:<Alert type="info" message="尚未启动本研究对接，请先完成准备与执行确认。" action={<Button href={hrefFor({page:'study',studyId,moduleId:'A06_PREP'})}>前往准备</Button>}/>}</>}
  </section>;
}
