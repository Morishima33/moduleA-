// 文件用途：三库原件明确获取、原请求补取及实际来源状态；不发布科学结果。
import {Alert,Button,Checkbox,Input,Modal,Select,Skeleton,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError,errorText} from '../api/client';
import type {SystemAcquisitionInfo,SystemAcquisitionRequest} from '../api/types';
import {useApp} from '../lib/appContext';
import {fmtTime} from '../lib/format';

/** 读取只忽略过时响应，获取与补取均只由用户的明确操作触发。 */
export default function SystemAcquisitionPanel({studyId}:{studyId:string}){
 const app=useApp();const [info,setInfo]=useState<SystemAcquisitionInfo|null>(null);const [error,setError]=useState('');
 const [author,setAuthor]=useState('');const [note,setNote]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [saving,setSaving]=useState(false);const [notice,setNotice]=useState('');const [tick,setTick]=useState(0);
 const [selected,setSelected]=useState<string>();const binding=useRef('');const request=useRef({signature:'',id:''});
 useEffect(()=>{setInfo(null);setSelected(undefined);setAuthor('');setNote('');setConfirmed(false);setNotice('');request.current={signature:'',id:''};},[studyId]);
 useEffect(()=>{let current=true;api.systemAcquisition(studyId).then(value=>{if(!current)return;
  const key=studyId+':'+value.expected_input_hash+':'+value.expected_plan_id;
  if(binding.current!==key){binding.current=key;setConfirmed(false);}
  setInfo(value);setError('');setSelected(old=>value.requests.some(r=>r.request_id===old)?old:value.requests[value.requests.length-1]?.request_id);
 }).catch(e=>{if(current){setInfo(null);setError(errorText(e));setConfirmed(false);}});return()=>{current=false;};
 },[studyId,app.refreshTick,tick]);
 const previous=info?.requests.find(r=>r.request_id===selected);const disabled=saving||!!info?.busy;
 /** 网络异常保留原请求号；409刷新后不自动重交，也不替换原方案。 */
 async function submit(body:SystemAcquisitionRequest){
  setSaving(true);setError('');setNotice('');
  try{const value=await api.acquireSystemSources(studyId,body);
   if(value.task.state==='failed')setError(value.task.error_zh??'任务启动失败，请查看日志');else{
    setNotice(value.message_zh);app.trackTasks([value.task]);app.openTasks(value.task.task_id);}
   setConfirmed(false);app.bumpRefresh();
  }catch(e){setError(errorText(e));if(e instanceof ApiError&&e.status===409){setConfirmed(false);setTick(n=>n+1);}}
  finally{setSaving(false);}
 }
 /** 新获取固定当前方案和输入；不从页面接收阈值、路径或通过标记。 */
 function start(){if(!info?.enabled||!confirmed||!info.expected_a00||!info.expected_plan_id||disabled)return;
  const content={expected_a00:info.expected_a00,expected_plan_id:info.expected_plan_id,expected_input_hash:info.expected_input_hash,
   author:author.trim(),note:note.trim(),confirmed:true as const};const signature=JSON.stringify(content);
  if(signature!==request.current.signature)request.current={signature,id:'systemacqreq_'+crypto.randomUUID().replace(/-/g,'')};
  void submit({...content,request_id:request.current.id});
 }
 /** 原确认窗口明确展示原门槛；只补缺失来源，不偷换后来草稿或签名。 */
 function retry(){if(!previous?.retry_enabled||disabled)return;
  Modal.confirm({title:'按原确认核验或补取三库原件',content:<><p>原TCMSP门槛：OB≥{previous.screening_parameters.ob_min}%，DL≥{previous.screening_parameters.dl_min}。</p>
   <p>保留原登记人和原说明；已归档的合格库不会重复下载。本次仍只处理原件，不发布科学结果。</p></>,
   okText:'按原确认继续',cancelText:'取消',onOk:()=>submit(previous.request)});
 }
 return <section className="card stack" id="system-source-acquisition"><h2>补齐三库原件</h2>
  <Alert showIcon type="info" message="获取和核验本研究原件" description="成功来源会保留，失败后可以补取。这里尚未自动衔接科学标准化；原件齐全后仍须满足新批次的资料检查。"/>
  {error&&<Alert type="error" showIcon message={error} action={<Button onClick={()=>setTick(n=>n+1)}>重新读取原件状态</Button>}/>}
  {notice&&<Alert type="success" showIcon message={notice}/>}
  {!info?(!error&&<Skeleton active/>):<>
   {!info.enabled&&<Alert type="warning" showIcon message={info.blockers.join('；')}/>}
   {info.screening_parameters&&<p>当前方案获取门槛：TCMSP OB≥{info.screening_parameters.ob_min}%，DL≥{info.screening_parameters.dl_min}；HERB、BATMAN沿用原来源规则。</p>}
   <label>原件获取登记人<Input aria-label="原件获取登记人" value={author} maxLength={2000} disabled={disabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/></label>
   <label>原件获取说明<Input.TextArea aria-label="原件获取说明" value={note} maxLength={2000} disabled={disabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/></label>
   <Checkbox checked={confirmed} disabled={disabled||!info.enabled} onChange={e=>setConfirmed(e.target.checked)}>我已核对当前方案，确认获取并保存本研究三库原件</Checkbox>
   <Button type="primary" loading={saving} disabled={disabled||!info.enabled||!confirmed||!author.trim()||!note.trim()} onClick={start}>确认获取三库原件</Button>
   {!!info.requests.length&&<><h3>原件获取记录与补取</h3><Select aria-label="原件获取记录" value={selected} style={{width:'100%'}} disabled={saving} onChange={setSelected}
    options={info.requests.map((r,i)=>({value:r.request_id,label:`获取 ${i+1} · ${r.state_label_zh} · ${fmtTime(r.created_at)}`}))}/>
    {previous&&<><p>原获取方案：TCMSP OB≥{previous.screening_parameters.ob_min}%，DL≥{previous.screening_parameters.dl_min}。</p>
     <p>{previous.state_label_zh}。{previous.message_zh}</p>
     {previous.retry_blockers.length>0&&<Alert type="warning" message={previous.retry_blockers.join('；')}/>}
     <Table size="small" rowKey="database" pagination={false} dataSource={previous.display_sources} tableLayout="fixed"
      columns={[{title:'来源',dataIndex:'database',width:86},{title:'实际状态',dataIndex:'state_label_zh',width:100},{title:'依据或原因',dataIndex:'reason_zh'}]}/>
     <div style={{display:'flex',flexWrap:'wrap',gap:12}}><Button disabled={disabled||!previous.retry_enabled} onClick={retry}>按原确认核验或补取</Button>
      <Button onClick={()=>setTick(n=>n+1)}>刷新原件状态</Button></div>
    </>}
   </>}
  </>}
 </section>;
}
