// 用户明确限定的历史版本例外；绑定当前文件，默认不确认，不批准身份或启动下游。
import {Alert,Button,Checkbox,Collapse,Input,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,errorText} from '../api/client';
import type {HistoricalDiseaseSourcesInfo} from '../api/types';
import {useApp} from '../lib/appContext';
import {fmtTime} from '../lib/format';

/** 只有主动载入才读取条件；明确确认经统一任务入口处理。 */
export default function HistoricalDiseaseSources({studyId}:{studyId:string}){
 const app=useApp();const [loaded,setLoaded]=useState(false),[tick,setTick]=useState(0),[value,setValue]=useState<HistoricalDiseaseSourcesInfo|null>(null);
 const [author,setAuthor]=useState(''),[note,setNote]=useState(''),[decision,setDecision]=useState(''),[confirmed,setConfirmed]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const request=useRef({signature:'',id:''});
 useEffect(()=>{if(!loaded)return;let current=true;setValue(null);setConfirmed(false);
  api.historicalDiseaseSources(studyId).then(data=>{if(current){setValue(data);setError('');}}).catch(e=>{if(current)setError(errorText(e));});return()=>{current=false;};
 },[studyId,app.refreshTick,loaded,tick]);
 async function publish(){if(!value||!value.enabled||!confirmed)return;setSaving(true);setError('');
  try{const body={expected_a00:value.expected_a00!,expected_plan_id:value.expected_plan_id!,expected_input_hash:value.expected_input_hash!,expected_source_hashes:value.expected_source_hashes,author,note,user_decision:decision,confirmed:true};
   const signature=JSON.stringify(body);if(request.current.signature!==signature)request.current={signature,id:'historicaldiseaseq_'+crypto.randomUUID().replace(/-/g,'')};
   const result=await api.publishHistoricalDiseaseSources(studyId,{...body,request_id:request.current.id});setNotice(result.message_zh);setConfirmed(false);app.trackTasks([result.task]);app.openTasks(result.task.task_id);app.bumpRefresh();
  }catch(e){setError(errorText(e));setConfirmed(false);setTick(n=>n+1);}finally{setSaving(false);}
 }
 const disabled=saving||!!value?.busy;
 return <section className="card stack" id="historical-disease-sources"><h2>历史疾病原件的限定版本例外</h2>
  <p>只有用户明确同意后，才能将当前两份“发布版本未知”的旧文件用于本项流程测试。原件不需要重复上传，其他科研关口保持。</p>
  <Button onClick={()=>{setLoaded(true);setTick(n=>n+1);}}>读取历史原件与限定例外</Button>
  {error&&<Alert type="error" showIcon message={error}/>} {notice&&<Alert type="info" showIcon message={notice}/>}
  {value&&<><Alert type="warning" showIcon message={value.notice_zh}/>
   {!!value.blockers.length&&<Alert type="info" message={value.blockers.join('；')}/>}
   <Table size="small" rowKey="database" dataSource={value.sources} pagination={false} scroll={{x:650}} columns={[
    {title:'来源',dataIndex:'database'},{title:'原版本',render:(_,row)=>row.source.version},{title:'原获取日期',render:(_,row)=>row.source.retrieved_at},
    {title:'文件指纹',render:(_,row)=><span title={row.archive.sha256}>{row.archive.sha256.slice(0,16)}…</span>},
   ]}/>
   {value.enabled&&<><label>例外登记人<Input aria-label="例外登记人" value={author} maxLength={2000} disabled={disabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/></label>
    <label>用户明确决定<Input.TextArea aria-label="用户明确决定" value={decision} maxLength={2000} disabled={disabled} onChange={e=>{setDecision(e.target.value);setConfirmed(false);}}/></label>
    <label>例外说明<Input.TextArea aria-label="例外说明" value={note} maxLength={2000} disabled={disabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/></label>
    <Checkbox checked={confirmed} disabled={disabled} onChange={e=>setConfirmed(e.target.checked)}>我确认用户已明确同意，仅允许当前原件用于本项流程测试，版本仍未知且不豁免其他科研关口</Checkbox>
    <Button type="primary" loading={saving} disabled={disabled||!confirmed||!author.trim()||!note.trim()||!decision.trim()} onClick={publish}>记录限定例外并整理历史候选</Button></>}
   <Collapse items={value.records.map(record=>({key:record.request.request_id,label:'已记录的本研究限定例外 · '+fmtTime(record.created_at),children:<div className="stack">
    <Alert type="warning" message={record.notice_zh}/><p>登记人：{record.request.author}</p><p>用户明确决定：{record.request.user_decision}</p><p>说明：{record.request.note}</p>
   </div>}))}/>
  </>}
 </section>;
}
