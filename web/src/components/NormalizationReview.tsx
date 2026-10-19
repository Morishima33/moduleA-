// 范围保存后的标准化衔接：后台预览、用户确认例外、生成待复核结果，不代签科研批准。
import { Alert, Button, Checkbox, Collapse, Input, Table } from 'antd';
import { useState } from 'react';
import type { NormalizationInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

/** 数量与身份明细直接使用后台预览；确认框初始均不勾选。 */
export default function NormalizationReview({ studyId, info, scopeDirty = false }: { studyId: string; info: NormalizationInfo; scopeDirty?: boolean }) {
  const app = useApp();
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [omit, setOmit] = useState(false);
  const [sourceException, setSourceException] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string>();
  const preview = info.preview;
  const disabled = busy || !info.enabled || scopeDirty;
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
    <h2>{preview ? '第3步：身份预览已完成' : '第3步：程序核查基因身份'}</h2>
    <p>操作顺序：保存范围 → 核查身份并确认处理 → 生成待复核结果 → 整体复核。本步骤只读取已保存的范围决定。</p>
    <Alert type="warning" showIcon message={info.scope_note_zh} style={{ marginBottom: 12 }} />
    {!info.enabled && <Alert type="warning" showIcon message={info.disabled_reason_zh} style={{ marginBottom: 12 }} />}
    {scopeDirty && <Alert type="warning" showIcon message="请先保存第2步的范围修改，再重新核查身份。本次预览仍对应修改前的已保存范围。" style={{marginBottom: 12}} />}
    {!preview && <Button type="primary" disabled={disabled} loading={busy} onClick={() => submit('preview')}>核查基因身份</Button>}
    {preview && <>
      <section id="normalization-confirmation" style={{ border: '2px solid #0F5E6E', borderRadius: 10, padding: 16, marginBottom: 16, scrollMarginTop: 90 }}>
      <h3 style={{ marginTop: 0 }}>第4步：确认身份处理并生成结果</h3>
      <Alert type="info" showIcon message="目前只有预览，整体复核尚未开放" description="完成下面的身份处理确认并生成待复核结果后，右侧“通过”才可使用。“重新核查”只更新预览。" style={{ marginBottom: 12 }} />
      {hasIssues && <p>请查看下方已展开的身份例外。程序尚不能唯一确定这些条目的标准身份，须明确本次是否暂不采用。</p>}
      {preview.modules.filter(m => m.identity_issues.length > 0).map(m => <div key={m.module}>
        <strong>{m.module} · 需要处理的身份例外</strong>
        <Table size="small" rowKey="issue_id" dataSource={m.identity_issues} scroll={{ x: 650 }} pagination={{ defaultPageSize: 10 }} columns={[
          { title: '原名称', dataIndex: 'raw_symbol' }, { title: '原蛋白编号', dataIndex: 'raw_uniprot' },
          { title: '原始关系数', dataIndex: 'records' },
          { title: '核查状态', render: (_, row) => ({unmapped:'仍未查实', ambiguous_or_conflicting:'歧义或冲突', identity_verified_no_hgnc:'身份已查实，未接入HGNC', non_gene_object:'生物区域，非单个基因'}[String(row.status)] || String(row.status)) },
          { title: '核查依据', dataIndex: 'query_note' },
        ]} />
      </div>)}
      {hasSourceException && <Alert type="warning" message="本预览包含流程测试缺库例外" description="GeneCards未提供；其他来源不是等价替代。须核对下方例外确认，本次不能作为完整五库正式研究。" />}
      <label>本次核验人<Input aria-label="标准化核验人" value={reviewer} disabled={disabled} onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} maxLength={200} /></label>
      <label>处理依据<Input.TextArea aria-label="标准化处理依据" value={note} disabled={disabled} onChange={e => { setNote(e.target.value); setConfirmed(false); }} rows={3} maxLength={4000} /></label>
      {hasIssues && <p><Checkbox disabled={disabled} checked={omit} onChange={e => { setOmit(e.target.checked); setConfirmed(false); }}>我已核查身份例外，接受本次暂不采用未进入HGNC主集合的条目，保留原件及核查依据</Checkbox></p>}
      {hasSourceException && <p><Checkbox disabled={disabled} checked={sourceException} onChange={e => { setSourceException(e.target.checked); setConfirmed(false); }}>我接受本次流程测试暂不采用GeneCards；其他来源不是等价替代，不作为完整五库正式研究</Checkbox></p>}
      <p><Checkbox disabled={disabled} checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我确认已保存的采用、排除范围及上述身份处理</Checkbox></p>
      <Button type="primary" disabled={disabled || !confirmed || !reviewer.trim() || !note.trim() || (hasIssues && !omit) || (hasSourceException && !sourceException)} onClick={() => submit('publish')}>确认处理并生成待复核结果</Button>
      <p className="small muted">请填写核验人与依据，勾选需要的例外处理及范围确认后提交。</p>
      </section>
      <h3>身份核查预览（尚未生成待复核结果）</h3>
      <Table size="small" rowKey="module" pagination={false} dataSource={preview.modules} columns={[
        { title: '模块', dataIndex: 'module' },
        { title: '预览可匹配基因数', render: (_, row) => String(row.summary['标准化基因数']) },
        { title: '待处理身份问题组', render: (_, row) => String(row.summary['身份问题组数']) },
      ]} />
      <Collapse style={{ marginTop: 12 }} items={[{ key: 'refresh-preview', label: '需要重新核查时展开', children: <Button disabled={disabled} loading={busy} onClick={() => submit('preview')}>重新核查基因身份（仅更新预览）</Button> }]} />
    </>}
    {notice && <Alert showIcon message={notice} style={{ marginTop: 12 }} />}
    <p className="small muted">生成后进入第5步：A01/A02整体复核；两项通过后接续第6步A03交集。</p>
  </section>;
}
