// 文件用途：选择同批明确图表修订；读取不写入，生成只走原后台任务和用户明确操作。
import { Alert, Button, Input, Select, Space } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { RescuePresentationDirectory, SystemRescueDisplay } from '../api/types';
import { useApp } from '../lib/appContext';
import { fmtTime } from '../lib/format';
import SystemRescueResults from './SystemRescueResults';

/** 每次选择固定回执；刷新仅更新目录，用户选过的历史版本不会自动跳到新版本。 */
export default function RescuePresentationResults({data}:{data:SystemRescueDisplay}) {
  const app=useApp();
  const [catalog,setCatalog]=useState<RescuePresentationDirectory|null>(null);
  const [choice,setChoice]=useState<string|null>(null);
  const [display,setDisplay]=useState<SystemRescueDisplay|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [reload,setReload]=useState(0);
  const [author,setAuthor]=useState('');
  const [note,setNote]=useState('按当前固定来源整理双语矩阵、图表与名称证据，不改变评分或科研复核。');
  const [submitting,setSubmitting]=useState(false);
  const pinned=useRef(false);

  // 全局仅在任务终态等变化时刷新；不另建持续轮询，不自动生成图表。
  useEffect(()=>{
    if(!data.presentation_url)return;
    let active=true;setLoading(true);setError('');setDisplay(null);
    api.rescuePresentationDirectory(data.presentation_url).then(value=>{
      if(!active)return;
      if(value.run_id!==data.run_id)throw new Error('图表版本与本运行不同，请刷新。');
      setCatalog(value);
      if(!pinned.current)setChoice(value.current?.revision_id??'');
    }).catch(cause=>{if(active){setError(errorText(cause));setDisplay(null);}})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[data.presentation_url,data.run_id,app.refreshTick,reload]);

  const selected=catalog?.history.find(item=>item.revision_id===choice);
  useEffect(()=>{
    if(!data.presentation_url||choice===''){setDisplay(data);return;}
    if(choice===null)return;
    if(!selected){setError('所选图表版本已不可用，请重新读取版本目录。');setDisplay(null);return;}
    let active=true;setDisplay(null);setLoading(true);setError('');
    api.rescuePresentation(selected.view_url).then(value=>{
      if(!active)return;
      const revision=value.presentation_revision;
      if(value.run_id!==data.run_id||!revision||revision.revision_id!==selected.revision_id||
          revision.receipt_sha256!==selected.receipt_sha256||value.input_key!==selected.input_key){
        throw new Error('返回图表与所选版本不同，请重新读取。');
      }
      // 客户端可能共用同URL在途GET；较早回包不能推翻新目录的适用状态。
      if(revision.matches_input!==selected.matches_input)throw new Error('图表适用状态已更新，请刷新图表版本。');
      setDisplay(value);
    }).catch(cause=>{if(active)setError(errorText(cause));})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[choice,selected?.view_url,data,catalog]);

  /** 只在用户点击且后端资格齐备时提交，不保存科研批准或新的名称例外。 */
  const generate=async()=>{
    if(!data.presentation_url||!catalog?.enabled||!catalog.expected_input_hash||!author.trim()||!note.trim())return;
    setSubmitting(true);setError('');
    try{
      const reply=await api.publishRescuePresentation(data.presentation_url,{
        request_id:'rescuereq_'+crypto.randomUUID().replace(/-/g,''),expected_run_id:data.run_id,
        expected_input_hash:catalog.expected_input_hash,author:author.trim(),note:note.trim(),confirmed:true,
      });
      setCatalog({...catalog,enabled:false,blockers_zh:['本批图表整理已提交，请在后台任务中查看进度。']});
      app.trackTasks([reply.task]);app.openTasks(reply.task.task_id);app.bumpRefresh();
    }catch(cause){setError(errorText(cause));}
    finally{setSubmitting(false);}
  };

  if(!data.presentation_url)return <SystemRescueResults data={data}/>;
  const options=[{value:'',label:'原始科学附件（保留）'},...(catalog?.history??[]).map((item,index)=>({
    value:item.revision_id,label:`图表修订 ${index+1} · ${fmtTime(item.created_at)}${
      catalog?.current?.revision_id===item.revision_id?'（当前适用）':item.matches_input?'':'（历史）'}`,
  }))];
  const revision=display?.presentation_revision;
  return <>
    <div className="card" style={{padding:14,minWidth:0}}>
      <Space wrap style={{maxWidth:'100%'}}>
        <label style={{display:'flex',flexDirection:'column',gap:4,maxWidth:'100%'}}>图表版本
          <Select aria-label="图表版本" value={choice??''} options={options} disabled={!catalog}
            style={{width:300,maxWidth:'100%'}} onChange={value=>{pinned.current=true;setChoice(value);}}/>
        </label>
        <Button size="small" loading={loading} onClick={()=>setReload(value=>value+1)}>刷新图表版本</Button>
      </Space>
      {revision&&<p className="small muted">中文名称记录 {revision.name_counts.chinese} 条，其中 {revision.name_counts.source_term_only} 条仅为原来源术语；
        保留原专名 {revision.name_counts.original_proper_name} 条。名称记录数不代表已核实的独立结构数。</p>}
      {revision&&!revision.matches_input&&<Alert type="warning" showIcon message="当前查看历史图表修订，仅供追溯；不代表当前输入或科研复核已通过。"/>}
      {choice===''&&<p className="small muted">正在查看原始科学附件。双语图表会独立保留，原评分、NA和历史文件保持。</p>}
      {catalog?.enabled&&<div style={{marginTop:12}}>
        <Space wrap style={{maxWidth:'100%'}}>
          <Input aria-label="图表登记人" placeholder="登记人" value={author} onChange={event=>setAuthor(event.target.value)} style={{width:180}}/>
          <Input aria-label="图表修订说明" placeholder="修订说明" value={note} onChange={event=>setNote(event.target.value)} style={{width:280,maxWidth:'100%'}}/>
          <Button size="small" loading={submitting} disabled={!author.trim()||!note.trim()} onClick={generate}>生成本批双语图表</Button>
        </Space>
        <p className="small muted">只整理本批已有结果；不重新对接，不生成Word，不提交科研复核。</p>
      </div>}
      {catalog&&!catalog.enabled&&!catalog.current&&<p className="small muted">{catalog.blockers_zh.join('；')}</p>}
      {error&&<Alert type="error" showIcon message={error}/>}
    </div>
    {loading&&!display&&<p role="status">正在读取所选图表版本…</p>}
    {display&&!error&&<SystemRescueResults key={data.run_id+'/'+(revision?.receipt_sha256??'original')} data={display}/>}
  </>;
}
