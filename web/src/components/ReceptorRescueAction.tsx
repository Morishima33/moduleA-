// 文件用途：准备页的受体补救入口；原请求续做或主动另立新请求均须明确确认，保留原范围与旧记录。
import { Alert, Button, Checkbox, Input, Radio } from 'antd';
import { useState } from 'react';
import type { ReceptorRescueInfo, ReceptorRescueRequest } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';
import { hrefFor } from '../lib/route';

/** 页面加载不扫描来源或排队；后端资格和原请求是唯一执行依据。 */
export default function ReceptorRescueAction({studyId}:{studyId:string}) {
  const app=useApp();
  const [info,setInfo]=useState<ReceptorRescueInfo|null>(null);
  const [loading,setLoading]=useState(false),[working,setWorking]=useState(false);
  const [author,setAuthor]=useState(''),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false);
  const [notice,setNotice]=useState<string|null>(null);
  const [replacement,setReplacement]=useState(false);
  const incomplete=info?.state==='incomplete';
  const resume=incomplete&&!replacement;
  const original=resume?info?.request:null;
  const bound=!!info?.expected_preparation_run_id&&!!info.expected_scoring_run_id&&!!info.expected_input_hash;
  const enabled=!!info?.enabled&&!info.busy&&bound&&(!resume||!!original);
  const canSubmit=enabled&&!loading&&!working&&!!author.trim()&&!!note.trim()&&confirmed;
  const missing=[!author.trim()?'填写执行人':'',!note.trim()?'填写执行依据':'',!confirmed?'主动勾选范围确认':''].filter(Boolean);

  /** 明确读取会清除旧确认；不因页面刷新或后台任务变化自动重试。 */
  async function load() {
    if(loading||working)return;
    setLoading(true);setInfo(null);setReplacement(false);setConfirmed(false);setNotice(null);
    try {
      const value=await api.receptorRescue(studyId);
      setInfo(value);setAuthor(value.state==='incomplete'?value.request?.author||'':'');
      setNote(value.state==='incomplete'?value.request?.note||'':'');
    }catch(error){setNotice(errorText(error));}finally{setLoading(false);}
  }

  /** 新请求必须主动选择并清空依据与确认；返回原模式时恢复原请求原文。 */
  function selectReplacement(next:boolean) {
    if(!info||info.state!=='incomplete'||info.busy||loading||working)return;
    setReplacement(next);setConfirmed(false);
    setAuthor(next?'':info.request?.author||'');setNote(next?'':info.request?.note||'');
  }

  /** 新请求生成独立编号并绑定所见来源；默认续做仍原样提交归档请求。 */
  async function execute() {
    if(!canSubmit||!info)return;
    const body:ReceptorRescueRequest=original?{...original}:{
      request_id:'rescue_'+crypto.randomUUID().replace(/-/g,''),
      expected_preparation_run_id:info.expected_preparation_run_id!,expected_scoring_run_id:info.expected_scoring_run_id!,
      expected_input_hash:info.expected_input_hash!,author,note,confirmed:true};
    setWorking(true);setNotice(null);
    try {
      const response=await api.executeReceptorRescue(studyId,body,info.schema_version);
      app.trackTasks([response.task]);app.openTasks(response.task.task_id);setNotice(response.message_zh);app.bumpRefresh();
    }catch(error){setNotice(errorText(error));app.bumpRefresh();}
    finally{setConfirmed(false);setReplacement(false);setInfo(null);setWorking(false);}
  }

  return <section className="card stack" id="receptor-rescue-action" style={{gap:12,minWidth:0,scrollMarginTop:90}}>
    <h2>本批受体补救与新增评分</h2>
    <p>保持本批固定名单和全部组合，补救未通过受体；原评分、NA与原因保留，新A06结果另行独立复核。</p>
    <Button style={{alignSelf:'flex-start'}} loading={loading} disabled={working} onClick={load}>
      {info?'刷新补救资格':'查看补救资格与入口'}
    </Button>
    {info?.state==='complete'?<>
      <Alert type="info" showIcon message="本轮补救结果已归档；科学结果仍按本轮复核状态处理。"/>
      {info.current_run_id&&<p className="small muted" style={{overflowWrap:'anywhere'}}>本轮运行：{info.current_run_id}</p>}
      <Button type="primary" href={hrefFor({page:'study',studyId,moduleId:'A06'})} style={{alignSelf:'flex-start'}}>查看本轮A06结果</Button>
    </>:info&&<>
      {info.blockers.length>0&&<Alert type="info" showIcon message={info.blockers.join('；')}/>}
      {info.enabled&&!bound&&<Alert type="warning" showIcon message="当前资格缺少来源版本或指纹，请重新读取资格。"/>}
      {incomplete&&<Radio.Group aria-label="未完成补救请求处理方式" value={replacement?'replacement':'resume'}
        disabled={loading||working||info.busy} onChange={event=>selectReplacement(event.target.value==='replacement')}
        style={{display:'flex',flexWrap:'wrap',gap:8}}>
        <Radio value="resume">继续原请求</Radio><Radio value="replacement">使用新请求</Radio>
      </Radio.Group>}
      {incomplete&&info.current_run_id&&<p className="small muted" style={{margin:0,overflowWrap:'anywhere'}}>原未完成运行：{info.current_run_id}</p>}
      {resume&&<Alert type="info" showIcon message="续做本批已登记请求；执行人、依据与来源版本保持原样，需重新主动确认。"/>}
      {incomplete&&replacement&&<Alert type="warning" showIcon message="旧运行和检查点保留；新请求绑定当前显示的原准备、原评分与来源指纹。"
        description="请重新填写执行人和依据并主动确认。切换选项只改变本页输入，不提交任务。"/>}
      {resume&&!original&&<Alert type="warning" showIcon message="本批未返回已登记续做请求，请重新读取资格。"/>}
      <Input aria-label="受体补救执行人" placeholder="实际执行人" maxLength={2000} value={author} readOnly={resume}
        disabled={!enabled||working} onChange={event=>{setAuthor(event.target.value);setConfirmed(false);}}/>
      <Input.TextArea aria-label="受体补救执行依据" placeholder="填写本次已核对的固定范围与计算授权依据" maxLength={2000} value={note} readOnly={resume}
        disabled={!enabled||working} onChange={event=>{setNote(event.target.value);setConfirmed(false);}}/>
      <Checkbox checked={confirmed} disabled={!enabled||working} onChange={event=>setConfirmed(event.target.checked)}>
        确认按本批固定范围补救受体并计算新增可用组合；保留原评分、NA与独立复核
      </Checkbox>
      {enabled&&missing.length>0&&<p className="small muted" style={{margin:0}}>执行前还需：{missing.join('、')}。</p>}
      <Button type="primary" loading={working} disabled={!canSubmit} onClick={execute} style={{alignSelf:'flex-start',maxWidth:'100%',whiteSpace:'normal',height:'auto',minHeight:32}}>
        {incomplete&&replacement?'使用新请求开始本批受体补救与评分':resume?'继续本批受体补救与评分':'开始本批受体补救与评分'}
      </Button>
    </>}
    {notice&&<Alert type="info" showIcon message={notice}/>}
  </section>;
}
