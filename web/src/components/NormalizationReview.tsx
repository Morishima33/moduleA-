// 范围保存后的标准化衔接：后台预览、用户确认例外、生成待复核结果，不代签科研批准。
import { Alert, Button, Checkbox, Collapse, Input, Table } from 'antd';
import { useState } from 'react';
import type { NormalizationInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 数量与身份明细直接使用后台预览；确认框初始均不勾选。 */
export default function NormalizationReview({ studyId, info }: { studyId: string; info: NormalizationInfo }) {
  const app = useApp();
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [omit, setOmit] = useState(false);
  const [sourceException, setSourceException] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string>();
  const preview = info.preview;
  const disabled = busy || !info.enabled;
  // 是否需要例外确认来自后台各侧的身份问题清单，不在页面推断身份。
  const hasIssues = !!preview?.modules.some(m => m.identity_issues.length > 0);
  const hasSourceException = !!preview?.source_exceptions.length;
  async function submit(action: 'preview' | 'publish') {
    setBusy(true); setNotice(undefined);
    try {
      const result = await api.normalization(studyId, { expected_a00: info.expected_a00, expected_a01: info.expected_a01, expected_a02: info.expected_a02, action,
        ...(action === 'publish' ? { stamp: preview!.stamp, reviewer, note, confirmed, accept_omit: omit, accept_source_exception: sourceException } : {}) });
      app.trackTasks([result.task]); app.openTasks(result.task.task_id); app.bumpRefresh();
      setNotice(result.message_zh);
    } catch (error) { setNotice(errorText(error)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <section className="card" id="normalization-review">
    <h2>下一步：基因身份核查与标准化</h2>
    <p>范围保存后还需生成标准化结果，整体复核的“通过”才可开放。本步骤只读取已保存的范围决定；上方未保存的修改不会用于本次预览。</p>
    <Alert type="info" showIcon message={info.scope_note_zh} style={{ marginBottom: 12 }} />
    {!info.enabled && <Alert type="warning" showIcon message={info.disabled_reason_zh} style={{ marginBottom: 12 }} />}
    <Button disabled={disabled} loading={busy} onClick={() => submit('preview')}>{preview ? '重新核查基因身份' : '核查基因身份'}</Button>
    {preview && <>
      <Table size="small" rowKey="module" pagination={false} dataSource={preview.modules} style={{ marginTop: 12 }} columns={[
        { title: '模块', dataIndex: 'module' },
        { title: '标准化基因数', render: (_, row) => String(row.summary['标准化基因数']) },
        { title: '身份问题组', render: (_, row) => String(row.summary['身份问题组数']) },
      ]} />
      <Collapse style={{ margin: '12px 0' }} items={preview.modules.map(m => ({ key: m.module, label: `${m.module} 身份例外明细`, children: <Table size="small" rowKey="issue_id" dataSource={m.identity_issues} scroll={{ x: 650 }} pagination={{ defaultPageSize: 10 }} columns={[
        { title: '原名称', dataIndex: 'raw_symbol' }, { title: '原始编号', dataIndex: 'raw_id' },
        { title: '核查状态', render: (_, row) => ({unmapped:'仍未查实', ambiguous_or_conflicting:'歧义或冲突', identity_verified_no_hgnc:'身份已查实，未接入HGNC', non_gene_object:'生物区域，非单个基因'}[String(row.status)] || String(row.status)) },
        { title: '核查依据', dataIndex: 'query_note' },
      ]} /> }))} />
      {hasSourceException && <Alert type="warning" message="本预览包含流程测试缺库例外" description="GeneCards未提供；其他来源不是等价替代。须核对下方例外确认，本次不能作为完整五库正式研究。" />}
      <label>本次核验人<Input aria-label="标准化核验人" value={reviewer} disabled={disabled} onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} maxLength={200} /></label>
      <label>处理依据<Input.TextArea aria-label="标准化处理依据" value={note} disabled={disabled} onChange={e => { setNote(e.target.value); setConfirmed(false); }} rows={3} maxLength={4000} /></label>
      {hasIssues && <p><Checkbox disabled={disabled} checked={omit} onChange={e => { setOmit(e.target.checked); setConfirmed(false); }}>我已核查身份例外，接受本次暂不采用未进入HGNC主集合的条目，保留原件及核查依据</Checkbox></p>}
      {hasSourceException && <p><Checkbox disabled={disabled} checked={sourceException} onChange={e => { setSourceException(e.target.checked); setConfirmed(false); }}>我接受本次流程测试暂不采用GeneCards；其他来源不是等价替代，不作为完整五库正式研究</Checkbox></p>}
      <p><Checkbox disabled={disabled} checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我确认已保存的采用、排除范围及上述身份处理</Checkbox></p>
      <Button type="primary" disabled={disabled || !confirmed || !reviewer.trim() || !note.trim() || (hasIssues && !omit) || (hasSourceException && !sourceException)} onClick={() => submit('publish')}>生成标准化结果，进入整体复核</Button>
    </>}
    {notice && <Alert showIcon message={notice} style={{ marginTop: 12 }} />}
    <p className="small muted">生成后停在A01/A02整体复核；不自动批准、不启动A03或分子对接。</p>
  </section>;
}
