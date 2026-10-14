// 本批准备页：只读关联已确认试算，同批资料与历史严格质控分别呈现。
import {Alert, Button, Collapse, Descriptions, Modal, Table, Tag} from 'antd';
import {useState} from 'react';
import type {PreparationFile, TrialPreparationInfo} from '../api/types';
import {fmtTime} from '../lib/format';
import {StatusPill} from './common';

const modes:Record<string,string>={fixed_site:'预先固定的共晶位点',predicted_sites:'预测位点探索',partitioned_blind:'分区盲搜'};
const header=()=>({style:{background:'#0F5E6E',color:'#FFFFFF'}});

/** 原件与准备文件仅使用归档接口提供的下载地址。 */
function FileLink({file,label}:{file?:PreparationFile|null;label:string}){
 return file?.url ? <a href={file.url} title={`${file.path}\nSHA-256 ${file.sha256}`}>{label}</a> : <span>{file?.path || '未提供'}</span>;
}

/** 用中文展示原核查来源，下载原件作为进一步追溯。 */
export function PreparationSource({info}:{info:TrialPreparationInfo}){
 const [open,setOpen]=useState(false);
 return <><Button onClick={()=>setOpen(true)}>查看核查来源</Button><Modal title="已有核查来源" open={open} onCancel={()=>setOpen(false)} footer={<Button onClick={()=>setOpen(false)}>关闭</Button>}>
  <Descriptions column={1} size="small" items={[
   {key:'reviewer',label:'原试算核查人',children:info.reviewer},
   {key:'time',label:'原核查时间',children:fmtTime(info.reviewed_at)},
   {key:'note',label:'原核查说明',children:info.note},
   {key:'formal',label:'关联的A06确认记录',children:`${info.a06_reviewer} · ${fmtTime(info.a06_reviewed_at)}`},
   {key:'run',label:'所关联A06',children:<span style={{overflowWrap:'anywhere'}}>{info.a06_run_id}</span>},
  ]}/><p>本页沿用已有核查，关联记录不新增人工批准，也不改变历史严格质控。</p><Button href={info.source_url}>下载原核查记录</Button>
 </Modal></>;
}

