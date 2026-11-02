// 文件用途：明确生成同批Excel、CSV及图表，下载已有归档；不提交科学复核或重算评分。
import { Alert, Button, Collapse } from 'antd';
import { useState } from 'react';
import type { SystemExportRecord, SystemExportsInfo } from '../api/types';
import { api, apiUrl, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 文件名及链接完全读取后端已登记回执，不将路径拼成下载权限。 */
function Files({record}:{record:SystemExportRecord}) {
  return <div className="stack" style={{gap:8}}>
    <p className="small muted" style={{overflowWrap:'anywhere'}}>来源：{record.source_module} · {record.source_run_id}</p>
    <div style={{display:'flex',flexWrap:'wrap',gap:8}}>{record.files.map(file=>
      <Button key={file.sha256+file.path} href={apiUrl(file.download_url)}>{file.name}</Button>)}</div>
  </div>;
}

/** 用户点击后只生成已有结果附件，资格与原始范围均由服务端决定。 */
export default function SystemExports({studyId,info}:{studyId:string;info:SystemExportsInfo}) {
  const app=useApp();const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
  const history=info.history.filter(row=>row.export_id!==info.current?.export_id);
  /** 单次明确操作使用新请求号，后台按本批指纹重核并排队。 */
  async function generate() {
    if(!info.enabled||!info.expected_module||!info.expected_run_id||!info.expected_input_hash)return;
    setBusy(true);setNotice(null);
    try {
      const result=await api.exportSystemResults(studyId,{
        request_id:'sysexportreq_'+crypto.randomUUID().replace(/-/g,''),
        expected_module:info.expected_module,expected_run_id:info.expected_run_id,expected_input_hash:info.expected_input_hash,
        author:'网页明确导出操作',note:'按当前已归档矩阵生成同批附件，保留原始精度和NA，不重新计算或签署复核。',confirmed:true});
      app.trackTasks([result.task]);app.openTasks(result.task.task_id);setNotice(result.message_zh);app.bumpRefresh();
    }catch(error){setNotice(errorText(error));app.bumpRefresh();}finally{setBusy(false);}
  }
  return <section id="system-exports" className="card stack" style={{gap:12,scrollMarginTop:90}}>
    <h2>同批结果下载</h2><p>{info.message_zh}</p>
    {info.current?<Files record={info.current}/>:<>
      {info.expected_run_id&&<p className="small muted" style={{overflowWrap:'anywhere'}}>导出来源：{info.expected_module} · {info.expected_run_id}</p>}
      {!info.enabled&&<Alert type="info" showIcon message={info.blockers.join('；')}/>}
      <Button type="primary" loading={busy} disabled={!info.enabled||busy} onClick={generate}>生成本批Excel、CSV与图表</Button>
    </>}
    {notice&&<Alert type="info" showIcon message={notice}/>}
    {history.length>0&&<Collapse items={[{key:'history',label:'已归档的其他导出',children:
      <div className="stack">{history.map(row=><Files key={row.export_id} record={row}/>)}</div>}]} />}
  </section>;
}
