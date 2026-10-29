// 文件用途：展示本批固定输入到结构准备和证据核查的真实入口，不执行科学计算或代签。
import { Alert, Button, Checkbox, Descriptions, Input, Table } from 'antd';
import { useState } from 'react';
import type { PlanPreparationUiInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';
import { navigate } from '../lib/route';

/** 明确确认仅连接本批来源并准备，失败保留NA，后续核查/复核/评分分别执行。 */
export default function PlanPreparation({studyId,info}:{studyId:string;info:PlanPreparationUiInfo}) {
 const app=useApp();const [author,setAuthor]=useState('');const [note,setNote]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);const current=info.current,summary=current?.summary;
 async function execute(){setBusy(true);setNotice(null);try{
  const r=await api.startPlanPreparation(studyId,{request_id:'planprep_'+crypto.randomUUID().replace(/-/g,''),
   expected_input_id:info.expected_input_id,expected_preparation_run_id:info.expected_preparation_run_id,
   expected_input_hash:info.input_hash,author,note,confirmed:true});
  app.trackTasks([r.task]);app.openTasks(r.task.task_id);setNotice(r.message_zh);setConfirmed(false);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));setConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
 /** 同页定位已有证据区，跨页仅导航，不发起任何任务。 */
 function open(step:PlanPreparationUiInfo['steps'][number]){
  if(step.target==='pockets'){navigate({page:'plan-pockets',studyId});return;}
  if(step.module==='A06'){navigate({page:'study',studyId,moduleId:'A06'});return;}
  document.getElementById(step.target)?.scrollIntoView({block:'start',behavior:'smooth'});
 }
 return <section className="card stack" id="plan-preparation" style={{scrollMarginTop:90,gap:16}}><h2>本批结构与配体准备</h2>
  <p>{info.message_zh}</p>
  {info.scope&&<Alert type="info" showIcon message={`固定范围：${info.scope.compounds.length} 成分 × ${info.scope.receptors.length} 受体，共 ${info.scope.pair_count} 组`}
   description="仅消费已经分别复核的完整名单，准备失败的对象保留原位置和原因，不补位或填零。"/>}
  {!info.enabled&&<Alert type="info" showIcon message={info.blockers.join('；')}/>}
  {current&&<Alert type={current.completed?'info':'warning'} showIcon message={current.completed?'当前准备已归档；资料核查、整体复核与评分分别进行':'当前准备未完整归档；原件保留，请先查看后台任务'}
   description={!current.matches_input?'当前准备属于其他输入批次，不能借用为本批结果':!current.completed?'若任务已失败或中断，刷新后按当前版本重新明确执行；不会自动重启。':summary?`可用组合 ${String(summary.ready_pairs??'—')}，NA ${String(summary.na_pairs??'—')}，已评分 ${String(summary.scored_pairs??'—')}`:undefined}/>}
  {info.scope&&<Descriptions size="small" column={{xs:1,sm:2,lg:3}} items={[
   {key:'exhaustiveness',label:'Vina搜索投入',children:String(info.parameters['a06.exhaustiveness'])},
   {key:'num_modes',label:'最多输出姿势',children:String(info.parameters['a06.num_modes'])},
   {key:'energy_range',label:'输出能量差范围',children:String(info.parameters['a06.energy_range'])+' kcal/mol'},
   {key:'seed',label:'固定随机种子',children:String(info.parameters['a06.seed'])},
   {key:'padding',label:'搜索盒每侧外扩',children:String(info.parameters['a06.box_padding'])+' Å'},
   {key:'rmsd',label:'方案RMSD上限',children:String(info.parameters['a06.redocking_rmsd_max'])+' Å（严格标准仍不放宽）'}]}/>}
  <div className="stack" style={{gap:10}}>
   <Input aria-label="结构准备执行人" placeholder="实际执行人" maxLength={2000} value={author} disabled={busy||!info.enabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="结构准备执行依据" placeholder="核对本批名单、参数和来源要求后填写依据" maxLength={2000} value={note} disabled={busy||!info.enabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy||!info.enabled} onChange={e=>setConfirmed(e.target.checked)}>确认连接本批官方来源并准备结构与配体；不评分或自动批准</Checkbox>
   <Button type="primary" loading={busy} disabled={!info.enabled||!author.trim()||!note.trim()||!confirmed} onClick={execute}>开始本批结构与配体准备（不评分）</Button>
  </div>
  <h3>同批后续环节</h3>
  <Table size="small" rowKey="key" pagination={false} scroll={{x:650}} dataSource={info.steps} columns={[
   {title:'环节',dataIndex:'label',width:180},{title:'说明',dataIndex:'detail_zh'},
   {title:'入口',width:100,render:(_,step)=><Button type="link" disabled={!step.available} onClick={()=>open(step)}>前往核对</Button>}]}/>
  {notice&&<Alert showIcon message={notice}/>}
 </section>;
}
