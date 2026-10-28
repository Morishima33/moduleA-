// 文件用途：真实新模式建档；预检、一次明确确认和初始方案共同归档，计算能力另行接续。
import { Alert, Button, Checkbox, Col, Form, Input, Radio, Row, Skeleton, Tag } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { AnalysisParameterCatalog, NewStudyInput, PlanCreationPreflight, PlanValue } from '../api/types';
import { hrefFor, navigate } from '../lib/route';
import { useApp } from '../lib/appContext';
import PlanCreationFields from '../components/PlanCreationFields';
import CreationMaterials from '../components/CreationMaterials';

type Intake=Omit<NewStudyInput,'request_id'>;

/** 编辑清除旧预检，迟到响应失效，重试沿用同一创建编号，避免重复研究。 */
export default function PlanStudyCreationPage() {
  const app=useApp(); const [form]=Form.useForm<Intake>();
  const [catalog,setCatalog]=useState<AnalysisParameterCatalog|null>(null);
  const [mode,setMode]=useState<'standard'|'personalized'>('standard');
  const [values,setValues]=useState<Record<string,PlanValue>>({});
  const [preview,setPreview]=useState<PlanCreationPreflight|null>(null);
  const [confirmed,setConfirmed]=useState(false); const [busy,setBusy]=useState<'preflight'|'create'|null>(null);
  const [error,setError]=useState(''); const [reload,setReload]=useState(0);
  const sequence=useRef(0); const submitting=useRef(false);
  const requestId=useRef('plancreate_'+crypto.randomUUID().replace(/-/g,''));
  useEffect(()=>{
    let active=true; setError('');
    api.analysisParameters().then(data=>{if(active){setCatalog(data);setValues(Object.fromEntries(Object.entries(data.parameters).map(([k,v])=>[k,v.default])));}})
      .catch(e=>{if(active)setError(errorText(e));});
    return()=>{active=false;sequence.current++;};
  },[reload]);
  useEffect(()=>{
    if(!preview)return;
    const timeout=window.setTimeout(()=>{setPreview(null);setConfirmed(false);setError('本次预检已过期，请重新预检后确认。');},Math.max(0,Date.parse(preview.expires_at)-Date.now()));
    return()=>window.clearTimeout(timeout);
  },[preview]);

  /** 参数或登记变化即清除凭证与确认，不沿用上一次核查。 */
  function invalidate() {sequence.current++;setPreview(null);setConfirmed(false);setError('');}
  /** 校验普通字段后请求官方身份和真实资料预检，本次不创建研究。 */
  async function preflight() {
    if(submitting.current||busy)return;
    let fields:Intake;try{fields=await form.validateFields();}catch{return;}
    const call=++sequence.current;setBusy('preflight');setPreview(null);setConfirmed(false);setError('');
    try{
      const result=await api.preflightPlanStudy(fields,mode==='standard'?{mode}:{mode,parameters:values});
      if(call===sequence.current)setPreview(result);
    }catch(e){if(call===sequence.current)setError(errorText(e));}
    finally{if(call===sequence.current)setBusy(null);}
  }
  /** 一次明确确认只把当前预检对应的登记、初始方案和缺口共同发布。 */
  async function create() {
    if(submitting.current||busy||!confirmed||!preview?.can_create)return;
    submitting.current=true;const call=++sequence.current;setBusy('create');setError('');
    try{
      const result=await api.createPlanStudy({request_id:requestId.current,preflight_id:preview.preflight_id,expected_input_hash:preview.input_hash,confirmed:true});
      if(call===sequence.current){app.bumpRefresh();navigate({page:'study',studyId:result.study_id,moduleId:'A00'});}
    }catch(e){if(call===sequence.current){setError(errorText(e));setConfirmed(false);}}
    finally{submitting.current=false;if(call===sequence.current)setBusy(null);}
  }
  const defaults=catalog?Object.fromEntries(Object.entries(catalog.parameters).map(([k,v])=>[k,v.default])):{};
  const displayed=mode==='standard'?defaults:values;
  const required=[{required:true,whitespace:true,message:'请填写此项'}];
  return <main className="home plan-preview-page" id="plan-study-creation">
    <div className="plan-page-heading"><div><Tag color="cyan">新版建档</Tag><h1>新建研究 · 标准版／个性化版</h1>
      <p className="muted">先核对登记、方案和资料，再一次确认独立建档。</p></div><Button disabled={!!busy} href={hrefFor({page:'home'})}>返回研究列表</Button></div>
    <Alert type="info" showIcon message="本次只建档并固定初始方案，不自动批准或启动分析。新方案自动接续仍在接入。"/>
    <section className="card"><h2>1. 填写本研究登记</h2>
      <Form form={form} layout="vertical" requiredMark={false} disabled={!!busy} onValuesChange={invalidate}>
        <Row gutter={16}><Col xs={24} sm={12}><Form.Item name="formula" label="方剂名称" rules={required}><Input maxLength={2000}/></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="disease" label="疾病中文名" rules={required}><Input maxLength={2000}/></Form.Item></Col></Row>
        <Form.Item name="herbs" label="药味清单" rules={required}><Input.TextArea maxLength={2000} rows={2}/></Form.Item>
        <Row gutter={16}><Col xs={24} sm={16}><Form.Item name="mesh_term" label="MeSH首选词（英文）" rules={required}><Input maxLength={500}/></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item name="mesh_id" label="MeSH编号" rules={[...required,{pattern:/^D\d{6,9}$/i,message:'请填写D开头的描述词编号'}]}><Input maxLength={10}/></Form.Item></Col></Row>
        <Row gutter={16}><Col xs={24} sm={14}><Form.Item name="analysis_purpose" label="研究用途" rules={[{required:true,message:'请选择用途'}]}>
          <Radio.Group options={[{label:'正式研究',value:'formal_research'},{label:'流程测试',value:'workflow_test'}]}/></Form.Item></Col>
          <Col xs={24} sm={10}><Form.Item name="operator" label="登记人" rules={required}><Input maxLength={2000}/></Form.Item></Col></Row>
      </Form><div className="small muted">物种：人类9606；范围：仅本病，不纳入亚型。MeSH身份由服务端向NLM官方核对。</div>
    </section>
    <section className="card"><h2>2. 选择方式与参数</h2>
      <Radio.Group aria-label="新研究分析方式" value={mode} disabled={!!busy} onChange={e=>{invalidate();setMode(e.target.value);}}>
        <Radio value="standard">标准版（默认方案）</Radio><Radio value="personalized">个性化版</Radio>
      </Radio.Group>
      {!catalog?<div style={{marginTop:16}}>{error?<Button onClick={()=>{setError('');setReload(n=>n+1);}}>重新读取参数</Button>:<Skeleton active/>}</div>:<>
        <p>目标成分 × 受体：<strong>{String(displayed['a06.component_count'])} × {String(displayed['a06.receptor_count'])}</strong>；保留边界并列，不足按实际，准备失败保留NA。</p>
        <PlanCreationFields catalog={catalog} mode={mode} values={displayed} disabled={!!busy} onChange={(key,value)=>{invalidate();setValues(old=>({...old,[key]:value}));}}/>
      </>}
    </section>
    <section className="card stack" id="plan-creation-confirmation"><h2>3. 预检资料并确认建档</h2>
      <Button disabled={!catalog||!!busy} loading={busy==='preflight'} onClick={()=>void preflight()}>核对登记、方案与资料</Button>
      {preview&&<div className="stack" id="plan-creation-preflight-result">
        <Alert type="success" showIcon message={preview.message_zh} description={`NLM已核对：${preview.mesh_verification.preferred_term}（${preview.mesh_verification.mesh_id}）`}/>
        <CreationMaterials value={preview.materials}/>
        {preview.plan.warnings.map(w=><Alert key={w.code} type="warning" showIcon message={w.message_zh}/>)}
        <div className="small mono" style={{overflowWrap:'anywhere'}}>初始方案指纹：{preview.plan.parameter_hash}</div>
        <Checkbox disabled={!!busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>我已核对本研究登记、方案及资料缺口，确认只建档，不启动分析</Checkbox>
      </div>}
      <Button type="primary" size="large" loading={busy==='create'} disabled={!!busy||!preview?.can_create||!confirmed} onClick={()=>void create()}>确认建档并固定初始方案</Button>
      {error&&<Alert type="error" showIcon message={error}/>}
    </section>
  </main>;
}
