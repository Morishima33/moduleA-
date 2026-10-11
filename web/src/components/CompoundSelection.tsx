// 当前A03成分核查；保存选择与模块复核分开，旧失效名单不会自动选中。
import {Alert,Button,Checkbox,Collapse,Input,Table,message} from 'antd';
import {useEffect,useState} from 'react';
import type {CompoundSelectionInfo,CompoundChoiceRow} from '../api/types';
import {api,errorText} from '../api/client';
import {useApp} from '../lib/appContext';

// 完整候选跨页保留用户选择，科学资格由原选择内核判定。
export default function CompoundSelection({studyId,info}:{studyId:string;info:CompoundSelectionInfo}){
 const app=useApp();const [selected,setSelected]=useState<string[]>(info.current_selected||[]);
 const [reviewer,setReviewer]=useState('');const [reason,setReason]=useState('');const [confirmed,setConfirmed]=useState(false);
 const [manual,setManual]=useState<Record<string,string>>({});const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 useEffect(()=>{setSelected(info.current_selected||[]);setConfirmed(false)},[info.expected_a03,info.expected_select]);
 async function save(){setBusy(true);setError('');try{
  const result=await api.saveCompoundSelection(studyId,{expected_a03:info.expected_a03,expected_select:info.expected_select,selected,manual_supplements:Object.fromEntries(Object.entries(manual).filter(([k,v])=>selected.includes(k)&&v.trim())),reviewer,reason,confirmed});
  app.trackTasks([result.task]);app.bumpRefresh();message.success(result.message_zh);
 }catch(e){setError(errorText(e))}finally{setBusy(false)}}
 if(!info.enabled)return <section className="card"><h2>对接成分核查</h2><Alert type="warning" message={info.disabled_reason_zh}/></section>;
 return <section className="card" id="a03-compound-selection"><h2>对接成分：先保存名单，再在复核栏确认</h2>
 <p className="small">{info.rule_zh}</p>
 {!info.previous_active&&info.previous_rows?.length>0&&<Collapse size="small" items={[{key:'old',label:'旧失效选择（仅供对照，不自动复用）',children:info.previous_rows.map(r=>r.name+'（'+r.compound_id+'）').join('、')}]}/>}
 <div className="toolbar"><Button onClick={()=>{setSelected(info.rows.filter(r=>r.eligible&&!r.suggestion_zh.startsWith('需逐项')).map(r=>r.compound_id));setConfirmed(false)}}>选择当前建议及边界并列</Button><Button onClick={()=>{setSelected([]);setConfirmed(false)}}>全部取消</Button><span>已选 {selected.length} 个</span></div>
 <Table<CompoundChoiceRow> rowKey="compound_id" size="small" dataSource={info.rows} pagination={{pageSize:25,showSizeChanger:false}} scroll={{x:850}}
 rowSelection={{selectedRowKeys:selected,preserveSelectedRowKeys:true,onChange:keys=>{setSelected(keys.map(String));setConfirmed(false)},getCheckboxProps:r=>({disabled:!r.eligible})}}
 columns={[{title:'成分编号',dataIndex:'compound_id'},{title:'成分名称',dataIndex:'name'},{title:'药味来源',dataIndex:'herbs',render:(v:string[])=>Array.isArray(v)?v.join('、'):String(v||'')},{title:'交集靶点数',dataIndex:'intersection_count'},{title:'当前规则',dataIndex:'suggestion_zh'},{title:'人工补充理由（需要时填写）',render:(_,r)=><Input aria-label={'人工补充理由 '+r.compound_id} value={manual[r.compound_id]||''} onChange={e=>{setManual({...manual,[r.compound_id]:e.target.value});setConfirmed(false)}}/>}]}/>
 <div style={{display:'flex',gap:12,flexWrap:'wrap'}}><Input aria-label="成分核验人" placeholder="成分核验人" value={reviewer} onChange={e=>setReviewer(e.target.value)} style={{width:220}}/><Input.TextArea aria-label="成分选择依据" placeholder="成分选择与身份核验依据" value={reason} onChange={e=>setReason(e.target.value)} style={{flex:'1 1 300px'}}/></div>
 <Checkbox checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>已核对所选成分身份及选择依据</Checkbox>
 <Button type="primary" loading={busy} disabled={!confirmed||!reviewer.trim()||!reason.trim()||selected.length===0} onClick={save}>保存新版成分选择（待独立复核）</Button>
 {error&&<Alert type="error" message={error}/>}<p className="small muted">保存不会批准成分名单，也不会启动结构准备或分子对接。</p>
 </section>
}
