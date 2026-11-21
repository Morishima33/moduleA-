// 文件用途：统一批次确认、明确续做和实际流水；参数及结果状态全部来自服务端。
import {Alert,Button,Collapse,Input,Select,Skeleton,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,errorText,ApiError} from '../api/client';
import type {PipelineParameters,SystemPipelineInfo} from '../api/types';
import {useApp} from '../lib/appContext';
import {hrefFor} from '../lib/route';
import {fmtTime} from '../lib/format';
import SystemAcquisitionPanel from '../components/SystemAcquisitionPanel';
import SystemDiseaseSourcesPanel from '../components/SystemDiseaseSourcesPanel';
import HistoricalDiseaseSources from '../components/HistoricalDiseaseSources';

/** 原参数只读展示；不在浏览器重编译方案或计算科学通过与否。 */
function Parameters({value}:{value:PipelineParameters}){
 return <Collapse items={[{key:'parameters',label:`本批方案参数 · ${value.mode_label_zh??'尚未保存'}`,children:<Table size="small" rowKey="key" pagination={false}
  tableLayout="fixed" dataSource={value.parameters??[]} columns={[{title:'参数',dataIndex:'label_zh',width:'65%'},
   {title:'保存值',width:'35%',render:(_,row)=><span style={{overflowWrap:'anywhere'}}>{`${typeof row.value==='boolean'?(row.value?'是':'否'):row.value}${row.unit?' '+row.unit:''}`}</span>}]} />}]}/>;
}

