// A02前置范围核验：完整清单由后端提供，决定由用户明确选择，不自动判断本病。
import { Alert, Button, Checkbox, Input, Select, Space, Table, Typography } from 'antd';
import { useState } from 'react';
import { api, errorText } from '../api/client';
import type { DiseaseScopeInfo } from '../api/types';
import { useApp } from '../lib/appContext';

/** 默认展开核验表；翻页不丢决定，提交完整清单并绑定当前版本。 */
export default function DiseaseScopeReview({ studyId, info }: { studyId: string; info: DiseaseScopeInfo }) {
  const app = useApp();
  const [decisions, setDecisions] = useState<Record<string, string>>(() => Object.fromEntries(info.items.map(r => [r.scope_id, r.scope])));
  const [bulk, setBulk] = useState<string>();
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const options = info.choices.map(c => ({ value: c.value, label: c.label_zh }));
  const disabled = !info.enabled || busy;

  async function submit() {
    setBusy(true); setNotice(null);
    try {
      const r = await api.reviewDiseaseScope(studyId, { expected_a00: info.expected_a00, expected_run: info.expected_run, expected_staging: info.expected_staging,
        decisions: info.items.map(row => ({ scope_id: row.scope_id, scope: decisions[row.scope_id] })), reviewer, note, confirmed });
      setNotice(r.message_zh); app.trackTasks([r.task]); app.openTasks(r.task.task_id); app.bumpRefresh();
    } catch (e) { setNotice(errorText(e)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }

  return <section className="card" id="disease-scope-review" style={{ border: '2px solid #D28A19', padding: 20 }}>
    <h2 style={{ marginTop: 0 }}>疾病范围核验 · 请在此处理</h2>
    <p>核对各组来源和疾病名称，再选择范围。只纳入本病直接条目；亚型、范围外条目不纳入，待核验不自动放行。</p>
    {!info.enabled && <Alert showIcon type="info" message={info.disabled_reason_zh} />}
    <Space wrap style={{ marginBottom: 12 }}>
      <Button disabled={disabled || selectedIds.length === info.items.length} onClick={() => setSelectedIds(info.items.map(row => row.scope_id))}>全选条目（含其他页）</Button>
      <Button disabled={disabled || !selectedIds.length} onClick={() => setSelectedIds([])}>取消选择</Button>
      <span role="status">已选 {selectedIds.length} 项</span>
      <Select aria-label="统一范围选择" placeholder="选择统一处理方式" value={bulk} options={options} onChange={setBulk} disabled={disabled} style={{ minWidth: 200 }} />
      <Button disabled={disabled || !bulk || !selectedIds.length} onClick={() => {
        setDecisions(old => Object.fromEntries(info.items.map(row => [row.scope_id, !selectedIds.includes(row.scope_id) || (bulk === 'direct' && !row.direct_allowed) ? old[row.scope_id] : bulk!])));
        setConfirmed(false);
      }}>应用到已选条目</Button>
      <span className="small muted">全选涵盖完整清单，不受搜索或分页影响；选择本身不改变范围，来源身份不符的条目不会设为本病。</span>
    </Space>
    <Input aria-label="查找范围条目" allowClear placeholder="按来源、疾病名称或编号查找；筛选保留勾选，保存时保留完整清单的决定" value={query} onChange={e => setQuery(e.target.value)} style={{ marginBottom: 12 }} />
    <Table rowKey="scope_id" size="small" rowSelection={{ selectedRowKeys: selectedIds, preserveSelectedRowKeys: true, onChange: keys => setSelectedIds(keys.map(String)), getCheckboxProps: () => ({ disabled }), columnTitle: '选择', columnWidth: 50 }} dataSource={info.items.filter(row => [row.database, row.disease_term, row.disease_id].some(value => value.toLowerCase().includes(query.trim().toLowerCase())))} scroll={{ x: 770 }} pagination={{ defaultPageSize: 10, showSizeChanger: true }} columns={[
      { title: '来源与原文件', key: 'source', width: 125, render: (_, row) => <><strong>{row.database}</strong><br /><a href={row.source_url}>查看原文件</a><Typography.Text type="secondary" ellipsis={{ tooltip: row.source_name }} style={{ fontSize: 12, maxWidth: 109, display: 'block' }}>{row.source_name}</Typography.Text></> },
      { title: '原始疾病条目及身份提示', key: 'disease', render: (_, row) => <><div>{row.disease_term || '原文件未提供疾病名称'}</div><div className="small muted">{row.disease_id}</div>{row.identity_warning && <Alert type={row.direct_allowed ? 'info' : 'error'} showIcon message={row.identity_warning} style={{ marginTop: 6 }} />}</> },
      { title: '候选记录数', dataIndex: 'records', width: 95 },
      { title: '我的范围决定', key: 'scope', width: 170, render: (_, row) => <Select aria-label={row.database + ' ' + (row.disease_id || row.scope_id) + ' 范围决定'} value={decisions[row.scope_id]} disabled={disabled} options={options.map(c => ({ ...c, disabled: c.value === 'direct' && !row.direct_allowed }))} style={{ width: '100%' }} onChange={value => { setDecisions(old => ({ ...old, [row.scope_id]: value })); setConfirmed(false); }} /> },
    ]} />
    <label>本批核验人<Input aria-label="范围核验人" value={reviewer} maxLength={200} onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} disabled={disabled} /></label>
    <label>范围核验依据<Input.TextArea aria-label="范围核验依据" value={note} rows={3} maxLength={4000} placeholder="说明本批判断依据，特殊条目请注明名称或编号。" onChange={e => { setNote(e.target.value); setConfirmed(false); }} disabled={disabled} /></label>
    <p><Checkbox checked={confirmed} disabled={disabled} onChange={e => setConfirmed(e.target.checked)}>我已核对完整清单及例外，确认保存这些范围决定</Checkbox></p>
    <Button type="primary" loading={busy} disabled={disabled || !confirmed || !reviewer.trim() || !note.trim()} onClick={submit}>保存本批范围核验</Button>
    {notice && <Alert showIcon message={notice} style={{ marginTop: 10 }} />}
    <p className="small muted">保存成功后，请到下方“基因身份核查与标准化”生成标准化结果，再进行A02整体复核。</p>
  </section>;
}
