// 文件用途：显示同批真实校验和原计算状态，明确提交后台核对，不制造人工批准。
import {Alert,Button,Checkbox,Collapse,Select,Table} from 'antd';
import {useState} from 'react';
import {api,errorText} from '../api/client';
import type {PlanSystemValidationsInfo} from '../api/types';
import {useApp} from '../lib/appContext';

/** 资格和结论来自服务端；选择阶段不启动任务，确认默认不勾选。 */
export default function PlanSystemValidations({studyId,info}:{studyId:string;info:PlanSystemValidationsInfo}){
 const app=useApp();const [module,setModule]=useState<string>();const [confirmed,setConfirmed]=useState(false);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState<string|null>(null);
 const selected=info.items.find(row=>row.module_id===module);
 /** 一次提交使用本次显示的实际运行及完整输入指纹，过期只刷新、不自动重试。 */
 async function execute(){if(!selected?.request)return;setBusy(true);setNotice(null);try{
  const result=await api.executePlanSystemValidation(studyId,{request_id:'syscheckreq_'+crypto.randomUUID().replace(/-/g,''),
   expected_run_id:selected.request.expected_run_id,expected_input_hash:selected.request.expected_input_hash});
  app.trackTasks([result.task]);app.openTasks(result.task.task_id);setNotice(result.message_zh);app.bumpRefresh();
 }catch(error){setNotice(errorText(error));app.bumpRefresh();}finally{setBusy(false);setConfirmed(false);}}
 return <section className="card" id="plan-system-validations" style={{scrollMarginTop:90}}><h2>本批结果核查</h2><p>{info.message_zh}</p>
  <Table size="small" rowKey="module_id" pagination={false} scroll={{x:540}} dataSource={info.items} columns={[
   {title:'阶段',dataIndex:'module_id',width:85},
   {title:'当前核查',render:(_,row)=>row.current?.label_zh??'尚未核查当前输入'},
   {title:'执行条件',render:(_,row)=>row.enabled?'可核对已归档证据':row.blockers.join('；')}]}/>
  <Collapse style={{marginTop:12}} items={[{key:'execute',label:'重新核对一个阶段的证据',children:<div className="stack" style={{gap:12}}>
   <p>核对会调用实际科学工具，可能需要等待。计算失败或资料未齐会保留原因；核查通过不代表研究结论获得人工认可。</p>
   <Select aria-label="结果核查阶段" placeholder="选择要核对的阶段" value={module} disabled={busy} style={{width:'100%'}}
    options={info.items.map(row=>({value:row.module_id,label:row.module_id,disabled:!row.enabled}))}
    onChange={value=>{setModule(value);setConfirmed(false);}}/>
   <Checkbox checked={confirmed} disabled={busy} onChange={event=>setConfirmed(event.target.checked)}>确认核对所选阶段的本批证据</Checkbox>
   <Button type="primary" loading={busy} disabled={!selected?.enabled||!confirmed} onClick={execute}>核对所选阶段证据</Button>
  </div>},{key:'history',label:`历次核查（${info.history.length}）`,children:<Table size="small" rowKey="validation_id" pagination={{pageSize:5}}
   dataSource={info.history} scroll={{x:560}} columns={[{title:'阶段',dataIndex:'module_id',width:70},{title:'实际结论',dataIndex:'label_zh'},
    {title:'原因',render:(_,row)=>row.error_zh??row.scientific_status.note_zh}]}/>}]} />
  {notice&&<Alert style={{marginTop:12}} showIcon message={notice}/>}</section>;
}
