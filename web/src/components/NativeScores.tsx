// 文件用途：只读显示本平台完整矩阵与同批MODEL1下载；不触发计算或科研批准。
import { Alert,Button,Collapse,Space } from 'antd';
import { useState } from 'react';
import type { NativeScoreDisplay,RescueCell } from '../api/types';
import { Matrix } from './SystemRescueResults';
import { SectionHead } from './common';

/** 复用既有矩阵组件与后端名称、颜色、原因和指纹链接，不在前端重算科学结果。 */
export default function NativeScores({data}:{data:NativeScoreDisplay}) {
  const [picked,setPicked]=useState<RescueCell|null>(null);
  const compound=(id:string)=>data.table.rows.find(row=>row.compound_id===id)?.label||id;
  const receptor=(id:string)=>data.table.columns.find(row=>row.target_id===id)?.label||id;
  return <section className="card" style={{minWidth:0}}>
    <SectionHead title="本平台评分与构象" extra="完整组合、NA及实际执行保持"/>
    <Alert type="info" showIcon message={data.review_note_zh} description={data.scope_note_zh}/>
    <p className="small muted">{data.colour_note_zh}</p>
    <Space wrap>{data.downloads.map(file=><Button key={file.url} size="small" href={file.url}>{file.label_zh}</Button>)}</Space>
    <h3>成功对象焦点热图</h3>
    <Matrix matrix={data.heatmap} label="本平台成功对象焦点热图" onPick={setPicked}/>
    <h3>完整矩阵（{data.table.rows.length}×{data.table.columns.length}）</h3>
    <Matrix matrix={data.table} label="本平台完整评分矩阵" onPick={setPicked}/>
    <p className="small muted">点击格子核对原始精度及原因。NA表示未形成有效评分，不能解释为结合差。</p>
    {picked&&<div role="region" aria-label="本平台组合评分与构象" style={{padding:14,border:'1px solid #DCE1E5',borderRadius:8,overflowWrap:'anywhere'}}>
      <strong>{compound(picked.compound_id)} × {receptor(picked.target_id)}</strong>
      <p>原始评分：{picked.score??'NA'} {picked.score!==null?data.unit:''} · {picked.state_zh} · {picked.quality}</p>
      {picked.reason_zh&&<p>原因：{picked.reason_zh}</p>}
      <Space wrap>{picked.downloads.map(file=><Button key={file.url} size="small" href={file.url}>{file.label_zh}</Button>)}
        <Button size="small" onClick={()=>setPicked(null)}>关闭详情</Button></Space>
      {picked.downloads.length>0&&<p className="small muted">Top-1取自本格实际Vina输出的MODEL 1原字节；指纹说明与评分对应同一执行。</p>}
    </div>}
    {data.figures.length>0&&<Collapse items={[{key:'figures',label:'本批已归档完整图与焦点图',children:<div className="stack">
      {data.figures.map(file=><a key={file.url} href={file.url}><img src={file.image_url} alt={file.name} loading="lazy" style={{maxWidth:'100%',height:'auto'}}/></a>)}
    </div>}]}/>}
  </section>;
}
