// 文件用途：分别显示后端已核验的准备、组合、区域进度；不推算成功率或剩余时间。
import { Alert } from 'antd';
import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import type { ScientificProgress } from '../api/types';
import { fmtTime } from '../lib/format';

/** 面板打开后才读取；活动任务沿原三秒轮询，切换任务时丢弃迟到响应。 */
export default function TaskScientificProgress({taskId,active}:{taskId:string;active:boolean}) {
  const [value,setValue]=useState<ScientificProgress|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    let valid=true,pending=false;
    setValue(null);setError('');
    const load=async()=>{
      if(pending)return;pending=true;
      try{
        const data=await api.taskScientificProgress(taskId);
        if(valid){setValue(data);setError('');}
      }catch(cause){if(valid)setError(errorText(cause));}
      finally{pending=false;}
    };
    void load();
    const timer=active?window.setInterval(load,3000):undefined;
    return()=>{valid=false;if(timer!==undefined)window.clearInterval(timer);};
  },[taskId,active]);
  if(error)return <Alert type="error" showIcon message="科学进度暂不可核验" description={error}/>;
  if(!value?.supported)return null;
  if(!value.available)return <p className="small muted">{value.message_zh}</p>;
  return <section aria-label="分别核验的科学进度" className="stack" style={{gap:8}}>
    {([['准备',value.preparation],['组合评分',value.pairs],['区域执行',value.regions]] as const).map(([label,row])=>row&&
      <div key={label} style={{border:'1px solid #DCE1E5',borderRadius:6,padding:8}}>
        <strong>{label}：已登记{row.completed} / {row.total??'总数未固定'}</strong>
        <div className="small">复用 {row.reused} · 本轮新增 {row.new} · 成功 {row.succeeded} · 失败 {row.failed}{row.na!==undefined&&<> · NA {row.na}</>} · 待完成 {row.pending??'未固定'}</div>
      </div>)}
    <div className="small">当前对象：{value.current_object_zh||'未登记'}<br/>最近更新：{fmtTime(value.updated_at||'')}</div>
    <p className="tiny muted">{value.message_zh}<br/>{value.region_total_note_zh}<br/>{value.estimate_note_zh}</p>
  </section>;
}
