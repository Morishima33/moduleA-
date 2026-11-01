// 原精确编号补查与不可变凭据历史；不提供身份采用或科研通过入口。
import {Alert,Button,Checkbox,Collapse,Input,Space,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,errorText} from '../api/client';
import type {ComponentIdentityProbeInfo,ComponentIdentityProbeRequest} from '../api/types';
import {useApp} from '../lib/appContext';

/** 显式载入与明确确认后补查，任务完成按真实后台状态重新读取。 */
export default function ComponentIdentityProbes({studyId}:{studyId:string}){
 const app=useApp();const [value,setValue]=useState<ComponentIdentityProbeInfo|null>(null),[error,setError]=useState('');
 const [author,setAuthor]=useState(''),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false),[saving,setSaving]=useState(false),[notice,setNotice]=useState('');
 const [loaded,setLoaded]=useState(false),[tick,setTick]=useState(0);const request=useRef({signature:'',id:''});
 useEffect(()=>{if(!loaded)return;let active=true;setValue(null);setConfirmed(false);
  api.componentIdentityProbes(studyId).then(data=>{if(active){setValue(data);setError('');}}).catch(e=>{if(active)setError(errorText(e));});
  return()=>{active=false;};
 },[studyId,loaded,tick,app.refreshTick]);
 /** 同内容网络重试保留请求号，过期版本只刷新且不自动提交。 */
 async function submit(previous?:ComponentIdentityProbeRequest){if(!value||!confirmed)return;setSaving(true);setError('');
  try{const fields={expected_a01:value.expected_a01!,expected_input_hash:value.expected_input_hash,author,note,confirmed:true as const};
   const signature=JSON.stringify(fields);if(request.current.signature!==signature)request.current={signature,id:'componentprobereq_'+crypto.randomUUID().replace(/-/g,'')};
   const result=await api.probeComponentIdentities(studyId,previous??{...fields,request_id:request.current.id});
   setNotice(result.message_zh);setConfirmed(false);app.trackTasks([result.task]);app.openTasks(result.task.task_id);app.bumpRefresh();
  }catch(e){setError(errorText(e));setConfirmed(false);setTick(n=>n+1);}finally{setSaving(false);}
 }
 const disabled=saving||!!value?.busy;
 return <section className="card stack" id="component-identity-probes"><h2>官方精确编号补查</h2>
  <p>按本版HERB原关系中的编号补查官方详情、HGNC及NCBI。补查只归档凭据，原身份待核和科研复核保持。</p>
  <Button onClick={()=>{setLoaded(true);setTick(n=>n+1);}}>读取补查条件与已归档凭据</Button>
  {error&&<Alert type="error" showIcon message={error}/>} {notice&&<Alert type="info" showIcon message={notice}/>}
  {value&&<><Alert type="info" showIcon message={value.message_zh}/>
   {!!value.blockers.length&&<Alert type="warning" message={value.blockers.join('；')}/>}
   <p>本版可按精确编号补查：{value.targets.map(t=>t.target_id).join('、')||'无'}；历史回执 {value.records.length} 份。</p>
   <label>补查登记人<Input aria-label="补查登记人" value={author} maxLength={2000} disabled={disabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/></label>
   <label>补查说明<Input.TextArea aria-label="补查说明" value={note} maxLength={2000} disabled={disabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/></label>
   <Checkbox checked={confirmed} disabled={disabled||!value.enabled} onChange={e=>setConfirmed(e.target.checked)}>我确认按当前原编号补查并保存官方原文；本操作不采用身份或批准结果</Checkbox>
   <Button type="primary" loading={saving} disabled={disabled||!value.enabled||!confirmed||!author.trim()||!note.trim()} onClick={()=>submit()}>确认补查官方凭据</Button>
   <Collapse items={value.records.map(record=>({key:record.probe_id,label:`${!record.candidate_coverage_complete?'历史凭据缺少原候选补查':record.state==='complete'?'补查凭据已归档':'部分查询失败，成功原文已保留'} · ${record.created_at}`,children:<div className="stack">
    <Alert type={record.state==='complete'?'info':'warning'} message={record.message_zh}/>
    <Alert type={record.candidate_coverage_complete?'info':'warning'} message={record.coverage_message_zh}/>
    <Table size="small" rowKey="target_id" pagination={false} scroll={{x:520}} dataSource={record.rows} columns={[
     {title:'原编号',dataIndex:'target_id'},{title:'来源核对结果（未采用）',dataIndex:'message_zh'},
     {title:'原待核记录数',render:(_,row)=>row.issues.length},
    ]}/>
    <Space wrap>{record.downloads.filter((_,i)=>i===0).map(d=><Button key={d.url} href={d.url}>{d.label_zh}</Button>)}</Space>
    <Collapse items={[{key:'raw',label:'查看逐次查询状态与全部原文下载',children:<div className="stack">
     {record.queries.map((q,i)=><p key={i} style={{overflowWrap:'anywhere'}}>{q.label_zh}：{q.state==='ready'?'原响应已核验':'失败'} · HTTP {q.http_status??'未取得'} · {q.retrieved_at}{q.reused?' · 复用原成功响应':''}{q.error_zh&&' · '+q.error_zh}</p>)}
     <Space wrap>{record.downloads.slice(1).map(d=><Button key={d.url} href={d.url}>{d.label_zh}</Button>)}</Space>
    </div>}]} />
    {record.state==='partial_failure'&&record.request.expected_a01===value.expected_a01&&record.request.expected_input_hash===value.expected_input_hash&&<Button disabled={disabled||!confirmed||!value.enabled} onClick={()=>submit(record.request)}>按原登记人与说明明确重试，仅补未完成查询</Button>}
   </div>}))}/>
  </>}
 </section>;
}