/** 每次只读刷新忽略旧响应；实际写入只在用户点击时发生。 */
export default function SystemPipelinePage({studyId}:{studyId:string}){
 const app=useApp();const [info,setInfo]=useState<SystemPipelineInfo|null>(null);const [error,setError]=useState('');
 const [notice,setNotice]=useState('');const [author,setAuthor]=useState<string>();
 const [priorAuthor,setPriorAuthor]=useState<{context:string;name:string}>();
 const [saving,setSaving]=useState(false);const [tick,setTick]=useState(0);
 const [selected,setSelected]=useState<string>();const request=useRef({signature:'',id:''});
 useEffect(()=>{let current=true;api.systemPipeline(studyId).then(value=>{if(!current)return;
  setInfo(value);setError('');setSelected(old=>value.batches.some(b=>b.batch_id===old)?old:value.batches[value.batches.length-1]?.batch_id);
 }).catch(e=>{if(current){setError(errorText(e));setInfo(null);}});return()=>{current=false;};
 },[studyId,app.refreshTick,tick]);
 const plan=info?.start.expected_plan_id;const registration=info?.start.expected_a00;
 const authorContext=studyId+':'+plan+':'+registration;
 const canReadDisease=app.session?.capabilities.system_disease_acquisition;
 useEffect(()=>{let current=true;
  if(plan&&registration&&canReadDisease)api.systemDiseaseAcquisition(studyId).then(value=>{
   if(!current)return;
   const saved=[...value.requests].reverse().find(row=>row.plan_id===plan&&row.request.expected_a00===registration);
   setPriorAuthor({context:authorContext,name:saved?.request.author.trim()??''});
  }).catch(()=>undefined);
  return()=>{current=false;};
 },[studyId,plan,registration,authorContext,canReadDisease,app.refreshTick]);
 const batch=info?.batches.find(b=>b.batch_id===selected);const disabled=saving||!!info?.busy;
 const operator=author??(priorAuthor?.context===authorContext?priorAuthor.name:'');
 /** 原一次授权用于首轮，续做只绑定已有批次；409刷新后不自动重交。 */
 async function execute(start:boolean){if(!info||disabled)return;if(start&&(!operator.trim()||!info.start.enabled))return;
  if(!start&&!batch?.continue_enabled)return;setSaving(true);setError('');setNotice('');
  try{let result;
   if(start){const content={expected_a00:info.start.expected_a00,expected_plan_id:info.start.expected_plan_id,
    expected_input_hash:info.start.expected_input_hash,author:operator.trim(),
    note:'在计算页明确开始，沿用本研究已保存方案及已核验资料。',confirmed:true};const signature=JSON.stringify(content);
    if(request.current.signature!==signature)request.current={signature,id:'systembatchreq_'+crypto.randomUUID().replace(/-/g,'')};
    result=await api.startSystemPipeline(studyId,{...content,request_id:request.current.id});
   }else result=await api.continueSystemPipeline(studyId,{batch_id:batch!.batch_id,expected_input_hash:batch!.expected_input_hash});
   if(result.task.state==='failed')setError(result.task.error_zh??'任务启动失败，请查看后台日志');else{
    setNotice(result.message_zh);app.trackTasks([result.task]);app.openTasks(result.task.task_id);}
   if(start)setSelected(result.batch_id);
   app.bumpRefresh();
  }catch(e){setError(errorText(e));if(e instanceof ApiError&&e.status===409)setTick(n=>n+1);}
  finally{setSaving(false);}
 }
 return <main className="stack" style={{maxWidth:1100,margin:'24px auto',padding:'0 16px',overflowWrap:'anywhere'}}>
  <section className="card"><div style={{display:'flex',flexWrap:'wrap',gap:12,justifyContent:'space-between'}}>
   <h1 style={{margin:0,fontSize:24}}>计算工作台</h1><Button href={hrefFor({page:'study',studyId,moduleId:'A00'})}>返回研究登记</Button></div>
   <p>{info?.study_label_zh}</p>{info?.purpose_zh&&<div className="small muted">{info.purpose_zh}</div>}</section>
  {error&&<Alert type="error" showIcon message={error} action={<Button onClick={()=>setTick(n=>n+1)}>重新读取</Button>}/>}
  {notice&&<Alert type="success" showIcon message={notice}/>}
  {!info?(!error&&<Skeleton active/>):<>
   {info.busy&&<Alert type="info" showIcon message="本研究后台任务正在进行" description="任务完成后会刷新实际状态。"/>}
   {!info.busy&&<section className="card stack" id="pipeline-start"><h2>开始计算</h2>
    {!info.start.enabled&&<Alert type="warning" showIcon message="先处理下方所列资料" description={<ul style={{margin:0,paddingLeft:20}}>
      {info.start.blockers.map(reason=><li key={reason}>{reason}</li>)}</ul>}/>}
    <div style={{display:'flex', flexWrap:'wrap',alignItems:'end',gap:12}}>
      <label style={{width:220,maxWidth:'100%'}}>本次操作登记人<Input aria-label="本次操作登记人" value={operator} maxLength={2000} disabled={disabled} onChange={e=>setAuthor(e.target.value)}/></label>
      <Button type="primary" loading={saving} disabled={disabled||!info.start.enabled||!operator.trim()} onClick={()=>execute(true)}>按已保存方案开始计算</Button>
    </div>
    <Parameters value={info.start}/>
   </section>}
   {!info.busy&&!info.start.enabled&&<div className="source-field-grid">
    {app.session?.capabilities.system_acquisition&&<SystemAcquisitionPanel studyId={studyId} compact operator={operator}/>}
    {canReadDisease&&<SystemDiseaseSourcesPanel studyId={studyId} compact/>}
   </div>}
   {!info.busy&&app.session?.capabilities.historical_disease_sources&&<Collapse items={[{key:'history',label:'查看历史疾病资料',children:<HistoricalDiseaseSources studyId={studyId}/>}]} />}
   {info.batches.length>0&&<section className="card stack" id="pipeline-history"><h2>执行记录</h2>
    {info.batches.length>1&&
     <Select aria-label="已有执行批次" value={selected} style={{width:'100%'}} onChange={setSelected} disabled={saving}
      options={info.batches.map((b,i)=>({value:b.batch_id,label:`批次 ${i+1} · ${b.mode_label_zh} · ${b.latest_event?.state_label_zh??'已保存授权'}`}))}/>}
     {batch&&<><Parameters value={batch}/><p>{batch.latest_event?.state_label_zh??'已保存授权，尚无执行流水'}</p>
      {batch.continue_blockers.length>0&&<Alert type="warning" message={batch.continue_blockers.join('；')}/>}
      <div style={{display:'flex',gap:12,flexWrap:'wrap'}}><Button disabled={disabled||!batch.continue_enabled} onClick={()=>execute(false)}>按当前状态续做本批</Button>
       <Button href={hrefFor({page:'study',studyId,moduleId:'A07'})}>查看报告与复核</Button><Button onClick={()=>setTick(n=>n+1)}>刷新实际状态</Button></div>
      <Table size="small" rowKey={(_,i)=>String(i)} dataSource={batch.history} pagination={{pageSize:14}} scroll={{x:650}}
       columns={[{title:'阶段',dataIndex:'stage_label_zh',width:130},{title:'状态',dataIndex:'state_label_zh',width:150},
        {title:'依据或原因',render:(_,row)=>row.error_zh??row.reason_zh??'原一次明确批次授权'},
        {title:'记录时间',render:(_,row)=>fmtTime(row.created_at),width:160}]}/>
     </>}
   </section>}
  </>}
 </main>;
}
