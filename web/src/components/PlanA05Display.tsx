// 文件用途：同批A05分类、核译和展示决定，完整原统计与科学复核由原模块独立保存。
import {Alert,Button,Checkbox,Collapse,Input,Select,Table} from 'antd';
import {useState} from 'react';
import {api,apiUrl,errorText} from '../api/client';
import type {PlanA05DisplayChoice,PlanA05DisplayInfo,PlanA05DisplayRow,PlanA05Translation} from '../api/types';
import {useApp} from '../lib/appContext';

/** 展示范围与核译是完整明确决定；恢复已有内容不会恢复整体确认。 */
export default function PlanA05Display({studyId,info}:{studyId:string;info:PlanA05DisplayInfo}){
 const app=useApp();const current=info.current,p=current?.presentation,previous=current?.decision;
 const [author,setAuthor]=useState(''),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false);
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState<string|null>(null);
 const [excluded,setExcluded]=useState<string[]>(previous?.excluded_ids??[]);
 const [choices,setChoices]=useState<Record<string,PlanA05DisplayChoice>>(Object.fromEntries((previous?.uncertain_decisions??[]).map(v=>[v.ID,v])));
 const [translations,setTranslations]=useState<Record<string,PlanA05Translation>>(Object.fromEntries((previous?.translations??[]).map(v=>[v.ID,v])));
 const rows=p?.tables.kegg_catalog??[],unknown=rows.filter(r=>r.classification_status==='uncertain');
 const terms=Array.from(new Map(Object.values(p?.tables??{}).flat().map(row=>[row.ID,row])).values());
 const enabled=info.enabled&&!busy;
 const invalidChoice=Object.values(choices).some(v=>!v.reason.trim());
 const overrides=Object.values(translations).filter(v=>v.zh.trim()||v.reason.trim());
 const invalidTranslation=overrides.some(v=>!v.zh.trim()||!v.reason.trim());
 /** 所有编辑都会撤销确认，未知分类没有默认保留/排除。 */
 function changeChoice(row:PlanA05DisplayRow,value:PlanA05DisplayChoice['decision']){
  setChoices(v=>({...v,[row.ID]:{ID:row.ID,decision:value,reason:v[row.ID]?.reason??''}}));
  setExcluded(v=>value==='exclude'?Array.from(new Set([...v,row.ID])):v.filter(id=>id!==row.ID));setConfirmed(false);
 }
 /** 核译严格携带后端原英文及编号，不猜词义或修改科学身份。 */
 function changeTranslation(row:PlanA05DisplayRow,key:'zh'|'reason',value:string){
  setTranslations(v=>({...v,[row.ID]:{ID:row.ID,english:row.english,zh:v[row.ID]?.zh??'',reason:v[row.ID]?.reason??'',[key]:value}}));setConfirmed(false);
 }
 /** 仅用户明确提交后启动后台；不重算R或提交科学批准。 */
 async function submit(){setBusy(true);setNotice(null);try{
  const action=current?'confirm':'prepare';
  const body={request_id:'a05displayreq_'+crypto.randomUUID().replace(/-/g,''),expected_a05:info.expected_a05,
   expected_display_id:info.expected_display_id,expected_input_hash:info.expected_input_hash,author,note,confirmed:true,
   ...(current?{excluded_ids:excluded,uncertain_decisions:Object.values(choices),translations:overrides}:{})};
  const result=await api.savePlanA05Display(studyId,action,body);app.trackTasks([result.task]);app.openTasks(result.task.task_id);
  setConfirmed(false);setNotice(result.message_zh);app.bumpRefresh();
 }catch(e){setNotice(errorText(e));setConfirmed(false);app.bumpRefresh();}finally{setBusy(false);}}
 return <section className="card" id="plan-a05-display" style={{scrollMarginTop:90}}>
  <h2>本批A05分类、核译与展示决定</h2><p>{info.message_zh}</p>
  <p>对象：当前A05已归档显著条目；来源：本批R统计、固定KEGG分类与编号对应核译。图／表按本统计绑定方案截取，完整统计保留。</p>
  {info.blockers.length>0&&<Alert type="warning" showIcon message={info.blockers.join('；')}/>}
  {p&&<>
   <Alert type={p.ready_for_display?'success':'info'} showIcon message={p.ready_for_display?'本次展示决定已保存；A05科学结果仍按原复核栏独立决定':`本批待核译 ${p.missing_translations.length} 项、分类待判断 ${p.unresolved_classifications.length} 项；可明确暂缓并留因，不修改完整统计`}/>
   <Table style={{marginTop:12}} size="small" rowKey="group" pagination={false} scroll={{x:600}} dataSource={p.groups} columns={[
    {title:'类别',dataIndex:'group'},{title:'实际纳入',render:(_,r)=>r.included?'已纳入':'本方案未纳入'},
    {title:'完整显著',dataIndex:'significant_count',render:v=>v??'不适用'},{title:'展示范围',dataIndex:'retained_count',render:v=>v??'不适用'},
    {title:'图／表条目',render:(_,r)=>r.included?`${r.plot_count}／${r.table_count}`:'不适用'}]}/>
   {p.groups.find(g=>g.group==='KEGG')?.included?<><h3>KEGG完整显著集合的分类与拟排除</h3>
   <p className="small muted">勾选仅表示本次展示排除，拟排除项不默认勾选。分类待判断请在下表逐项决定；暂缓与排除分别留存。</p>
   <Table aria-label="本批KEGG分类清单" size="small" rowKey="ID" pagination={{pageSize:8}} scroll={{x:950}} dataSource={rows}
    rowSelection={{selectedRowKeys:excluded,onChange:keys=>{setExcluded(keys.map(String));setConfirmed(false);},getCheckboxProps:r=>({disabled:!enabled||r.classification_status==='uncertain'})}}
    columns={[{title:'稳定编号／原英文',render:(_,r)=><>{r.ID}<br/>{r.english}</>},{title:'官方分类',dataIndex:'classification_zh'},
     {title:'本批核查依据',dataIndex:'reason_zh'},{title:'分类建议',render:(_,r)=>r.classification_status==='exclude'?'拟排除，待明确选择':r.classification_status==='uncertain'?'待判断':'保留候选机制'},
     {title:'此前展示决定',render:(_,r)=>r.deferred?'暂缓':r.excluded?'展示排除':'未排除'}]}/></>:<Alert style={{marginTop:12}} type="info" message="本方案未纳入KEGG：本批分类与排除不适用，不表示零显著。"/>}
   {unknown.length>0&&<><h3>分类待判断逐项决定</h3><Table aria-label="分类待判断决定" size="small" rowKey="ID" pagination={{pageSize:5}} scroll={{x:800}} dataSource={unknown} columns={[
    {title:'编号／原英文',render:(_,r)=><>{r.ID}<br/>{r.english}</>},
    {title:'明确决定',render:(_,r)=><Select aria-label={`分类决定-${r.ID}`} style={{width:150}} disabled={!enabled} value={choices[r.ID]?.decision} placeholder="尚未决定"
     options={[{value:'retain',label:'保留展示'},{value:'exclude',label:'排除展示'},{value:'defer',label:'留因暂缓'}]} onChange={v=>changeChoice(r,v)}/>},
    {title:'逐项依据',render:(_,r)=><Input.TextArea aria-label={`分类依据-${r.ID}`} disabled={!enabled||!choices[r.ID]} placeholder="先选择明确决定，再填写依据" rows={2} maxLength={2000} value={choices[r.ID]?.reason??''}
     onChange={e=>{const text=e.target.value;setChoices(v=>v[r.ID]?({...v,[r.ID]:{...v[r.ID],reason:text}}):v);setConfirmed(false);}}/>}]} /></>}
   <h3>编号与原英文对应核译</h3><p className="small muted">已有词典核译与本研究明确核译分开保存，均不称为官方中文。缺译可暂存，图表采用原英文并标明待核译；需要使用的条目缺译时展示资料仍待补。</p>
   <Table aria-label="本批条目核译" size="small" rowKey="ID" pagination={{pageSize:5}} scroll={{x:1000}} dataSource={terms} columns={[
    {title:'编号／原英文',render:(_,r)=><>{r.ID}<br/>{r.english}</>},{title:'当前核译',render:(_,r)=>r.description_zh||'中文待核译'},
    {title:'本研究明确中文',render:(_,r)=><Input.TextArea aria-label={`中文核译-${r.ID}`} disabled={!enabled} rows={2} maxLength={2000} value={translations[r.ID]?.zh??''} onChange={e=>changeTranslation(r,'zh',e.target.value)}/>},
    {title:'核译依据',render:(_,r)=><Input.TextArea aria-label={`核译依据-${r.ID}`} disabled={!enabled} rows={2} maxLength={2000} value={translations[r.ID]?.reason??''} onChange={e=>changeTranslation(r,'reason',e.target.value)}/>}]} />
   <Collapse style={{marginTop:12}} items={[{key:'tables',label:'查看本批派生图表与完整导出范围',children:<>
    <p>{p.note_zh}</p><p>展示暂缓：{p.deferred_ids.join('、')||'无'}；展示排除：{p.excluded_ids.join('、')||'无'}。原科学统计可从本页追溯／CSV入口获取，派生表单独标识。</p>
    {current?.downloads.filter(v=>v.name.endsWith('.png')).map(v=><div key={v.index} style={{marginBottom:16}}><p><a href={apiUrl(v.url)}>下载 {v.name}</a></p><img loading="lazy" src={apiUrl(v.url+'?inline=1')} alt={`本批展示图 ${v.name}`} style={{maxWidth:'100%',height:'auto'}}/></div>)}
    {current?.downloads.filter(v=>v.name.endsWith('.svg')).map(v=><p key={v.index}><a href={apiUrl(v.url)}>下载可编辑 {v.name}</a></p>)}
   </>},{key:'binding',label:'本批统计与方案版本',children:<div style={{overflowWrap:'anywhere'}}>A05：{info.expected_a05}<br/>方案：{info.plan_id}<br/>参数指纹：{info.parameter_hash}</div>}]}/>
  </>}
  <div className="stack" style={{gap:12,marginTop:16}}>
   <Input aria-label="A05展示登记人" value={author} disabled={!enabled} maxLength={2000} placeholder="展示资料登记人" onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/>
   <Input.TextArea aria-label="A05展示登记依据" value={note} disabled={!enabled} rows={2} maxLength={2000} placeholder="核对同批来源及展示决定后填写依据" onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={!enabled} onChange={e=>setConfirmed(e.target.checked)}>已核对本批统计与展示内容，确认{current?'保存本次展示决定':'准备分类与核译资料'}；不批准A05科学结果</Checkbox>
   <Button type="primary" loading={busy} disabled={!enabled||!author.trim()||!note.trim()||!confirmed||invalidChoice||invalidTranslation} onClick={submit}>{current?'保存本批展示决定':'准备本批分类与核译资料（不重算R）'}</Button>
   {notice&&<Alert showIcon message={notice}/>}
  </div>
 </section>;
}