/** 同批准备摘要、受体、成分及默认折叠的历史证据，均无保存表单。 */
export default function TrialPreparation({info,label}:{info:TrialPreparationInfo;label:string}){
 const receptorColumns=[
  {title:'受体',key:'gene',width:110,render:(_:unknown,r:TrialPreparationInfo['receptors'][number])=><><strong>{r.symbol}</strong><div className="tiny muted">{r.target_id}</div></>},
  {title:'A/B梯队',dataIndex:'candidate_grade',width:80},
  {title:'实际采用结构',dataIndex:'structure_id',width:115},
  {title:'位点／搜索方式',key:'mode',width:140,render:(_:unknown,r:TrialPreparationInfo['receptors'][number])=>modes[r.mode]||r.mode},
  {title:'准备及修补说明',key:'preparation',width:250,render:(_:unknown,r:TrialPreparationInfo['receptors'][number])=><>{r.processing_zh||r.reason_zh}{r.repair&&<div className="small">新增侧链原子 {r.repair.added_atoms.length} 个；原重原子坐标{r.repair.original_coordinates_unchanged?'保持':'未验证'}。</div>}</>},
  {title:'适用范围',key:'scope',width:125,render:()=> <><Tag color="blue">扩展试算</Tag><div className="small">严格等级见历史证据</div></>},
  {title:'证据',key:'evidence',width:160,render:(_:unknown,r:TrialPreparationInfo['receptors'][number])=><Collapse size="small" items={[{key:r.target_id,label:'查看证据',children:<>
   <p><FileLink file={r.source} label="下载采用的来源结构"/></p><p><FileLink file={r.receptor} label="下载实际准备文件"/></p>
   <p>历史质控：{r.history_quality_zh||'未记录'}{r.history_rmsd_A!=null&&`；RMSD ${r.history_rmsd_A.toFixed(3)} Å`}</p>
   <pre className="tiny" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({spec:r.spec,regions:r.regions,environment:r.environment,attempts:r.attempts},null,2)}</pre>
  </>}]} />},
 ].map(c=>({...c,onHeaderCell:header}));
 const compoundColumns=[
  {title:'成分名称',dataIndex:'name_zh',width:200},
  {title:'身份',key:'identity',width:280,render:(_:unknown,c:TrialPreparationInfo['compounds'][number])=><>PubChem CID {c.cid}<div className="small">{c.preparation.identity?.formula}</div><div className="tiny muted" style={{overflowWrap:'anywhere'}}>{c.preparation.identity?.inchi_key}</div><span className="small">{c.preparation.identity?.identity_check==='matched'?'归档身份匹配':'详见原身份记录'}</span></>},
  {title:'来源三维与准备文件',key:'source',render:(_:unknown,c:TrialPreparationInfo['compounds'][number])=><>{c.files.map(f=><p key={f.path} style={{margin:'3px 0'}}><FileLink file={f} label={f.role==='source_3d'?'来源三维 SDF':'本批准备文件'}/></p>)}<Collapse size="small" items={[{key:'identity',label:'查看原准备记录',children:<pre className="tiny" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(c.preparation,null,2)}</pre>}]}/></>},
 ].map(c=>({...c,onHeaderCell:header}));
 const historyColumns=['受体','PDB','质控状态','RMSD_A','结构限制'].map(key=>({title:key==='RMSD_A'?'历史RMSD（Å）':key,dataIndex:key,render:(value:unknown)=>value==null?'—':String(value)}));
 return <div className="stack">
  <section className="card"><div style={{display:'flex',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}><h1 style={{margin:0,fontSize:24}}>本批对接准备</h1><StatusPill code={info.active?'scope_confirmed':'stale'} label={label}/></div>
   <p className="small muted">沿用本批已确认的结构、位点和处理记录；扩展用途与严格质控分别记录。</p>
   {!info.active&&<Alert type="warning" showIcon message="准备关联已失效" description={info.reason_zh}/>}
  </section>
  <section className="card" id="trial-preparation-summary"><h2>本批准备摘要</h2>
   <p>{info.active?`${info.compounds.length}个成分 · ${info.receptors.length}个受体，均来自下方A06的同批准备资料。`:'当前资料不再满足原关联；完整历史记录保留，不能沿用为本批已核查。'}</p>
   <p>原核查人：<strong>{info.reviewer}</strong> · {fmtTime(info.reviewed_at)}；说明：{info.note}</p>
   <p className="small">关联的A06确认记录：{info.a06_reviewer} · {fmtTime(info.a06_reviewed_at)}。{info.active?'本页沿用已有核查，无需重复提交。':'此为原确认记录，当前关联已失效。'}</p>
   <p className="tiny muted" style={{overflowWrap:'anywhere'}}>关联A06：{info.a06_run_id}<br/>同批试算：{info.trial_id}<br/>准备关联：{info.link_id} · {fmtTime(info.created_at)}</p>
   <p><PreparationSource info={info}/>{' '}<Button type="primary" href={info.result_url}>{info.active?'前往已确认A06结果':'查看关联A06版本'}</Button></p>
  </section>
  {info.active&&<><section className="card" id="trial-preparation-receptors"><h2>15受体准备表</h2><p className="small muted">横向滚动查看适用范围与证据，纵向查看完整15项。</p><Table rowKey="target_id" size="small" pagination={false} scroll={{x:1080,y:640}} columns={receptorColumns} dataSource={info.receptors}/></section>
   <section className="card" id="trial-preparation-compounds"><h2>成分准备资料</h2><Table rowKey="compound_id" size="small" pagination={false} scroll={{x:700}} columns={compoundColumns} dataSource={info.compounds}/></section></>}
  <Collapse items={[{key:'strict-history',label:'历史严格准备与质控',children:<><p className="small">旧{info.history_rows.length}受体方案及失败、待补记录原样留存。历史运行：{info.legacy_run_id}。</p><Table rowKey={(_,i)=>String(i)} size="small" pagination={false} scroll={{x:850}} columns={historyColumns} dataSource={info.history_rows}/></>}]} />
 </div>;
}
