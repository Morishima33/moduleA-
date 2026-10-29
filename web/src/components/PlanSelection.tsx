// 文件用途：将原后台受体名单、独立复核与固定输入入口串联，页面不计算科学名单。
import { Alert, Button, Checkbox, Input, Radio, Table } from 'antd';
import { useState } from 'react';
import type { Decision, PlanSelectionUiInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 三项操作分别明确确认，任何一次完成都不代替下一项或人工批准。 */
export default function PlanSelection({studyId,info}:{studyId:string;info:PlanSelectionUiInfo}) {
 const app=useApp();const [operator,setOperator]=useState('');const [note,setNote]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [reviewer,setReviewer]=useState('');const [reviewNote,setReviewNote]=useState('');const [decision,setDecision]=useState<Decision|undefined>();const [reviewConfirmed,setReviewConfirmed]=useState(false);
 const [author,setAuthor]=useState('');const [inputNote,setInputNote]=useState('');const [inputConfirmed,setInputConfirmed]=useState(false);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);const selection=info.selection,review=info.selection_review;
 const gen=info.operations.selection,rev=info.operations.review,input=info.operations.input;
 const requestId=()=> 'planreq_'+crypto.randomUUID().replace(/-/g,'');
 /** 使用现有严格接口，不添加客户端阈值、名单或准备状态。 */
 async function execute(kind:'selection'|'review'|'input') {setBusy(true);setNotice(null);try{
  if(kind==='review'&&selection&&decision){await api.reviewPlanReceptors(studyId,selection.selection_id,{
   request_id:requestId(),expected_a00:info.expected_a00,expected_a04:info.expected_a04,selection_id:selection.selection_id,
   expected_review_id:review?.review_id??null,decision,reviewer,note:reviewNote});setNotice('受体名单复核决定已保存；未启动结构准备或评分。');
  }else if(kind==='selection'){
   const r=await api.generatePlanReceptors(studyId,{request_id:requestId(),expected_a00:info.expected_a00,
    expected_a04:info.expected_a04,expected_plan_id:info.expected_plan_id,author:operator,note});
   app.trackTasks([r.task]);app.openTasks(r.task.task_id);setNotice(r.message_zh);
  }else if(kind==='input'&&selection&&review){
   const r=await api.savePlanPreparationInput(studyId,{request_id:requestId(),expected_a00:info.expected_a00,
    expected_a03:info.expected_a03,expected_a03_select:info.expected_a03_select,expected_a04:info.expected_a04,
    expected_selection_id:selection.selection_id,expected_selection_review_id:review.review_id,
    expected_plan_id:info.expected_plan_id,author,note:inputNote});
   app.trackTasks([r.task]);app.openTasks(r.task.task_id);setNotice(r.message_zh);
  }
  setConfirmed(false);setReviewConfirmed(false);setInputConfirmed(false);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));setConfirmed(false);setReviewConfirmed(false);setInputConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
 return <section className="card stack" id="plan-selection" style={{scrollMarginTop:90,gap:16}}><h2>本方案受体名单与对接固定输入</h2>
  <p>{info.message_zh}</p>
  <p>本批模式：{({degree:'Degree',bc_cc:'BC＋CC',dual_ab:'双分支A/B'} as Record<string,string>)[String(info.parameters['a04.mode'])]??'尚未绑定'}；目标受体 {String(info.parameters['a06.receptor_count']??'—')} 项；STRING 最低置信度 {String(info.parameters['a04.required_score']??'—')}。</p>
  {info.newer_draft&&<Alert type="info" showIcon message="另有新草稿，本批继续使用原A04绑定方案；新草稿不会替换本批参数或名单。"/>}
  <section id="plan-receptor-generate" className="stack" style={{gap:10}}><h3>1. 生成本批受体名单</h3>
   {!gen.enabled&&<Alert type="info" message={gen.blockers.join('；')}/>}
   <Input aria-label="受体名单执行人" placeholder="执行人" maxLength={2000} value={operator} disabled={busy||!gen.enabled} onChange={e=>{setOperator(e.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="受体名单执行依据" placeholder="核对本批网络与方案后填写依据" maxLength={2000} value={note} disabled={busy||!gen.enabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy||!gen.enabled} onChange={e=>setConfirmed(e.target.checked)}>确认按本批A04绑定方案生成受体名单；名单另行复核</Checkbox>
   <Button type="primary" loading={busy} disabled={!gen.enabled||!operator.trim()||!note.trim()||!confirmed} onClick={()=>execute('selection')}>生成本批受体名单（待复核）</Button>
  </section>
  {selection&&<><h3>实际受体名单：{selection.selection.actual_count} 项（目标 {selection.selection.requested_count}）</h3>
   <Table aria-label="本批已归档受体名单" rowKey="target_id" size="small" scroll={{x:650}} pagination={{pageSize:10}} dataSource={selection.selection.selected} columns={[
    {title:'顺序',dataIndex:'selection_order'},{title:'受体',dataIndex:'symbol'},{title:'组别',dataIndex:'candidate_grade',render:v=>v??'未分组'},
    {title:'Degree',dataIndex:'degree'},{title:'BC',dataIndex:'bc'},{title:'CC',dataIndex:'cc'}]}/>
   <p>边界并列完整保留，不足按实际；后续准备失败留因，不替换低排名受体。</p></>}
  <section id="plan-receptor-review" className="stack" style={{gap:10}}><h3>2. 独立复核受体名单</h3>
   {review&&<Alert type="info" message={'已有决定：'+({approved:'通过',rejected:'退回',pending:'暂存'} as Record<string,string>)[review.decision]} description={review.reviewer+'：'+review.note}/>}
   {!rev.enabled&&<Alert type="info" message={rev.blockers.join('；')}/>}
   <Radio.Group aria-label="受体名单复核决定" value={decision} disabled={busy||!rev.enabled} onChange={e=>{setDecision(e.target.value);setReviewConfirmed(false);}}>
    <Radio value="approved">通过</Radio><Radio value="rejected">退回</Radio><Radio value="pending">暂存／撤回通过</Radio>
   </Radio.Group>
   <Input aria-label="受体名单复核人" placeholder="实际复核人" maxLength={2000} value={reviewer} disabled={busy||!rev.enabled} onChange={e=>{setReviewer(e.target.value);setReviewConfirmed(false);}}/>
   <Input.TextArea aria-label="受体名单复核依据" placeholder="核对名单、来源与选择规则后填写意见" maxLength={2000} value={reviewNote} disabled={busy||!rev.enabled} onChange={e=>{setReviewNote(e.target.value);setReviewConfirmed(false);}}/>
   <Checkbox checked={reviewConfirmed} disabled={busy||!rev.enabled} onChange={e=>setReviewConfirmed(e.target.checked)}>已核对本批实际受体名单，确认保存所选复核决定</Checkbox>
   <Button type="primary" loading={busy} disabled={!rev.enabled||!decision||!reviewer.trim()||!reviewNote.trim()||!reviewConfirmed} onClick={()=>execute('review')}>仅保存受体名单复核决定</Button>
  </section>
  <section id="plan-input-save" className="stack" style={{gap:10}}><h3>3. 保存本批对接固定输入</h3>
   <p>绑定已独立通过的成分和受体名单，以及同源交集、网络、方案与复核版本。此操作不下载结构、不执行评分。</p>
   {!input.enabled&&<Alert type="info" message={input.blockers.join('；')}/>}
   {info.current_input&&<Alert type="success" showIcon message={`固定输入已保存：${info.current_input.packet.compounds.length} 成分 × ${info.current_input.packet.receptors.length} 受体，共 ${info.current_input.packet.pair_count} 组；尚未执行结构准备或评分。`}/>}
   <Input aria-label="固定输入登记人" placeholder="登记人" maxLength={2000} value={author} disabled={busy||!input.enabled} onChange={e=>{setAuthor(e.target.value);setInputConfirmed(false);}}/>
   <Input.TextArea aria-label="固定输入登记依据" placeholder="核对两份名单、同源版本和全部实际范围后填写依据" maxLength={2000} value={inputNote} disabled={busy||!input.enabled} onChange={e=>{setInputNote(e.target.value);setInputConfirmed(false);}}/>
   <Checkbox checked={inputConfirmed} disabled={busy||!input.enabled} onChange={e=>setInputConfirmed(e.target.checked)}>确认固定本批全部成分与受体组合；结构准备和评分分别执行</Checkbox>
   <Button type="primary" loading={busy} disabled={!input.enabled||!author.trim()||!inputNote.trim()||!inputConfirmed} onClick={()=>execute('input')}>保存本批固定输入（不准备、不评分）</Button>
  </section>
  {notice&&<Alert showIcon message={notice}/>}
 </section>;
}
