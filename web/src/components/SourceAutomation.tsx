// 文件用途：三库自动获取、逐药味完整性核查与疾病映射只读预览；不自动保存人工决定。
import { Alert, Button, Checkbox, Form, Input, Modal, Space, Table } from 'antd';
import { useState } from 'react';
import { api, errorText } from '../api/client';
import type { DiseaseCandidatePage, SourceUploadInfo, Task } from '../api/types';
import { useApp } from '../lib/appContext';

/** 所有操作由用户主动触发；当前疾病集合不因预览改变。 */
export default function SourceAutomation({studyId, moduleId, info}: {studyId:string; moduleId:string; info:SourceUploadInfo}) {
  const app=useApp();
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState<string | null>(null);
  const [preview,setPreview]=useState<DiseaseCandidatePage | null>(null);
  const [environment,setEnvironment]=useState<Awaited<ReturnType<typeof api.environment>> | null>(null);
  const versions={expected_a00:info.expected_a00,expected_run:info.expected_run,expected_staging:info.expected_staging};
  const acquisition=info.acquisition, verification=info.verification, mapping=info.mapping_preview;
  /** 将明确提交的操作接入原任务面板，不重复启动或代签。 */
  async function action(run:()=>Promise<{task:Task;message_zh:string}>) {
    setBusy(true);setNotice(null);
    try {const r=await run();setNotice(r.message_zh);app.trackTasks([r.task]);app.openTasks(r.task.task_id);app.bumpRefresh();}
    catch(e){setNotice(errorText(e));app.bumpRefresh();}finally{setBusy(false);}
  }
  /** 只读取已保存的分页候选证据。 */
  async function readPreview(database:string,page=1) {
    if(!mapping?.latest)return;
    setBusy(true);try{setPreview(await api.sourcePreview(studyId,mapping.latest.preview_id,database,page));}
    catch(e){setNotice(errorText(e));}finally{setBusy(false);}
  }
  return <div className="stack" style={{gap:14,marginBottom:16}}>
    {moduleId==='A01' && acquisition && <>
      <p>先获取各库原始资料，再整理三库结果。失败库可用下方上传入口补齐；缺库不能完成三库验收。</p>
      <Space wrap>
        <Button type="primary" disabled={!acquisition.enabled || busy || !acquisition.databases.length} onClick={()=>action(()=>api.acquireSources(studyId,{...versions,databases:acquisition.databases,reason:'获取本研究尚缺三库官方原始资料'}))}>获取缺少的数据库资料</Button>
        <Button loading={busy} onClick={async()=>{setBusy(true);try{setEnvironment(await api.environment());}catch(e){setNotice(errorText(e));}finally{setBusy(false);}}}>检查本机版本与资料</Button>
      </Space>
      {acquisition.latest?.databases.map(r=><Alert key={r.database} type={r.status==='success'?'success':'warning'} showIcon message={r.database+'：'+(r.message_zh || r.status_zh)} />)}
    </>}
    {moduleId==='A02' && mapping && <>
      <p>TTD 合并疾病、PharmGKB 同义名与交叉编号可单独核查。这里只生成候选，不更改当前疾病集合。</p>
      <Space wrap>{['TTD','PharmGKB'].map(database=><Button key={database} disabled={!mapping.enabled || busy} onClick={()=>action(()=>api.mappingPreview(studyId,{...versions,databases:[database],reason:'核对本研究'+database+'疾病身份候选，当前A02保持'}))}>核查 {database} 疾病定位</Button>)}</Space>
      <Button disabled={!mapping.enabled || busy} onClick={()=>action(()=>api.mappingPreview(studyId,{...versions,databases:['TTD','PharmGKB'],reason:'同时核对TTD和PharmGKB疾病候选，当前A02保持'}))}>同时核查两库疾病定位</Button>
      {mapping.latest?.databases.map(r=><div key={r.database}><Alert type={r.status==='query_failed'?'warning':'info'} showIcon message={r.database+'：'+r.status_zh} description={r.error_zh} /><Button style={{marginTop:8}} onClick={()=>readPreview(r.database)} disabled={busy}>查看 {r.database} 候选及依据（{r.candidates_count || 0}组）</Button></div>)}
    </>}
    {verification && <>
      <Table size="small" rowKey={r=>r.database+':'+r.herb} dataSource={verification.coverage} pagination={false} scroll={{x:600}} columns={[{title:'数据库',dataIndex:'database'},{title:'药味',dataIndex:'herb'},{title:'原始清单记录',dataIndex:'records'},{title:'完整性',dataIndex:'availability'},{title:'依据',dataIndex:'basis'}]} />
      {(verification.coverage.some(r=>!r.complete) || verification.issues_count>0) && <Form layout="vertical" disabled={!verification.enabled || busy} onFinish={v=>action(()=>api.resolveSources(studyId,{...versions,...v,confirm_coverage:v.confirm_coverage===true,omit_unresolved:v.omit_unresolved===true}))}>
        <Alert type="warning" showIcon message={'完整性待核查或身份未决：'+verification.issues_count+'组身份问题。先查看下方明细，再明确处理。'} style={{marginBottom:12}} />
        {verification.coverage.some(r=>!r.complete) && <Form.Item name="confirm_coverage" valuePropName="checked"><Checkbox>我已核对所上传原件，各数据库均完整覆盖本研究药味</Checkbox></Form.Item>}
        {verification.issues_count>0 && <Form.Item name="omit_unresolved" valuePropName="checked"><Checkbox>本次暂不采用全部未查实身份的关系，保留原始记录和依据</Checkbox></Form.Item>}
        <Form.Item label="核验人" name="reviewer" rules={[{required:true,whitespace:true}]}><Input /></Form.Item>
        <Form.Item label="核验依据及处理说明" name="note" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={2} maxLength={2000}/></Form.Item>
        <Form.Item name="confirmed" valuePropName="checked" rules={[{validator:(_,v)=>v?Promise.resolve():Promise.reject(new Error('请明确确认处理决定'))}]}><Checkbox>确认仅处理本批上述项目；生成后另行整体复核</Checkbox></Form.Item>
        <Button type="primary" htmlType="submit">保存处理并生成待复核结果</Button>
      </Form>}
    </>}
    {notice && <Alert showIcon type="info" message={notice}/>}
    <Modal title="疾病映射候选与依据" open={!!preview} onCancel={()=>setPreview(null)} footer={null} width={1000}>
      {preview && <><Alert type="info" showIcon message={preview.note_zh} description={preview.error_zh} /><Table style={{marginTop:16}} size="small" rowKey="candidate_id" loading={busy} dataSource={preview.items} scroll={{x:700}} pagination={{current:preview.page,pageSize:preview.size,total:preview.total,showSizeChanger:false,onChange:p=>readPreview(preview.database,p)}} columns={[{title:'原始疾病条目',dataIndex:'disease_name'},{title:'疾病编号',dataIndex:'disease_id'},{title:'原始关系数',dataIndex:'records_count',render:v=>v===null?'尚未查询':v},{title:'待核验依据',dataIndex:'reason_zh'},{title:'来源',dataIndex:'source_url',render:u=><a href={u} target="_blank" rel="noreferrer">官方来源</a>}]} /></>}
    </Modal>
    <Modal title="本机版本与资料预检" open={!!environment} onCancel={()=>setEnvironment(null)} footer={null}>
      {environment && <><p>分支：{environment.code.branch || '未核实'}<br/>提交：{environment.code.commit || '未核实'}<br/>{environment.code.dirty?'工作区有未提交修改':''}</p>{environment.references.map(r=><p key={r.label_zh}><strong>{r.label_zh}</strong>：{r.detail_zh}</p>)}<Alert type="info" message={environment.note_zh}/></>}
    </Modal>
  </div>;
}
