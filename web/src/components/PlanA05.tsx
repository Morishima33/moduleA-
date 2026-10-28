// 文件用途：新方案富集明确执行及同批结果表，所有状态和参数由服务器提供。
import { Alert, Button, Checkbox, Collapse, Input, Table } from 'antd';
import { useState } from 'react';
import type { PlanA05Info, FileItem } from '../api/types';
import { api, errorText, fileUrl } from '../api/client';
import { useApp } from '../lib/appContext';

/** 只有主动填写依据并核对才提交任务，页面读取不执行R。 */
export default function PlanA05({studyId,info}:{studyId:string;info:PlanA05Info}) {
  const app=useApp();const [reason,setReason]=useState('');const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
  async function submit(){setBusy(true);setNotice(null);try{
    const r=await api.runPlanA05(studyId,{expected_a00:info.expected_a00,expected_a03:info.expected_a03,
      expected_a05:info.expected_a05,expected_plan_id:info.expected_plan_id,reason});
    app.trackTasks([r.task]);app.openTasks(r.task.task_id);setConfirmed(false);setNotice(r.message_zh);app.bumpRefresh();
  }catch(e){setNotice(errorText(e));setConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
  const p=info.parameters;
  return <section className="card" id="plan-a05-tasks"><h2>按本研究方案执行GO与KEGG富集</h2>
    <Alert type="info" showIcon message={info.message_zh}/>
    <p>纳入：{p.include_go?'GO BP / CC / MF':'GO未纳入'}；{p.include_kegg?'KEGG':'KEGG未纳入'}。条目背景基因数 {p.min_term_size}—{p.max_term_size}，BH p.adjust &lt; {p.adjusted_p_max}。</p>
    <p className="small muted">GO图/表前列：{p.go_plot_top}/{p.go_table_top}；KEGG图/两种排名表前列：{p.kegg_plot_top}/{p.kegg_table_top}。不足按实际数量。</p>
    <Input.TextArea aria-label="新方案A05操作依据" rows={2} maxLength={2000} placeholder="填写本次富集操作依据" value={reason}
      disabled={busy} onChange={e=>{setReason(e.target.value);setConfirmed(false);}}/>
    <p><Checkbox checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}>已核对当前A03与方案，确认执行本次富集；结果另行复核</Checkbox></p>
    <Button type="primary" loading={busy} disabled={!info.enabled||!reason.trim()||!confirmed} onClick={submit}>按本方案执行富集</Button>
    {info.blockers.length>0&&<Alert style={{marginTop:12}} type="warning" message={info.blockers.join('；')}/>}
    {notice&&<Alert style={{marginTop:12}} message={notice} showIcon/>}
    <Collapse style={{marginTop:12}} items={[{key:'binding',label:'本批参数指纹',children:<p style={{overflowWrap:'anywhere'}}>{info.parameter_hash}</p>}]}/>
  </section>;
}

/** 原始前列表可下载全表，未选择类别明确显示，不在前端重筛统计。 */
export function PlanA05Results({data,studyId,files}:{studyId:string;files:FileItem[];data:{groups:{group:string;included:boolean;state_zh:string}[];tables:Record<string,Record<string,unknown>[]>;threshold_zh:string;note_zh:string}}){
 const columns=[{title:'编号',dataIndex:'ID'},{title:'条目名称（官方原名）',dataIndex:'Description'},
   {title:'命中数 Count',dataIndex:'Count'},{title:'BH校正后P值',dataIndex:'p.adjust'}];
 return <section className="card" id="plan-a05-results"><h2>本方案同批富集结果</h2><p>{data.threshold_zh}；{data.note_zh}</p>
  {data.groups.map(g=><div key={g.group}><h3>{g.group} · {g.state_zh}</h3>{g.included?<Table size="small" rowKey="ID" pagination={false} scroll={{x:700}} columns={columns}
    dataSource={data.tables[g.group.toLowerCase()+'_plan_top']} locale={{emptyText:'本类无符合阈值的显著条目；完整统计保留。'}}/>:<Alert message="本方案未纳入此类别，没有执行或检验结果。"/>}</div>)}
  {data.groups.some(g=>g.group==='KEGG'&&g.included)&&<><h3>KEGG · 按命中数排序</h3><Table size="small" rowKey="ID" pagination={false} scroll={{x:700}} columns={columns} dataSource={data.tables.kegg_plan_count_top}/></>}
  <h3>本批归档图件</h3>{files.filter(f=>f.role==='figure'&&f.name.endsWith('.png')).map(f=><figure key={f.key}>
    <a href={fileUrl(studyId,f.key,true)} target="_blank" rel="noreferrer"><img style={{width:'100%',height:'auto'}} src={fileUrl(studyId,f.key,true)} alt={f.name}/></a>
    <figcaption>{f.name} · 按本方案实际数量绘制，点击放大。</figcaption></figure>)}
 </section>;
}
