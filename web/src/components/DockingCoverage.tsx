// A06集中核查：同页17项、证据折叠和一次采用；服务端决定资格与覆盖数量。
import {Alert,Button,Checkbox,Collapse,Input,Modal,Table,Tag,message} from 'antd';
import {useEffect,useState} from 'react';
import type {DockingCoverageInfo,DockingCoverageRow} from '../api/types';
import {api,errorText} from '../api/client';
import {useApp} from '../lib/appContext';

// 只显示已归档的技术与采用结果，未确认时不自动选择或启动计算。
export default function DockingCoverage({studyId,info}:{studyId:string;info:DockingCoverageInfo}){
 const {bumpRefresh,trackTasks}=useApp();
 const [open,setOpen]=useState(false),[selected,setSelected]=useState<string[]>([]);
 const [reviewer,setReviewer]=useState(''),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{setSelected(info.draft?.selected_target_ids||[]);setReviewer(info.draft?.reviewer||'');setNote(info.draft?.note||'');setConfirmed(false);setError('')},
  [info.campaign_id,info.expected_run,info.expected_decision_id]);
 const canEdit=info.enabled&&!info.confirmed&&!busy;
 const eligibleIds=info.rows.filter(r=>r.eligible).map(r=>r.target_id);
 // 全选只改变窗口状态；未解决项没有资格进入批量选择。
 function selectAll(){setSelected(eligibleIds);setConfirmed(false)}
 async function save(final:boolean){
  setError('');setBusy(true);
  try{
   const result=await api.saveCoverageSelection(studyId,{expected_run:info.expected_run,expected_source:info.expected_source,
      campaign_id:info.campaign_id,expected_decision_id:info.expected_decision_id,
      selected_target_ids:selected,reviewer,note,confirmed:final});
   message.success(result.message_zh);trackTasks([result.task]);if(final)setOpen(false);bumpRefresh();
  }catch(e){setError(errorText(e))}finally{setBusy(false)}
 }
 // 技术证据默认折叠，用户只需要核对采用结构、用途和无法计算原因。
 function evidence(row:DockingCoverageRow){
  return <Collapse size="small" items={[{key:'evidence',label:'查看两遍及来源证据',children:
   <>{row.attempts.map((a,i)=><div key={i}><strong>{a.round===1?'第一遍':'第二遍独立补救'} · {a.spec.pdb_id||a.spec.model_id||'待补'}</strong>
    <p>{a.reason_zh}</p>
    {a.top1_rmsd!=null&&<p>Top-1 RMSD：{a.top1_rmsd.toFixed(3)} Å</p>}
    {a.pocket&&<><p>首位口袋概率：{String(a.pocket.runs[0]?.probability??'未提供')}；两次一致只说明可重复，位点仍须确认。</p>
      <p className="small">预测位置（Å）：{['center_x','center_y','center_z'].map(k=>String(a.pocket?.runs[0]?.[k]??'未提供')).join('，')}；残基：{String(a.pocket.runs[0]?.residue_ids??'未提供')}。{a.site_coverage?.note_zh}</p></>}
    {a.confidence_facts&&<p>口袋pLDDT均值 {a.confidence_facts.mean_plddt.toFixed(1)}，最低 {a.confidence_facts.min_plddt.toFixed(1)}；最大双向PAE {a.confidence_facts.max_bidirectional_pae_A.toFixed(2)} Å。</p>}
    {!!a.environment_audit?.box_environment.length&&<p>{a.environment_audit.box_environment.map(e=>
      e.chain+':'+e.residue+e.sequence+' '+e.reason_zh).join('；')}</p>}
    </div>)}
    <p className="small">完整原件、预测输出和质控文件见本模块归档文件。未取得结合能评分。</p>
   </>}]}/>;
 }
 const columns=[
  {title:'采用',width:60,render:(_:unknown,r:DockingCoverageRow)=><Checkbox aria-label={'采用'+r.symbol}
   disabled={!canEdit||!r.eligible} checked={info.confirmed?r.adopted:selected.includes(r.target_id)}
   onChange={e=>{setSelected(e.target.checked?[...selected,r.target_id]:selected.filter(x=>x!==r.target_id));setConfirmed(false)}}/>},
  {title:'受体／HGNC',width:150,render:(_:unknown,r:DockingCoverageRow)=><><strong>{r.symbol}</strong><div className="small">{r.target_id}</div></>},
  {title:'A/B',dataIndex:'candidate_grade',width:55},
  {title:'拟采用结构与位点',width:185,render:(_:unknown,r:DockingCoverageRow)=><>{r.pdb_id}
   {r.spec&&<div className="small">作者链 {r.spec.chains.join('、')}；{r.spec.pocket==='reference'?'参考配体 '+r.spec.reference_code+' / '+r.spec.reference_chain+':'+r.spec.reference_sequence:'P2Rank首位口袋（详见证据）'}</div>}
   {r.rmsd_A!=null&&<div className="small">Top-1 RMSD {r.rmsd_A.toFixed(3)} Å</div>}</>},
  {title:'质控类别',width:135,render:(_:unknown,r:DockingCoverageRow)=><Tag color={r.quality_zh==='严格'?'green':r.quality_zh==='探索'?'blue':'default'}>{r.status_zh}</Tag>},
  {title:'处理建议与依据',render:(_:unknown,r:DockingCoverageRow)=><><p>{r.reason_zh}</p>{evidence(r)}</>}
 ];
 return <section id="a06-coverage" className="card" style={{border:'2px solid #0F5E6E',marginBottom:16}}>
  <h3>A06 本轮可用范围：集中核查，一次确认</h3>
  {!info.enabled&&<Alert type="info" message={info.disabled_reason_zh}/>}
  <p><Tag color="green">严格可用 {info.counts.strict}</Tag><Tag color="blue">探索候选 {info.counts.exploration}</Tag>
   <Tag>待补／无法计算 {info.counts.unavailable}</Tag>完整保留 {info.counts.receptors} 个受体。</p>
  <p className="small">{info.note_zh}</p>
  <Button type="primary" onClick={()=>setOpen(true)}>{info.confirmed?'查看本轮已确认范围':'查看汇总并确认可用范围'}</Button>
  {info.confirmed&&<Alert type="success" message={"本轮采用范围已留存；主要结果条件"+(info.conditions.main_results?"已满足":"尚未满足")+"，具备准备输入 "+info.conditions.prepared_pairs+" 个组合。结果批准与批量计算仍分别操作。"}/>}
  <Modal title="核对拟采用结构、位点与严格／探索用途" open={open} onCancel={()=>setOpen(false)} width={1250} styles={{body:{maxHeight:'70vh',overflowY:'auto'}}}
   footer={<><Button onClick={()=>setOpen(false)}>返回</Button><Button disabled={!canEdit} loading={busy}
      onClick={()=>void save(false)}>保存草案</Button><Button type="primary" disabled={!canEdit||!confirmed||!selected.length||!reviewer.trim()||!note.trim()}
      loading={busy} onClick={()=>void save(true)}>确认本轮可用范围</Button></>}>
   <Alert type="info" message="全选不自动保存；只采用具备证据的受体。探索口袋的概率、位置与适用范围请查看证据，确认不启动批量结合能。"/>
   {error&&<Alert type="error" message={error}/>}
   <p><Button disabled={!canEdit} onClick={selectAll}>全选全部可确认项</Button>
    <Button disabled={!canEdit} onClick={()=>{setSelected([]);setConfirmed(false)}}>全部取消</Button>
    <span> 已选 {selected.length} / {eligibleIds.length} 可确认项</span></p>
   <Table rowKey="target_id" size="small" pagination={false} scroll={{x:900}} dataSource={info.rows} columns={columns}/>
   {!info.confirmed&&<><Input aria-label="本轮范围核验人" placeholder="实际核验人" value={reviewer} disabled={!canEdit}
       onChange={e=>{setReviewer(e.target.value);setConfirmed(false)}}/>
    <Input.TextArea aria-label="本轮范围核验依据" placeholder="简要填写采用依据与探索解释范围" value={note} disabled={!canEdit}
       onChange={e=>{setNote(e.target.value);setConfirmed(false)}}/>
    <Checkbox checked={confirmed} disabled={!canEdit||!selected.length} onChange={e=>setConfirmed(e.target.checked)}>
     我已核对所选结构、位点、严格／探索用途与未解决项，确认本轮可用范围；不启动批量计算
    </Checkbox></>}
  </Modal>
 </section>
}
