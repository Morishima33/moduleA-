// 文件用途：展示后端原生执行资格，明确选择后提交；切换研究丢弃迟到响应，不自动计算或批准。
import { Alert, Button, Checkbox, Collapse, Input, Select } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { NativeComputeInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 用户展开后读取本机独立协议，当前任务结束可手动刷新资格。 */
export default function NativeCompute({studyId}:{studyId:string}) {
  const [opened,setOpened]=useState(false);const [version,setVersion]=useState(0);
  const [info,setInfo]=useState<NativeComputeInfo|null>(null);const [error,setError]=useState('');
  useEffect(()=>{let valid=true;setInfo(null);setError('');
    if(opened)void api.nativeCompute(studyId).then(value=>{if(valid)setInfo(value);}).catch(cause=>{if(valid)setError(errorText(cause));});
    return()=>{valid=false;};
  },[studyId,opened,version]);
  return <Collapse onChange={keys=>setOpened(keys.length>0)} items={[{key:'native',label:'Windows / macOS 本机独立运行',children:<div className="stack">
    <Button onClick={()=>setVersion(v=>v+1)}>刷新本机执行条件</Button>
    {error&&<Alert type="error" message={error}/>}
    {info&&<><p>{info.notice_zh}</p>{info.stages.map(stage=><NativeStage key={`${studyId}:${stage.key}:${String(stage.request_template.request_id)}`}
      studyId={studyId} stage={stage} pockets={info.pockets}/>)}</>}
  </div>}]} />;
}

/** 科学条件和恢复决定直接显示后端值；口袋不默认采用，批准仍在原整体复核栏。 */
function NativeStage({studyId,stage,pockets}:{studyId:string;stage:NativeComputeInfo['stages'][number];pockets:NativeComputeInfo['pockets']}) {
  const app=useApp();const valid=useRef(true);
  useEffect(()=>{valid.current=true;return()=>{valid.current=false;};},[]);
  const [author,setAuthor]=useState(String(stage.request_template.author||''));
  const [note,setNote]=useState(String(stage.request_template.note||''));const [confirmed,setConfirmed]=useState(false);
  const [choices,setChoices]=useState<Record<string,string|null>>({});const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');
  /** 明确操作才提交；恢复使用原请求，重复响应不会改变其他研究的页面或任务。 */
  async function execute(){setBusy(true);setMessage('');try{
    const body=stage.resumable?stage.request_template:{...stage.request_template,author,note,confirmed:true,
      ...(stage.key==='qualify'?{decisions:pockets.map(row=>({target_id:row.target_id,pocket_key:choices[row.target_id]??null}))}:{})};
    const result=await api.executeNativeCompute(studyId,stage.key,body);
    if(valid.current){app.trackTasks([result.task]);app.openTasks(result.task.task_id);setMessage(result.message_zh);setConfirmed(false);app.bumpRefresh();}
  }catch(cause){if(valid.current){setMessage(errorText(cause));setConfirmed(false);}}finally{if(valid.current)setBusy(false);}}
  return <section className="stack" style={{borderTop:'1px solid #DCE1E5',paddingTop:12}}><h3>{stage.label_zh}</h3>
    {!stage.enabled&&<Alert type="info" message={stage.blockers_zh.join('；')}/>}
    {stage.resumable&&<Alert type="warning" message="按原请求接续，完整成功对象复用；输入或工具变化将阻断。"/>}
    {stage.key==='qualify'&&!stage.resumable&&pockets.map(row=><div key={row.target_id} className="stack"><strong>{row.symbol} · {row.target_id}</strong><span>{row.reason_zh}</span>
      <Select aria-label={`${row.symbol}本机口袋选择`} value={choices[row.target_id]??''} disabled={!stage.enabled||busy}
        options={[{value:'',label:'不采用预测口袋，保留原状态'},...row.options.map(option=>({value:option.pocket_key,label:`${option.pdb_id||''} · ${option.reason_zh}`,disabled:!option.eligible}))]}
        onChange={value=>{setChoices(c=>({...c,[row.target_id]:value||null}));setConfirmed(false);}}/>
    </div>)}
    <Input aria-label={`${stage.key}本机执行人`} placeholder="实际执行人" maxLength={2000} value={author} disabled={busy||!stage.enabled||stage.resumable} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/>
    <Input.TextArea aria-label={`${stage.key}本机执行依据`} placeholder="本次执行或核查依据" maxLength={2000} value={note} disabled={busy||!stage.enabled||stage.resumable} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/>
    <Checkbox checked={confirmed} disabled={busy||!stage.enabled} onChange={e=>setConfirmed(e.target.checked)}>确认本次明确操作；结果仍须独立科研复核</Checkbox>
    <Button type="primary" loading={busy} disabled={!stage.enabled||!confirmed||!author.trim()||!note.trim()} onClick={execute}>{stage.resumable?'接续原请求':stage.label_zh}</Button>
    {message&&<Alert type="info" message={message}/>}
  </section>;
}
