// 文件用途：A01/A02按库上传入口；格式、状态与版本全部由后端提供。
import { Alert, Button, Checkbox, Collapse, Form, Input, Select } from 'antd';
import { useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { SourceUploadInfo, SourceUploadItem, Task } from '../api/types';
import { useApp } from '../lib/appContext';
import { SectionHead } from './common';

const OFFICIAL: Record<string, string> = { TCMSP: 'https://tcmsp-e.com/', HERB: 'https://herb.ac.cn/', BATMAN: 'https://bionet.ncpsb.org.cn/batman-tcm/', GeneCards: 'https://www.genecards.org/', OMIM: 'https://www.omim.org/', TTD: 'https://ttd.idrblab.cn/', PharmGKB: 'https://api.clinpgx.org/v1', OTP: 'https://platform.opentargets.org/', DisGeNET: 'https://www.disgenet.org/' };

/** 单库表单，文件不自动上传，只有用户提交才创建后台任务。 */
function UploadForm({ studyId, moduleId, info, source }: { studyId: string; moduleId: string; info: SourceUploadInfo; source: SourceUploadItem }) {
  const app = useApp();
  const [form] = Form.useForm();
  const [fmt, setFmt] = useState(source.formats[0]?.value || '');
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const option = source.formats.find(f => f.value === fmt);
  async function submit(values: Record<string, string | boolean>) {
    if (!file) { setNotice({ text: '请先选择资料文件', error: true }); return; }
    if (file.size > 16 * 1024 * 1024) { setNotice({ text: '资料文件不能超过16MiB，请按库包装', error: true }); return; }
    setBusy(true); setNotice(null);
    try {
      const body = new FormData();
      for (const key of ['query', 'retrieved_at', 'version', 'source_url', 'reason', 'encoding', 'query_quoted', 'export_completeness']) body.append(key, String(values[key] || ''));
      body.append('database', source.database); body.append('format', fmt); body.append('confirmed', values.confirmed ? 'yes' : 'no');
      for (const key of ['expected_a00', 'expected_run', 'expected_staging'] as const) body.append(key, info[key]);
      body.append('upload', file);
      const response = await api.uploadSource(studyId, moduleId, body);
      setNotice({ text: response.message_zh, error: response.task.state === 'failed' });
      app.trackTasks([response.task]); app.openTasks(response.task.task_id); app.bumpRefresh();
      if (response.task.state !== 'failed') { setFile(null); if (input.current) input.current.value = ''; }
    } catch (error) { setNotice({ text: errorText(error), error: true }); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <div className="stack" style={{ gap: 12 }}>
    <p className="small muted">{source.hint_zh}</p>
    {source.uploaded_name && <p className="small" style={{ overflowWrap: 'anywhere' }}>已归档：{source.uploaded_name} {source.download_url && <a href={source.download_url}>下载原始资料</a>}<br />文件指纹：{source.sha256}</p>}
    {notice && <Alert type={notice.error ? 'error' : 'info'} showIcon message={notice.text} />}
    <Form name={moduleId + "_" + source.database + "_upload"} form={form} layout="vertical" disabled={!info.enabled || busy} initialValues={{ query: info.query_zh, version: '未知', source_url: OFFICIAL[source.database] || '', encoding: 'utf-8-sig', query_quoted: 'unknown', export_completeness: 'unknown', reason: '补充本研究' + source.label_zh + '资料' }} onFinish={submit}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0 18px' }}>
        <Form.Item label="资料格式"><Select aria-label={source.database + '资料格式'} value={fmt} options={source.formats.map(f => ({ value: f.value, label: f.label_zh }))} onChange={v => { setFmt(v); setFile(null); if (input.current) input.current.value = ''; }} /></Form.Item>
        <Form.Item label="文件编码" name="encoding"><Select options={[{ value: 'utf-8-sig', label: 'UTF-8' }, { value: 'gbk', label: 'GBK' }]} /></Form.Item>
        <Form.Item label="实际检索词或处方药味" name="query" rules={[{ required: true, whitespace: true, message: '请填写实际检索词或药味' }]}><Input /></Form.Item>
        <Form.Item label="资料获取日期" name="retrieved_at" rules={[{ required: true, message: '请填写实际获取日期' }]}><Input type="date" /></Form.Item>
        <Form.Item label="数据库版本（未知填未知）" name="version" rules={[{ required: true, whitespace: true, message: '请填写版本或未知' }]}><Input /></Form.Item>
        <Form.Item label="来源网址或出处" name="source_url" rules={[{ required: true, whitespace: true, message: '请填写来源' }]}><Input /></Form.Item>
      </div>
      {source.database === 'GeneCards' && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0 18px' }}>
        <Form.Item label="检索时是否加引号" name="query_quoted"><Select options={[{ value: 'unknown', label: '不确定' }, { value: 'yes', label: '加引号' }, { value: 'no', label: '未加引号' }]} /></Form.Item>
        <Form.Item label="本次搜索结果导出完整性" name="export_completeness"><Select options={[{ value: 'unknown', label: '不确定' }, { value: 'complete', label: '已核对为全部搜索结果' }, { value: 'partial', label: '仅部分搜索结果' }]} /></Form.Item>
      </div>}
      <p>{option && <a href={option.template_url}>下载字段模板或包装说明</a>} · 模板须替换为真实资料。</p>
      <Form.Item label={source.label_zh + '资料文件'}><input ref={input} type="file" aria-label={source.database + '资料文件'} accept={option?.accept} disabled={!info.enabled || busy} onChange={e => setFile(e.target.files?.[0] || null)} /></Form.Item>
      <Form.Item label="上传或替换原因" name="reason" rules={[{ required: true, whitespace: true, message: '请填写原因' }]}><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
      <Form.Item name="confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('请确认资料用于当前研究')) }]}><Checkbox>确认这份资料用于当前研究候选核查</Checkbox></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} disabled={!info.enabled}>上传并校验 {source.label_zh}</Button>
    </Form>
  </div>;
}

/** 来源列表同层显示；三库整理为单独的用户操作，不在上传后自动执行。 */
export default function SourceUploads({ studyId, moduleId, info }: { studyId: string; moduleId: string; info: SourceUploadInfo }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('整理本研究已上传的完整三库资料');
  const [notice, setNotice] = useState<string | null>(null);
  function track(task: Task) { app.trackTasks([task]); app.openTasks(task.task_id); app.bumpRefresh(); }
  async function process() {
    setBusy(true); setNotice(null);
    try { const response = await api.processSources(studyId, { expected_a00: info.expected_a00, expected_run: info.expected_run, expected_staging: info.expected_staging, reason }); setNotice(response.message_zh); track(response.task); }
    catch (error) { setNotice(errorText(error)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <section className="card">
    <SectionHead title="数据库资料上传与更新" />
    <p className="small muted">{info.note_zh}</p>
    {!info.enabled && <Alert type="info" showIcon message={info.disabled_reason_zh} style={{ marginBottom: 12 }} />}
    <Collapse items={info.sources.map(source => ({ key: source.database, label: <span><strong>{source.label_zh}</strong> · {source.status_zh}</span>, children: <UploadForm studyId={studyId} moduleId={moduleId} info={info} source={source} /> }))} />
    {moduleId === 'A01' && <div style={{ marginTop: 16 }}>
      <p className="small muted">{info.process_reason_zh || '完整三库资料和共同身份依据齐备，可整理为新版本。'}</p>
      <Input aria-label="三库整理原因" value={reason} onChange={e => setReason(e.target.value)} disabled={!info.can_process || busy} style={{ marginBottom: 8 }} />
      <Button type="primary" onClick={process} disabled={!info.can_process || !reason.trim()} loading={busy}>整理已上传三库资料</Button>
      {notice && <Alert showIcon type="info" message={notice} style={{ marginTop: 12 }} />}
    </div>}
  </section>;
}
