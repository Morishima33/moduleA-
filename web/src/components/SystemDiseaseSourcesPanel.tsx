// 文件用途：疾病五库原件明确获取与补取；只显示服务端事实，不生成科学结果或复核。
import {Alert,Button,Checkbox,Input,Modal,Select,Skeleton,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError,errorText} from '../api/client';
import type {SystemAcquisitionRequest,SystemDiseaseAcquisitionInfo} from '../api/types';
import {useApp} from '../lib/appContext';
import {fmtTime} from '../lib/format';

/** 只在明确点击时提交；旧读取响应忽略，刷新和任务完成不触发获取。 */
export default function SystemDiseaseSourcesPanel({studyId}:{studyId:string}){
 const app=useApp();const [info,setInfo]=useState<SystemDiseaseAcquisitionInfo|null>(null);const [error,setError]=useState('');
 const [notice,setNotice]=useState('');const [author,setAuthor]=useState('');const [note,setNote]=useState('');
 const [confirmed,setConfirmed]=useState(false);const [saving,setSaving]=useState(false);const [tick,setTick]=useState(0);
 const [selected,setSelected]=useState<string>();const binding=useRef('');const request=useRef({signature:'',id:''});
 useEffect(()=>{setInfo(null);setSelected(undefined);setAuthor('');setNote('');setConfirmed(false);setNotice('');request.current={signature:'',id:''};},[studyId]);
 useEffect(()=>{let current=true;api.systemDiseaseAcquisition(studyId).then(value=>{if(!current)return;
  const key=studyId+':'+value.expected_input_hash+':'+value.expected_plan_id;
  if(binding.current!==key){binding.current=key;setConfirmed(false);}
  setInfo(value);setError('');setSelected(old=>value.requests.some(r=>r.request_id===old)?old:value.requests[value.requests.length-1]?.request_id);
 }).catch(e=>{if(current){setInfo(null);setError(errorText(e));setConfirmed(false);}});return()=>{current=false;};
 },[studyId,app.refreshTick,tick]);
 const previous=info?.requests.find(r=>r.request_id===selected);const disabled=saving||!!info?.busy;
 /** 原请求编号在网络异常后保留，版本冲突只刷新；HTTP仍在服务端再次预检。 */
 async function submit(body:SystemAcquisitionRequest){
  setSaving(true);setError('');setNotice('');
  try{const value=await api.acquireSystemDiseaseSources(studyId,body);
   if(value.task.state==='failed')setError(value.task.error_zh??'任务启动失败，请查看后台日志');else{
    setNotice(value.message_zh);app.trackTasks([value.task]);app.openTasks(value.task.task_id);}
   setConfirmed(false);app.bumpRefresh();
  }catch(e){setError(errorText(e));if(e instanceof ApiError&&e.status===409){setConfirmed(false);setTick(n=>n+1);}}
  finally{setSaving(false);}
 }
 /** 当前方案明确开始，不接受客户端疾病词、来源地址或通过标记。 */
 function start(){if(!info?.enabled||!confirmed||!info.expected_a00||!info.expected_plan_id||disabled)return;
  const content={expected_a00:info.expected_a00,expected_plan_id:info.expected_plan_id,expected_input_hash:info.expected_input_hash,
   author:author.trim(),note:note.trim(),confirmed:true as const};const signature=JSON.stringify(content);
  if(request.current.signature!==signature)request.current={signature,id:'diseaseacqreq_'+crypto.randomUUID().replace(/-/g,'')};
  void submit({...content,request_id:request.current.id});
 }
 /** 补取只提交原确认；成功库与受限缺库规则均由后台实际处理。 */
 function retry(){if(!previous?.retry_enabled||disabled)return;
  Modal.confirm({title:'按原确认核验或补取疾病原件',content:<><p>沿用原获取方案、登记人和说明，仅补取可自动获取的缺失来源。</p>
   <p>成功原件会核验复用；GeneCards、OMIM仍需本研究原始资料。补上传后请按当前状态重新确认，原请求不会自动改用新资料。</p>
   <p>此操作不发布疾病候选或批准科研结果。</p></>,okText:'按原确认补取疾病原件',cancelText:'取消',onOk:()=>submit(previous.request)});
 }
 return <section className="card stack" id="system-disease-acquisition"><h2>补齐疾病五库原件</h2>
  <Alert showIcon type="info" message="获取和核验本研究疾病资料" description="公共来源可补取；GeneCards、OMIM需要本研究原始资料。缺失、失败与有效0条分别保留。本区仅保存原件，疾病候选发布仍待接续。"/>
  {error&&<Alert type="error" showIcon message={error} action={<Button onClick={()=>setTick(n=>n+1)}>重新读取疾病原件</Button>}/>}
  {notice&&<Alert type="success" showIcon message={notice}/>}
  {!info?(!error&&<Skeleton active/>):<>
   <p>登记核验的疾病：{info.disease_identity_zh||'尚未完成'}。可自动获取：{info.automatic_databases.join('、')}；需本研究原件：{info.manual_databases.join('、')}。</p>
   {!info.enabled&&<Alert type="warning" showIcon message={info.blockers.join('；')}/>}
   <label>疾病资料获取登记人<Input aria-label="疾病资料获取登记人" value={author} maxLength={2000} disabled={disabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/></label>
   <label>疾病资料获取说明<Input.TextArea aria-label="疾病资料获取说明" value={note} maxLength={2000} disabled={disabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/></label>
   <Checkbox checked={confirmed} disabled={disabled||!info.enabled} onChange={e=>setConfirmed(e.target.checked)}>我已核对本研究登记和方案，确认获取并保存疾病原件</Checkbox>
   <Button type="primary" loading={saving} disabled={disabled||!info.enabled||!confirmed||!author.trim()||!note.trim()} onClick={start}>确认获取疾病原件</Button>
   {!!info.requests.length&&<><h3>疾病原件记录与补取</h3>
    <Select aria-label="疾病原件获取记录" value={selected} style={{width:'100%'}} disabled={saving} onChange={setSelected}
     options={info.requests.map((r,i)=>({value:r.request_id,label:`获取 ${i+1} · ${r.state_label_zh} · ${fmtTime(r.created_at)}`}))}/>
    {previous&&<><p>{previous.state_label_zh}。{previous.message_zh}</p>
     {previous.retry_blockers.length>0&&<Alert type="warning" message={previous.retry_blockers.join('；')}/>}
     <Table size="small" rowKey="database" pagination={false} dataSource={previous.display_sources} scroll={{x:650}}
      columns={[{title:'来源',dataIndex:'database',width:95},{title:'实际状态',dataIndex:'state_label_zh',width:130},
       {title:'原始记录数',dataIndex:'records_text_zh',width:125},{title:'依据或原因',dataIndex:'reason_zh'}]}/>
     <div style={{display:'flex',flexWrap:'wrap',gap:12}}><Button disabled={disabled||!previous.retry_enabled} onClick={retry}>按原确认核验或补取疾病原件</Button>
      <Button onClick={()=>setTick(n=>n+1)}>刷新疾病原件</Button></div>
    </>}
   </>}
  </>}
 </section>;
}
