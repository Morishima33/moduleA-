// 文件用途：同批双报告的明确生成与实际历史下载；界面不编写科学结论或默认批准。
import {Alert,Button,Checkbox,Input,Table} from 'antd';
import {useState} from 'react';
import type {PlanReportsInfo} from '../api/types';
import {api,errorText} from '../api/client';
import {useApp} from '../lib/appContext';

/** 就绪条件、历史及复核状态由后端给出，确认默认不勾选。 */
export default function PlanReports({studyId,info}:{studyId:string;info:PlanReportsInfo}){
 const app=useApp();const [author,setAuthor]=useState('');const [note,setNote]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 /** 本次明确请求绑定实际当前报告和科学输入，过期仅刷新，不自动重提。 */
 async function generate(){setBusy(true);setNotice(null);try{
  const result=await api.generatePlanReport(studyId,{request_id:'planreportreq_'+crypto.randomUUID().replace(/-/g,''),
   expected_report_run_id:info.expected_report_run_id,expected_input_hash:info.expected_input_hash,author,note,confirmed:true});
  app.trackTasks([result.task]);app.openTasks(result.task.task_id);setNotice(result.message_zh);app.bumpRefresh();
 }catch(error){setNotice(errorText(error));app.bumpRefresh();}finally{setBusy(false);setConfirmed(false);}}
 return <section className="card" id="plan-reports" style={{scrollMarginTop:90}}><h2>本批主报告与简略版</h2>
  <p>按本批已经完成的分析生成报告。空结果、未评分和失败原因如实保留；生成后可统一复核。</p>
  {!!info.blockers.length&&<Alert showIcon type="warning" message="报告条件尚未齐备" description={info.blockers.join('；')}/>}
  <div className="stack" style={{gap:12,marginTop:12}}>
   <Input aria-label="报告登记人" value={author} maxLength={2000} disabled={busy} placeholder="本次报告登记人" onChange={event=>{setAuthor(event.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="报告生成依据" value={note} maxLength={2000} rows={2} disabled={busy} placeholder="填写本次生成报告的依据" onChange={event=>{setNote(event.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy} onChange={event=>setConfirmed(event.target.checked)}>已核对本批资料，确认生成主报告与简略版</Checkbox>
   <Button type="primary" loading={busy} disabled={!info.enabled||!author.trim()||!note.trim()||!confirmed} onClick={generate}>生成本批双报告</Button>
   {notice&&<Alert showIcon message={notice}/>}</div>
  <h3>已归档报告</h3><Table size="small" rowKey="run_id" pagination={{pageSize:5}} scroll={{x:570}} dataSource={[...info.history].reverse()} locale={{emptyText:'本研究尚无已归档的新方案报告'}}
   columns={[{title:'实际状态',dataIndex:'status_zh'},{title:'生成时间',dataIndex:'created_at',render:value=>new Date(value).toLocaleString()},
    {title:'获取文档',render:(_,row)=><div className="stack">{row.downloads.map(file=><a key={file.url} href={file.url} download={file.name}>{file.label_zh}</a>)}</div>}]}/>
 </section>;
}
