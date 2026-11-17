// 文件用途：较大资料走同修订完整包后台任务；状态和下载只用后端，不删证据或重算。
import { Alert, Button, Input, Select, Space } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { RescueAcceptanceArchiveDirectory, RescuePresentationRevision } from '../api/types';
import { useApp } from '../lib/appContext';
import { fmtBytes, fmtTime } from '../lib/format';

/** 父级明确核对资料包后才挂载；这里只读目录，生成必须用户填写并点击。 */
export default function RescueAcceptanceArchives({url,runId,revision}:{
  url:string;runId:string;revision:RescuePresentationRevision;
}) {
  const app=useApp();
  const [info,setInfo]=useState<RescueAcceptanceArchiveDirectory|null>(null);
  const [choice,setChoice]=useState('');const pinned=useRef(false);
  const [loading,setLoading]=useState(false);const [error,setError]=useState('');
  const [reload,setReload]=useState(0);const [author,setAuthor]=useState('');
  const [note,setNote]=useState('整理本修订全部原件、图表及固定构象，保留来源和缺失原因。');
  const [submitting,setSubmitting]=useState(false);

  useEffect(()=>{
    let active=true;setLoading(true);setError('');setInfo(null);
    api.acceptanceArchives(url).then(value=>{
      if(!active)return;
      if(value.run_id!==runId||value.revision_id!==revision.revision_id||value.receipt_sha256!==revision.receipt_sha256||
          value.input_key!==revision.input_key||value.matches_input!==revision.matches_input){
        throw new Error('完整包与当前图表版本或适用状态不同，请刷新图表版本。');
      }
      setInfo(value);if(!pinned.current)setChoice(value.current?.archive_id??'');
    }).catch(cause=>{if(active)setError(errorText(cause));})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[url,runId,revision.revision_id,revision.receipt_sha256,revision.input_key,revision.matches_input,app.refreshTick,reload]);

  /** 排原重任务；确认的是整理资料，不提交任何科研复核或名称例外。 */
  const generate=async()=>{
    if(!info?.enabled||!revision.matches_input||!info.expected_input_hash||!author.trim()||!note.trim())return;
    setSubmitting(true);setError('');
    try{
      const reply=await api.publishAcceptanceArchive(info.generate_url,{
        request_id:'rescuezipreq_'+crypto.randomUUID().replace(/-/g,''),expected_run_id:runId,
        expected_revision_id:revision.revision_id,expected_revision_sha256:revision.receipt_sha256,
        expected_input_key:revision.input_key,expected_input_hash:info.expected_input_hash,
        author:author.trim(),note:note.trim(),confirmed:true,
      });
      setInfo(null);app.trackTasks([reply.task]);app.openTasks(reply.task.task_id);app.bumpRefresh();
    }catch(cause){setError(errorText(cause));}
    finally{setSubmitting(false);}
  };

  const selected=info?.history.find(item=>item.archive_id===choice);
  return <div style={{marginTop:12,padding:12,border:'1px solid #DCE1E5',borderRadius:8,minWidth:0}}>
    <Space wrap><strong>完整资料包</strong>
      <Button size="small" loading={loading} onClick={()=>setReload(value=>value+1)}>刷新完整包状态</Button>
      {selected&&<Button size="small" href={selected.download_url}>下载完整验收资料ZIP</Button>}
    </Space>
    <p className="small muted">保留所选图表修订的全部原件、名称依据和固定构象；后台整理不重新计算，也不生成Word。</p>
    {loading&&<p role="status">正在核对本修订完整资料包…</p>}
    {info&&info.required_source_bytes!==null&&<p className="small muted">已登记原件大小：{fmtBytes(info.required_source_bytes)}；压缩包大小以生成结果为准。</p>}
    {info&&(info.history.length>1||(!info.current&&info.history.length>0))&&<label style={{display:'flex',flexDirection:'column',gap:4,maxWidth:'100%'}}>已归档完整包
      <Select aria-label="已归档完整包" placeholder="选择明确归档版本" value={choice||undefined}
        style={{width:320,maxWidth:'100%'}} onChange={value=>{pinned.current=true;setChoice(value);}}
        options={info.history.map((item,index)=>({value:item.archive_id,
          label:`完整包 ${index+1} · ${fmtTime(item.created_at)} · ${fmtBytes(item.bytes)}${item.matches_input?'':'（历史）'}`}))}/>
    </label>}
    {selected&&!selected.matches_input&&<Alert type="warning" showIcon message="当前下载历史完整包，仅供追溯，不表示当前输入或科研复核已通过。"/>}
    {info?.enabled&&<div style={{marginTop:10}}>
      <Space wrap style={{maxWidth:'100%'}}>
        <Input aria-label="完整包登记人" placeholder="登记人" value={author} onChange={event=>setAuthor(event.target.value)} style={{width:180}}/>
        <Input aria-label="完整包说明" placeholder="整理说明" value={note} onChange={event=>setNote(event.target.value)} style={{width:280,maxWidth:'100%'}}/>
        <Button size="small" loading={submitting} disabled={!author.trim()||!note.trim()} onClick={generate}>生成完整资料包</Button>
      </Space>
    </div>}
    {info&&!info.enabled&&!info.current&&<p className="small muted">{info.blockers_zh.join('；')}</p>}
    {error&&<Alert type="error" showIcon message={error}/>}
  </div>;
}
