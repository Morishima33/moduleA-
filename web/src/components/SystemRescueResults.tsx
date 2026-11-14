// 文件用途：展示本轮受体补救的完整评分、焦点图、NA原因与已登记原始证据；不执行计算。
import { Alert, Button, Collapse, Select, Space } from 'antd';
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { RescueCell, RescueEvidence, RescueMatrix, SystemRescueDisplay } from '../api/types';
import { HEAT_GRADIENT } from '../lib/theme';
import { SectionHead } from './common';

/** 直接排版后端返回的行列；不在页面裁切或推算科学结果。 */
function Matrix({ matrix, label, onPick }: {
  matrix:RescueMatrix;label:string;onPick:(cell:RescueCell)=>void;
}) {
  const rows = matrix.rows.map((row, index) => ({row, index}));
  const columns = matrix.columns.map((column, index) => ({column, index}));
  if (!rows.length || !columns.length) return <p className="small muted">请选择要显示的成分和受体；完整矩阵保留在下方。</p>;
  return <div style={{overflowX:'auto',maxWidth:'100%',minWidth:0}}>
    <table aria-label={label} style={{borderCollapse:'collapse',fontSize:12,width:'100%'}}>
      <thead><tr><th scope="col" style={{padding:8,minWidth:180,textAlign:'left'}}>本批成分记录</th>
        {columns.map(({column}) => <th scope="col" key={column.target_id} title={column.target_id} style={{padding:8,minWidth:76}}>
          {column.label}{column.candidate_grade && <div className="small muted">{column.candidate_grade}</div>}
        </th>)}
      </tr></thead>
      <tbody>{rows.map(({row,index}) => <tr key={row.compound_id}>
        <th scope="row" title={row.compound_id} style={{padding:8,border:'1px solid #DCE1E5',fontWeight:500,textAlign:'left',overflowWrap:'anywhere'}}>
          {row.label}{row.name_zh && row.name_en!==row.name_zh && <div className="small muted" style={{maxWidth:300}}>{row.name_en}</div>}
        </th>
        {columns.map(({column,index:columnIndex}) => {
          const cell=matrix.cells[index][columnIndex];
          const title=`${row.label} × ${column.label}：${cell.score_text}；${cell.state_zh}；${cell.source_zh}；${cell.quality}；${cell.reason_zh}`;
          return <td key={column.target_id} style={{padding:0,border:'1px solid #DCE1E5'}}>
            <button type="button" title={title} aria-label={title} onClick={()=>onPick(cell)}
              style={{display:'block',width:'100%',minHeight:44,padding:8,cursor:'pointer',font:'inherit',
                background:cell.color,color:cell.text_color,border:cell.score===null?'1px dashed #8C969E':'1px solid transparent'}}>
              {cell.display_score}
            </button>
          </td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}

/** 显示范围是本地页面状态，切换与刷新均不发写请求、不产生新科学运行。 */
export default function SystemRescueResults({data}:{data:SystemRescueDisplay}) {
  const [compounds,setCompounds]=useState(data.initial_focus.compound_ids);
  const [targets,setTargets]=useState(data.initial_focus.target_ids);
  const [picked,setPicked]=useState<RescueCell|null>(null);
  const [focused,setFocused]=useState(data.heatmap);
  const [focusError,setFocusError]=useState('');
  const [focusLoading,setFocusLoading]=useState(false);
  const [evidence,setEvidence]=useState<RescueEvidence|null>(null);
  const [evidenceError,setEvidenceError]=useState('');
  // 运行切换后清理旧选择和证据，迟到响应由各effect的失效标志丢弃。
  useEffect(()=>{
    setCompounds(data.initial_focus.compound_ids);setTargets(data.initial_focus.target_ids);
    setFocused(data.heatmap);setPicked(null);setEvidence(null);
  },[data.run_id,data.input_key]);
  useEffect(()=>{
    if(!data.focus_url||!data.input_key)return;
    let active=true;setFocusLoading(true);setFocusError('');
    api.rescueFocus(data.focus_url,data.input_key,compounds,targets).then(value=>{
      if(active&&value.run_id===data.run_id&&value.input_key===data.input_key)setFocused(value.heatmap);
    }).catch(error=>{if(active)setFocusError(error instanceof Error?error.message:'焦点范围读取失败');})
      .finally(()=>{if(active)setFocusLoading(false);});
    return()=>{active=false;};
  },[data.focus_url,data.input_key,data.run_id,compounds,targets]);
  useEffect(()=>{
    let active=true;setEvidence(null);setEvidenceError('');
    if(picked?.evidence_url)api.rescueEvidence(picked.evidence_url).then(value=>{
      if(active&&value.run_id===data.run_id&&value.compound_id===picked.compound_id&&value.target_id===picked.target_id)setEvidence(value);
    }).catch(error=>{if(active)setEvidenceError(error instanceof Error?error.message:'组合证据读取失败');});
    return()=>{active=false;};
  },[picked,data.run_id]);
  const compoundName=(identity:string)=>data.table.rows.find(row=>row.compound_id===identity)?.label||identity;
  const targetName=(identity:string)=>data.table.columns.find(row=>row.target_id===identity)?.label||identity;
  return <section className="card" style={{minWidth:0}}>
    <SectionHead title="受体补救与完整评分" extra="点击格子核对原值、来源与证据"/>
    <Alert type="info" showIcon message={data.review_note_zh} description={data.scope_note_zh}/>
    <p className="small muted">{data.colour_note_zh}</p>
    {data.downloads.length>0 && <Space wrap style={{marginBottom:14}}>{data.downloads.map(file=><Button key={file.url} size="small" href={file.url}>{file.label_zh}</Button>)}</Space>}

    <h3 style={{fontSize:16}}>焦点热图</h3>
    <p className="small muted">初始显示有成功评分的对象。选择只改变本图范围；完整组合、NA和归档图件保留。</p>
    {data.focus_url&&<div style={{display:'flex',flexWrap:'wrap',gap:12,marginBottom:12}}>
      <label style={{display:'flex',flexDirection:'column',gap:4,flex:'1 1 280px',minWidth:0}}>显示成分
        <Select aria-label="焦点热图显示成分" mode="multiple" value={compounds} onChange={setCompounds} optionFilterProp="label"
          maxTagCount="responsive" style={{width:'100%'}} options={data.table.rows.map(row=>({value:row.compound_id,label:row.label}))}/>
      </label>
      <label style={{display:'flex',flexDirection:'column',gap:4,flex:'1 1 240px',minWidth:0}}>显示受体
        <Select aria-label="焦点热图显示受体" mode="multiple" value={targets} onChange={setTargets} optionFilterProp="label"
          maxTagCount="responsive" style={{width:'100%'}} options={data.table.columns.map(row=>({value:row.target_id,label:row.label}))}/>
      </label>
      <Space wrap>
        <Button size="small" onClick={()=>{setCompounds(data.initial_focus.compound_ids);setTargets(data.initial_focus.target_ids);}}>显示成功对象</Button>
        <Button size="small" onClick={()=>{setCompounds(data.table.rows.map(row=>row.compound_id));setTargets(data.table.columns.map(row=>row.target_id));}}>显示完整范围</Button>
      </Space>
    </div>}
    {focusError?<Alert type="error" showIcon message={focusError}/>:focusLoading?
      <p role="status">正在读取本批焦点范围…</p>:<Matrix matrix={focused} label="补救焦点热图" onPick={setPicked}/>}
    <div className="small muted" style={{display:'flex',flexWrap:'wrap',gap:10,alignItems:'center',margin:'12px 0'}}>
      <span>{data.score_range[0]??'无有效评分'} 更负</span>
      <span aria-hidden style={{height:10,width:180,background:HEAT_GRADIENT}}/>
      <span>{data.score_range[1]??'无有效评分'} 较不负（{data.unit}）</span>
      <span>NA：白底虚线</span>
    </div>

    {picked && <div role="region" aria-label="组合评分与证据" style={{padding:14,border:'1px solid #DCE1E5',borderRadius:8,margin:'12px 0',overflowWrap:'anywhere'}}>
      <div style={{display:'flex',justifyContent:'space-between',gap:8}}>
        <strong>{compoundName(picked.compound_id)} × {targetName(picked.target_id)}</strong>
        <Button size="small" onClick={()=>setPicked(null)}>关闭详情</Button>
      </div>
      <p>原始评分：<span className="mono">{picked.score_text}</span>{picked.score!==null?` ${data.unit}`:''} · {picked.state_zh}</p>
      <p>来源：{picked.source_zh} · 准备类别：{picked.quality||'未登记'}</p>
      {picked.reason_zh && <p>原因：{picked.reason_zh}</p>}
      <p className="small muted">成分编号：{picked.compound_id}；受体编号：{picked.target_id}</p>
      {!picked.evidence_url&&(picked.downloads.length>0 ? <Space wrap>{picked.downloads.map(file=><Button size="small" key={file.url} href={file.url}>{file.label_zh}</Button>)}</Space>
        : <p className="small muted">本格未提供可核对的独立附件链接；原因与完整结果可在本批明细中核对。</p>)}
      {picked.evidence_url&&!evidence&&!evidenceError&&<p role="status">正在核对原始执行与构象…</p>}
      {evidenceError&&<Alert type="error" showIcon message={evidenceError}/>}
      {evidence&&<>
        <p>{evidence.source_zh}</p>
        <Space wrap>{evidence.downloads.map(file=><Button size="small" key={file.url} href={file.url}
          title={`SHA-256：${file.sha256}；${file.bytes??'未登记'}字节`}>{file.label_zh}</Button>)}</Space>
        <p className="small muted">{evidence.region_note_zh}</p>
        {evidence.regions.length>0&&<div style={{overflowX:'auto',maxWidth:'100%'}}>
          <table aria-label="区域执行与选中证据" style={{width:'100%',borderCollapse:'collapse',fontSize:13}}>
            <thead><tr>{['区域','实际状态','原始评分','选中区域','失败原因','执行证据'].map(text=><th key={text} style={{padding:8,textAlign:'left'}}>{text}</th>)}</tr></thead>
            <tbody>{evidence.regions.map(region=><tr key={region.region_id}>
              <th scope="row" style={{padding:8,textAlign:'left'}}>{region.region_id}</th>
              <td style={{padding:8}}>{region.state_zh}</td><td style={{padding:8}}>{region.score??'NA'}</td>
              <td style={{padding:8}}>{region.selected?'已选中':'—'}</td><td style={{padding:8,minWidth:160}}>{region.reason_zh||'—'}</td>
              <td style={{padding:8}}>{region.downloads.map(file=><Button size="small" key={file.url} href={file.url} title={`SHA-256：${file.sha256}`}>{file.label_zh}</Button>)}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      </>}
    </div>}

    <h3 style={{fontSize:16}}>完整矩阵（{data.table.rows.length}×{data.table.columns.length}）</h3>
    <Matrix matrix={data.table} label="补救完整评分矩阵" onPick={setPicked}/>
    <p className="small muted">图中显示小数为便于阅读的格式；点击格子或下载完整CSV可核对原始精度。</p>
    <Collapse items={[{key:'preparation',label:'受体准备状态与剩余NA原因',children:<div style={{overflowX:'auto',maxWidth:'100%'}}>
      <table aria-label="受体补救准备明细" style={{borderCollapse:'collapse',width:'100%',fontSize:13}}>
        <thead><tr>{['受体','实际状态','准备类别','依据或NA原因'].map(text=><th key={text} style={{padding:8,textAlign:'left'}}>{text}</th>)}</tr></thead>
        <tbody>{data.receptor_preparation.map(row=><tr key={row.target_id}>
          <th scope="row" title={row.target_id} style={{padding:8,textAlign:'left'}}>{row.symbol||row.target_id}</th>
          <td style={{padding:8}}>{row.state_zh}</td><td style={{padding:8}}>{row.quality||'未登记'}</td>
          <td style={{padding:8,minWidth:200,overflowWrap:'anywhere'}}>{row.reason_zh||'—'}</td>
        </tr>)}</tbody>
      </table>
    </div>},...(data.figures.length?[{key:'figures',label:'已归档完整图与成功对象焦点图',children:<div className="stack">{data.figures.map(figure=><a key={figure.url} href={figure.url}>
      <img src={figure.image_url} alt={figure.name} loading="lazy" style={{maxWidth:'100%',height:'auto'}}/>
    </a>)}</div>}]:[])]}/>
  </section>;
}
