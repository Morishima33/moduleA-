// 已归档自动评分按需展示：矩阵、分页清单、单组合证据及文件分页。
import {Alert, Button, Collapse, Drawer, Input, Select, Spin, Table, message} from 'antd';
import {useEffect, useRef, useState} from 'react';
import type {AutomaticDockingInfo, AutomaticFile, AutomaticMatrixResponse, AutomaticPair} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';

/** 页面只读取选择和服务端结果，不推算质控或评分阈值。 */
export default function AutomaticResults({studyId, latest, readOnly=false}: {studyId:string; latest:NonNullable<AutomaticDockingInfo['latest']>; readOnly?:boolean}) {
  const {bumpRefresh, openTasks} = useApp();
  const [rows,setRows] = useState<AutomaticPair[]>([]), [total,setTotal] = useState(0), [page,setPage] = useState(1), [query,setQuery] = useState('');
  const [matrix,setMatrix] = useState<AutomaticMatrixResponse|null>(null), [compounds,setCompounds] = useState<string[]>([]), [targets,setTargets] = useState<string[]>([]);
  const [trace,setTrace] = useState<AutomaticPair|null>(null), [traceOpen,setTraceOpen] = useState(false), [traceBusy,setTraceBusy] = useState(false);
  const [files,setFiles] = useState<AutomaticFile[]>([]), [filesTotal,setFilesTotal] = useState(0), [filesPage,setFilesPage] = useState(1), [filesQuery,setFilesQuery] = useState(''), [filesLoaded,setFilesLoaded] = useState(false);
  const [error,setError] = useState(''), [matrixBusy,setMatrixBusy] = useState(false), [exportBusy,setExportBusy] = useState(false);
  const sequence=useRef(0), traceSequence=useRef(0);
  const complete=latest.state==='completed';
  useEffect(() => {
    let active=true;
    if (!complete) return;
    api.automaticPairs(studyId,latest.id,page,query).then(r => {if(active){setRows(r.items);setTotal(r.total);}}).catch(e => {if(active)setError(errorText(e));});
    return () => {active=false;};
  },[studyId,latest.id,complete,page,query]);
  useEffect(() => {
    let active=true;
    if (!complete) return;
    setMatrixBusy(true);
    api.automaticMatrix(studyId,latest.id).then(r => {if(active){setMatrix(r);setCompounds(r.view.heatmap.rows.map(c=>c.compound_id));setTargets(r.view.heatmap.columns.map(t=>t.target_id));}}).catch(e=>{if(active)setError(errorText(e));}).finally(()=>{if(active)setMatrixBusy(false);});
    return ()=>{active=false;};
  },[studyId,latest.id,complete,latest.display_id]);
  async function preview() {
    const request=++sequence.current; setMatrixBusy(true);setError('');
    try {const r=await api.automaticMatrix(studyId,latest.id,compounds,targets);if(request===sequence.current)setMatrix({...r,downloads:[]});}
    catch(e){if(request===sequence.current)setError(errorText(e));}finally{if(request===sequence.current)setMatrixBusy(false);}
  }
  async function exportFiles() {
    if(readOnly||!latest.run_id)return;
    setExportBusy(true);setError('');
    try{const r=await api.automaticDisplay(studyId,{expected_a06:latest.run_id,batch_id:latest.id,compound_ids:compounds,target_ids:targets});message.success(r.message_zh);openTasks(r.task.task_id);bumpRefresh();}
    catch(e){setError(errorText(e));}finally{setExportBusy(false);}
  }
  async function showTrace(row:AutomaticPair) {
    if(!row.pair_key)return;
    const request=++traceSequence.current;setTrace(null);setTraceOpen(true);setTraceBusy(true);
    try{const r=await api.automaticEvidence(studyId,latest.id,row.pair_key);if(request===traceSequence.current)setTrace(r);}
    catch(e){if(request===traceSequence.current)setError(errorText(e));}finally{if(request===traceSequence.current)setTraceBusy(false);}
  }
  async function loadFiles(p=1,q=filesQuery) {
    try{const r=await api.automaticFiles(studyId,latest.id,p,q);setFiles(r.items);setFilesTotal(r.total);setFilesPage(p);setFilesLoaded(true);}
    catch(e){setError(errorText(e));}
  }
  return <section className="stack" id="module-automatic-results" style={{minWidth:0,scrollMarginTop:90}}>
    <Alert type={['failed','interrupted','stale'].includes(latest.state)?'warning':'info'} showIcon message={{completed:'计算已完成：查看图表与异常后，在右侧独立复核',running:'后台正在计算，请查看任务进度',authorized:'执行范围已确认',failed:'本次执行失败，已有证据保留',interrupted:'执行已中断，原件保留',stale:'旧批次仅供追溯'}[latest.state]||latest.state} description={latest.error_zh}/>
    {latest.summary&&<p>有效评分 {String(latest.summary['成功组合数'])} 组；计算或姿势质控未通过 {String(latest.summary['失败组合数'])} 组；准备未通过 {String(latest.summary['NA组合数'])} 组。严格受体 {String(latest.summary['严格受体数'])}，探索受体 {String(latest.summary['探索受体数'])}。</p>}
    {error&&<Alert type="error" showIcon message={error}/>}
    {complete&&<>
      <h3>重点热图与完整矩阵</h3>
      <Spin spinning={matrixBusy}>
        {matrix&&<div className="stack" style={{minWidth:0}}>
          <div className="row" style={{display:'flex',flexWrap:'wrap',gap:10}}>
            <Select aria-label="热图成分" mode="multiple" value={compounds} onChange={setCompounds} style={{minWidth:200,flex:'1 1 240px',maxWidth:'100%'}} options={matrix.view.table.rows.map(c=>({value:c.compound_id,label:c.name_zh&&c.name_zh!==c.name_en?`${c.name_zh}（${c.name_en}）`:c.name_en||c.compound_id}))}/>
            <Select aria-label="热图受体" mode="multiple" value={targets} onChange={setTargets} style={{minWidth:200,flex:'1 1 240px',maxWidth:'100%'}} options={matrix.view.table.columns.map(t=>({value:t.target_id,label:`${t.symbol} ${t.candidate_grade}`}))}/>
          </div>
          <div className="row" style={{display:'flex',flexWrap:'wrap',gap:8}}><Button disabled={!compounds.length||!targets.length} onClick={preview}>预览显示选择</Button><Button disabled={readOnly||!matrix.enabled||!compounds.length||!targets.length} loading={exportBusy} onClick={exportFiles}>生成图表与矩阵下载</Button></div>
          <p className="muted">显示选择不改变计算对象或评分。重点图与完整矩阵共用完整同批色标；完整表的“**”仅标记原始评分≤−8，不表示统计显著性。</p>
          <div style={{overflowX:'auto',maxWidth:'100%'}}><img alt="本批重点分子对接热图" src={'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(matrix.svg)} style={{display:'block',width:'100%',minWidth:600}}/></div>
          <div className="row" style={{display:'flex',flexWrap:'wrap',gap:12}}>{matrix.downloads.map(f=><a key={f.url} href={f.url} style={{overflowWrap:'anywhere',maxWidth:'100%'}}>{f.name}</a>)}</div>
          <Collapse items={[{key:'matrix',label:`查看完整矩阵（${matrix.view.table.rows.length}个成分 × ${matrix.view.table.columns.length}个受体）`,children:<div style={{overflowX:'auto',maxWidth:'100%'}}><table style={{borderCollapse:'collapse',fontSize:13}}><thead><tr><th style={{padding:10,minWidth:200}}>成分</th>{matrix.view.table.columns.map(t=><th key={t.target_id} style={{padding:10,minWidth:90}}>{t.symbol}<br/>{t.candidate_grade}</th>)}</tr></thead><tbody>{matrix.view.table.rows.map((c,i)=><tr key={c.compound_id}><th style={{padding:10,textAlign:'left',overflowWrap:'anywhere'}}>{c.name_zh||c.name_en}{c.name_zh&&c.name_zh!==c.name_en&&<><br/>{c.name_en}</>}</th>{matrix.view.table.cells[i].map((cell,j)=><td key={j} title={cell.reason_zh||String(cell.score)} style={{padding:10,textAlign:'center',background:cell.color,color:cell.text_color,border:cell.score===null?'1px dashed #AAB4BE':'1px solid white'}}>{cell.display_score}{cell.threshold_mark}</td>)}</tr>)}</tbody></table></div>} ]}/>
        </div>}
      </Spin>
      <h3>逐组合评分与异常</h3>
      <Input.Search aria-label="查找对接组合" placeholder="按成分、受体或异常查找" onSearch={v=>{setQuery(v);setPage(1);}} allowClear/>
      <Table rowKey="pair_key" size="small" scroll={{x:760}} dataSource={rows} pagination={{current:page,pageSize:20,total,onChange:setPage,showSizeChanger:false}} columns={[
        {title:'成分',dataIndex:'compound_name'},{title:'受体',dataIndex:'symbol'},{title:'评分 kcal/mol',render:(_,r)=>r.score===null?'NA':r.score.toFixed(2)},
        {title:'范围',dataIndex:'quality'},{title:'状态／原因',render:(_,r)=><>{r.status_zh}<br/>{r.reason_zh}</>},
        {title:'溯源',render:(_,r)=><Button size="small" onClick={()=>showTrace(r)}>查看计算依据</Button>}
      ]}/>
    </>}
    <Collapse onChange={keys=>{if(keys.length&&!filesLoaded)void loadFiles();}} items={[{key:'files',label:`原件、参数、姿势与运行日志（${latest.file_count??0}个文件，按需加载）`,children:<div className="stack"><Input.Search placeholder="按文件名查找" onSearch={q=>{setFilesQuery(q);void loadFiles(1,q);}}/><Table rowKey="url" size="small" scroll={{x:600}} dataSource={files} pagination={{current:filesPage,pageSize:20,total:filesTotal,showSizeChanger:false,onChange:p=>void loadFiles(p)}} columns={[{title:'文件',render:(_,f)=><a href={f.url} style={{overflowWrap:'anywhere'}}>{f.path||f.name}</a>}]}/></div>} ]}/>
    <Drawer title="本分数计算依据" open={traceOpen} onClose={()=>{setTraceOpen(false);traceSequence.current++;setTraceBusy(false);}} width="min(760px,95vw)">
      <Spin spinning={traceBusy}>{trace&&<div className="stack"><p>{trace.compound_name}—{trace.symbol}：{trace.score??'NA'} kcal/mol；{trace.status_zh}</p><p>{trace.reason_zh}</p>{trace.evidence_files?.map(f=><a key={f.url} href={f.url} style={{overflowWrap:'anywhere'}}>{f.path||f.name}</a>)}<Collapse items={[{key:'raw',label:'构型、位点、参数和完整执行依据',children:<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:12}}>{JSON.stringify(trace,null,2)}</pre>}]}/></div>}</Spin>
    </Drawer>
  </section>;
}
