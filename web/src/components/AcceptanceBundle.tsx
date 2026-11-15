// 文件用途：明确核对本批已登记验收资料；缺译或原件缺失时展示后端阻塞，不补算。
import { Alert, Button, Space } from 'antd';
import { useState } from 'react';
import { api,errorText } from '../api/client';
import type { AcceptanceBundle as Bundle } from '../api/types';

/** 用户点击后只读核对；下载按钮只在后端确认本批附件齐备时出现。 */
export default function AcceptanceBundle({url}:{url:string}) {
  const [value,setValue]=useState<Bundle|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const load=async()=>{
    setLoading(true);setError('');setValue(null);
    try{setValue(await api.acceptanceBundle(url));}
    catch(cause){setError(errorText(cause));}
    finally{setLoading(false);}
  };
  return <div style={{margin:'12px 0'}}>
    <Space wrap><Button size="small" loading={loading} onClick={load}>核对验收资料包</Button>
      {value?.enabled&&<Button size="small" href={value.download_url}>下载本批验收资料ZIP</Button>}</Space>
    <p className="small muted">只读取已有矩阵、图件、来源、参数和构象；缺译阻断最终交付，不触发重算或生成Word。</p>
    {error&&<Alert type="error" showIcon message={error}/>}
    {value&&!value.enabled&&<Alert type="warning" showIcon message="本批验收资料尚未齐备"
      description={value.blockers_zh.map((text,index)=><div key={index}>{text}</div>)}/>}
    {value?.enabled&&<p className="small muted">{value.note_zh}</p>}
  </div>;
}
