// 文件用途：明确核对本批已登记验收资料；缺译或原件缺失时展示后端阻塞，不补算。
import { Alert, Button, Space } from 'antd';
import { useState } from 'react';
import { api,errorText } from '../api/client';
import type { AcceptanceBundle as Bundle, RescuePresentationRevision } from '../api/types';
import RescueAcceptanceArchives from './RescueAcceptanceArchives';

/** 用户点击后只读核对；下载按钮只在后端确认本批附件齐备时出现。 */
export default function AcceptanceBundle({url,revision}:{url:string;revision?:RescuePresentationRevision}) {
  const [value,setValue]=useState<Bundle|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const load=async()=>{
    setLoading(true);setError('');setValue(null);
    try{setValue(await api.acceptanceBundle(url));}
    catch(cause){setError(errorText(cause));}
    finally{setLoading(false);}
  };
  const context=revision??value?.presentation_revision;
  return <div style={{margin:'12px 0'}}>
    <Space wrap><Button size="small" loading={loading} onClick={load}>核对验收资料包</Button>
      {value?.enabled&&<Button size="small" href={value.download_url}>下载本批验收资料ZIP</Button>}</Space>
    <p className="small muted">只读取已有矩阵、图件、来源、参数和构象；缺译阻断最终交付，不触发重算或生成Word。</p>
    {error&&<Alert type="error" showIcon message={error}/>}
    {value&&!value.enabled&&<Alert type={value.archive_required?'info':'warning'} showIcon message={value.archive_required?'请使用完整资料包下载':'本批验收资料尚未齐备'}
      description={value.blockers_zh.map((text,index)=><div key={index}>{text}</div>)}/>}
    {value?.archive_required&&value.archive_url&&context&&<RescueAcceptanceArchives key={value.archive_url}
      url={value.archive_url} runId={value.run_id} revision={context}/>}
    {value?.enabled&&<p className="small muted">{value.note_zh}</p>}
  </div>;
}
