// 当前成分核查放在首屏；核查草案、名单保存、独立复核分别处理。
import {Alert,Button,Checkbox,Collapse,Input,Table,message} from 'antd';
import {useEffect,useState} from 'react';
import type {CompoundSelectionInfo,CompoundChoiceRow,DockingReviewInfo,DockingReviewCompound} from '../api/types';
import {api,errorText} from '../api/client';
import {useApp} from '../lib/appContext';
import SourceIdentityTrace from './SourceIdentityTrace';

export default function CompoundSelection({studyId,info,review}:{studyId:string;info:CompoundSelectionInfo;review?:DockingReviewInfo|null}){
 const app=useApp();const [selected,setSelected]=useState<string[]>(info.current_selected||[]);
 const [reviewer,setReviewer]=useState('');const [reason,setReason]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [manual,setManual]=useState<Record<string,string>>(info.current_manual_supplements||{});const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 useEffect(()=>{setSelected(info.current_selected||[]);setConfirmed(false);setManual(info.current_manual_supplements||{})},[info.expected_a03,info.expected_select,review?.review_id]);
 const draft=review?.proposal;const disabled=!info.enabled||review?.enabled===false;
 const scope=info.extended_scope;
 function loadExtended(){if(!scope)return;const eligible=new Set(info.rows.filter(r=>r.eligible).map(r=>r.compound_id));const ids=scope.proposed_ids.filter(id=>eligible.has(id));setSelected(ids);setManual(Object.fromEntries(Object.entries(scope.manual_reasons).filter(([id])=>ids.includes(id))));setConfirmed(false);}
 // 批量操作仅载入可核查项及补充依据，不勾选身份确认、不保存。
 function loadProposed(){if(!draft)return;setSelected(draft.compounds.filter(r=>r.identity_prechecked&&info.rows.some(x=>x.compound_id===r.compound_id&&x.eligible)).map(r=>r.compound_id));setManual(Object.fromEntries(draft.compounds.filter(r=>info.rows.find(x=>x.compound_id===r.compound_id)?.suggestion_zh.startsWith('需逐项')).map(r=>[r.compound_id,r.manual_reason_zh])));setConfirmed(false)}
 async function save(){setBusy(true);setError('');try{
  const result=await api.saveCompoundSelection(studyId,{expected_a03:info.expected_a03,expected_select:info.expected_select,...(review?.review_id?{expected_docking_review:review.review_id}:{}),selected,manual_supplements:Object.fromEntries(Object.entries(manual).filter(([k,v])=>selected.includes(k)&&v.trim())),reviewer,reason,confirmed});
  app.trackTasks([result.task]);app.bumpRefresh();message.success(result.message_zh);
 }catch(e){setError(errorText(e))}finally{setBusy(false)}}
 const selection={selectedRowKeys:selected,preserveSelectedRowKeys:true,onChange:(keys:React.Key[])=>{setSelected(keys.map(String));setConfirmed(false)},getCheckboxProps:(r:CompoundChoiceRow)=>({disabled:disabled||!r.eligible})};
 const full=<Table<CompoundChoiceRow> rowKey="compound_id" size="small" dataSource={info.rows} pagination={{pageSize:25,showSizeChanger:false}} scroll={{x:950}} rowSelection={selection}
 columns={[{title:'成分名称',dataIndex:'name'},{title:'药味来源',dataIndex:'herbs',render:(v:string[]|string)=>Array.isArray(v)?v.join('、'):v},{title:'交集靶点数',dataIndex:'intersection_count'},{title:'原名次',dataIndex:'main_rank'},{title:'当前规则',dataIndex:'suggestion_zh'},{title:'人工补充理由',render:(_,r)=><Input aria-label={'人工补充理由 '+r.compound_id} value={manual[r.compound_id]||''} onChange={e=>{setManual({...manual,[r.compound_id]:e.target.value});setConfirmed(false)}}/>}]}/>;
 return <section className="card" id="a03-compound-selection"><h2>对接成分核查：名单、身份与药味来源、补充依据</h2>
 <p className="small">保存名单与独立结果复核分开；本轮不启动对接计算。</p>
 {scope&&<section id="extended-docking-scope" className="stack" style={{scrollMarginTop:90}}>
  <Alert type={scope.ready?'success':'warning'} showIcon message={`主候选前${scope.primary_limit}与扩展筛查分开：当前已保存${scope.selected_count}项，扩展目标${scope.required_count}项${scope.proposed_count>scope.required_count?'（建议含截断并列）':''}。`} description={scope.note_zh}/>
  <Button type="primary" disabled={disabled||!scope.proposed_ids.length} onClick={loadExtended}>载入前{scope.required_count}项扩展筛查草稿{scope.proposed_count>scope.required_count?'（含并列）':''}</Button>
  <Table<CompoundChoiceRow> aria-label="完整扩展筛查名单" rowKey="compound_id" size="small" pagination={false} scroll={{x:800}} rowSelection={selection}
   dataSource={selected.flatMap(id=>{const row=info.rows.find(r=>r.compound_id===id);return row?[row]:[];})}
   columns={[{title:'成分',dataIndex:'name'},{title:'药味来源',dataIndex:'herbs',render:(v:string[]|string)=>Array.isArray(v)?v.join('、'):v},
    {title:'交集／原名次',render:(_,r)=>`${r.intersection_count}／${r.main_rank}`},{title:'选择角色',render:(_,r)=>r.suggestion_zh.startsWith('需逐项')?'扩展补充':r.suggestion_zh},
    {title:'补充依据（可修改）',render:(_,r)=><Input aria-label={'扩展补充理由 '+r.compound_id} value={manual[r.compound_id]||''} onChange={e=>{setManual({...manual,[r.compound_id]:e.target.value});setConfirmed(false);}}/>}]}/>
  <p className="small">载入后逐项核对成分、来源及补充理由，再填写核验人与整体依据并保存；独立复核通过后，连接与计算使用全部已选项。</p>
 </section>}
 {disabled&&<Alert type="warning" message={review?.reason_zh||info.disabled_reason_zh}/>}
 {draft&&<><p>{draft.note_zh}</p><div className="toolbar"><strong>本轮拟纳入 {draft.compounds.length} 项</strong><Button disabled={disabled} onClick={loadProposed}>全选本轮可确认项并载入补充理由</Button><Button onClick={()=>{setSelected([]);setConfirmed(false)}}>全部取消</Button><span>已选 {selected.length} 个</span></div>
 <Table<DockingReviewCompound> className="docking-compound-table" rowKey="compound_id" size="small" dataSource={draft.compounds.map(r=>({...r,eligible:r.identity_prechecked&&info.rows.some(x=>x.compound_id===r.compound_id&&x.eligible)}))} pagination={false} scroll={{x:750}} rowSelection={selection}
 expandable={{expandedRowRender:r=><div><p>{r.evidence_zh}</p><p>补充入选理由：{r.manual_reason_zh}</p><Input aria-label={'本轮补充理由 '+r.compound_id} value={manual[r.compound_id]||''} onChange={e=>{setManual({...manual,[r.compound_id]:e.target.value});setConfirmed(false)}}/></div>}}
 columns={[{title:'成分（中／英文）',width:190,render:(_,r)=><div><strong>{r.name_zh}</strong><div className="small" style={{overflowWrap:'anywhere'}}>{r.name}</div><span className="tiny muted">CID {r.cid}</span></div>},{title:'药味',width:60,dataIndex:'herbs',render:(v:string[]|string)=>Array.isArray(v)?v.join('、'):v},{title:'交集／原名次',width:70,render:(_,r)=>`${r.intersection_count}／${r.main_rank}`},{title:'化学身份与来源',width:165,dataIndex:'identity_state_zh'},{title:'来源三维资料',width:165,dataIndex:'source_3d_state_zh'}]}/>
 {draft.excluded.map(r=><Alert key={r.compound_id} type="warning" message={`${r.name_zh}：暂待补，不在本轮名单`} description={r.reason_zh}/>)}{draft.acetic_trace&&<SourceIdentityTrace name={draft.excluded[0]?.name_zh||'来源冲突'} info={draft.acetic_trace}/>}</>}
 {!draft&&<div className="toolbar"><Button disabled={disabled} onClick={()=>{setSelected(info.rows.filter(r=>r.eligible&&!r.suggestion_zh.startsWith('需逐项')).map(r=>r.compound_id));setConfirmed(false)}}>选择当前建议及边界并列</Button><Button onClick={()=>{setSelected([]);setConfirmed(false)}}>全部取消</Button><span>已选 {selected.length} 个</span></div>}
 {draft?<Collapse size="small" items={[{key:'full',label:'完整A03排名及其他候选（不改变既有科学规则）',children:full}]}/>:full}
 {!info.previous_active&&info.previous_rows?.length>0&&<Collapse size="small" items={[{key:'old',label:'已失效历史名单（仅供对照）',children:info.previous_rows.map(r=>r.name).join('、')}]}/>}
 <div id="compound-selection-confirmation" style={{display:'flex',gap:12,flexWrap:'wrap',marginTop:16}}><Input aria-label="成分核验人" placeholder="成分核验人" value={reviewer} onChange={e=>{setReviewer(e.target.value);setConfirmed(false)}} style={{width:220}}/><Input.TextArea aria-label="成分选择依据" placeholder="核对名单、化学身份和药味来源后填写依据" value={reason} onChange={e=>{setReason(e.target.value);setConfirmed(false)}} style={{flex:'1 1 300px'}}/></div>
 <Checkbox disabled={disabled} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>已核对所选成分身份、药味来源及补充入选依据</Checkbox>
 <Button type="primary" loading={busy} disabled={disabled||!confirmed||!reviewer.trim()||!reason.trim()||selected.length===0} onClick={save}>保存新版成分选择（待独立复核）</Button>
 {error&&<Alert type="error" message={error}/>}<p className="small muted">全选不自动保存或批准。身份待补项不能勾选；来源三维待补项可核对名单，补齐并质控前不产生评分。</p>
 </section>
}
