// 顶部身份清单提供真实方案确认和后台应用入口；不代签结果，不用确认按钮掩盖身份冲突。
import { Alert, Button, Checkbox, Descriptions, Drawer, Form, Input, Modal, Table, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import type { IdentityPlanInfo, ModuleView, PpiIdentity, PpiIdentityRow } from '../api/types';
import { api, errorText, fileUrl } from '../api/client';
import { useApp } from '../lib/appContext';
import { fmtTime } from '../lib/format';

// 保存和应用的反馈来自后端决定和结果；刷新后仍能看到核验人及执行结果。
export function IdentityPlanStatus({ info }: { info?: IdentityPlanInfo | null }) {
  const plan = info?.latest;
  if (!plan) return null;
  return <Alert style={{ margin: '12px 0' }} showIcon type={plan.applied_run_id ? 'info' : 'warning'} message={plan.status_zh}
    description={<><div>核验人：{plan.reviewer} · {fmtTime(plan.created_at)}</div><div>核验说明：{plan.note_zh}</div><div>补查 {plan.check_ids.length} 项；成功空响应时允许暂不采用 {plan.omit_ids.length} 项。{plan.pending_count !== null && `应用后仍有 ${plan.pending_count} 项待核验。`}</div>{plan.error_zh && <div>补查结果：{plan.error_zh}</div>}{plan.evidence_url && <Button size="small" href={plan.evidence_url}>下载本次补查原始证据</Button>}</>}  />;
}

// 每次提交绑定当前研究与A03/A04，并要求人工填写姓名、说明和确认勾选。
export default function IdentityReview({ studyId, view, data }: { studyId: string; view: ModuleView; data: PpiIdentity }) {
  const app = useApp();
  const [selected, setSelected] = useState<PpiIdentityRow | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [ids, setIds] = useState<string[]>([]);
  const [omitted, setOmitted] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<{ reviewer: string; note: string; confirmed: boolean }>();
  const info = view.identity_plan;
  const source = view.files.find(f => f.role === 'string_source');
  const list = view.files.find(f => f.name === 'identity_issues.csv');
  useEffect(() => { setSelected(null); setPlanOpen(false); form.resetFields(); }, [studyId, view.run?.run_id, form]);
  function openPlan(selectedIds: string[]) {
    setSelected(null); setIds(selectedIds); setOmitted([]); form.resetFields(); setPlanOpen(true);
  }
  async function submit() {
    if (!info || !ids.length) { message.warning('请至少选择一个补查项'); return; }
    let values;
    try { values = await form.validateFields(); } catch { return; }
    setBusy(true);
    try {
      const result = await api.identityPlan(studyId, { expected_a03: info.expected_a03, expected_a04: info.expected_a04, expected_decision_id: info.expected_decision_id, reviewer: values.reviewer.trim(), note: values.note.trim(), check_ids: ids, omit_ids: omitted.filter(id => ids.includes(id)), confirmed: true });
      setPlanOpen(false); app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
      if (result.task.state === 'failed') message.error(result.task.error_zh || '任务启动失败，方案尚未应用');
      else message.success(result.message_zh);
    } catch (error) { message.error(errorText(error)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <div className="identity-review">
    <div className="identity-review-heading">
      <strong>身份核验清单</strong><Tag color="orange">{data.total}项待核验</Tag>
      {!view.historical && <Button type="primary" disabled={!info?.enabled} onClick={() => openPlan(data.rows.map(r => r.target_id))}>确认补查方案并应用</Button>}
      {list && <Button size="small" href={fileUrl(studyId, list.key)}>下载本轮清单</Button>}
    </div>
    {!view.historical && <p className="small">操作：证据可按需查看，无须逐条点开。点击“确认补查方案并应用”，可一次提交多项补查；填写核验人和说明后，后台自动执行并生成新A04，仍须独立复核。仅等待不会启动补查。</p>}
    {!view.historical && !info?.enabled && info?.disabled_reason_zh && <Alert type="info" message={info.disabled_reason_zh} style={{ marginBottom: 12 }} />}
    <IdentityPlanStatus info={info} />
    <Table<PpiIdentityRow> size="small" rowKey="target_id" pagination={false} dataSource={data.rows}
      scroll={{ x: 780, y: 330 }} columns={[
        { title: '输入基因', dataIndex: 'symbol', width: 125, render: (value: string, row) => <Button type="link" style={{ padding: 0 }} onClick={() => setSelected(row)} aria-label={`核查${row.symbol}的身份`}>{value}</Button> },
        { title: 'HGNC编号', dataIndex: 'target_id', width: 130 },
        { title: 'STRING返回名称', dataIndex: 'returned', width: 150, render: (value: string) => value || <span className="muted">未返回名称</span> },
        { title: '待核验原因', dataIndex: 'reason_zh', width: 180 },
        { title: '核验入口', key: 'check', fixed: 'right', width: 100, render: (_, row) => <Button size="small" onClick={() => setSelected(row)} aria-label={`查看${row.symbol}的核查证据`}>查看证据</Button> },
      ]} />
    <p className="small muted" style={{ margin: '8px 0 0' }}>{data.note_zh}</p>
    <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? `身份核查：${selected.symbol}` : '身份核查'} width="min(620px, 96vw)" destroyOnClose>
      {selected && <>
        <Alert type="warning" showIcon message="身份待核验" description="查看证据后可确认本项的补查方案；名称或编号冲突不会因点击确认而通过。" />
        <Descriptions column={1} size="small" bordered style={{ marginTop: 18 }} items={[
          { key: 'symbol', label: '输入基因', children: selected.symbol },
          { key: 'target', label: 'HGNC编号', children: selected.target_id },
          { key: 'returned', label: 'STRING返回名称', children: selected.returned || '未返回名称' },
          { key: 'reason', label: '待核验原因', children: selected.reason_zh },
          { key: 'run', label: '本次A04版本', children: view.run?.run_id },
          { key: 'parent', label: '绑定的A03版本', children: view.run?.parent_runs.A03 },
        ]} />
        <div className="identity-review-downloads">
          {source && <Button href={fileUrl(studyId, source.key)}>下载本轮STRING原始资料</Button>}
          {list && <Button href={fileUrl(studyId, list.key)}>下载本轮身份问题清单</Button>}
        </div>
        <p>核验重点：输入基因、HGNC编号与STRING返回是否指向同一基因；缺少返回或名称不一致的项目需补齐稳定编号核对证据。</p>
        {!view.historical && <Button type="primary" disabled={!info?.enabled} onClick={() => openPlan([selected.target_id])}>确认本项补查方案并应用</Button>}
      </>}
    </Drawer>
    <Modal open={planOpen} title="确认身份补查方案" onCancel={() => !busy && setPlanOpen(false)} footer={null} width={760} destroyOnClose maskClosable={!busy}>
      <Alert type="info" showIcon message="按官方稳定编号核验，证据一致才采用" description="使用HGNC官方快照中的全部UniProt／Ensembl编号向STRING补查。缺编号、查询失败或编号冲突不会被当作无命中，也不会自动通过A04。" />
      <p>选择本次补查范围。同一A03中已应用的补查范围继续保留，本次追加所选项目。右侧选项需你明确同意：只有全部稳定编号补查均成功且无命中，才仅对本次PPI暂不采用；A03交集与富集输入保留。</p>
      {/* 批量授权仅作用于左侧已选补查项；打开窗口时保持未勾选，不提交任何请求。 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span>成功无命中时仅本次PPI暂不采用：</span>
        <Button size="small" disabled={busy || !ids.length} onClick={() => setOmitted([...ids])}>全部勾选</Button>
        <Button size="small" disabled={busy || !omitted.length} onClick={() => setOmitted([])}>全部取消</Button>
        <span className="small muted">仅作用于左侧已选补查项</span>
      </div>
      <Table<PpiIdentityRow> size="small" rowKey="target_id" pagination={false} dataSource={data.rows} scroll={{ x: 620, y: 245 }}
        rowSelection={{ selectedRowKeys: ids, onChange: keys => { const next = keys.map(String); setIds(next); setOmitted(old => old.filter(id => next.includes(id))); } }} columns={[
          { title: '输入基因', dataIndex: 'symbol', width: 120 },
          { title: 'HGNC编号', dataIndex: 'target_id', width: 130 },
          { title: '成功无命中时仅本次PPI暂不采用', width: 290, render: (_, row) => <Checkbox aria-label={`允许${row.symbol}成功无命中时暂不采用`} disabled={!ids.includes(row.target_id)} checked={omitted.includes(row.target_id)} onChange={e => setOmitted(old => e.target.checked ? [...old, row.target_id] : old.filter(id => id !== row.target_id))}>同意此项有限处理</Checkbox> },
        ]} />
      <Form form={form} layout="vertical" onFinish={submit} style={{ marginTop: 16 }}>
        <Form.Item label="核验人" name="reviewer" rules={[{ required: true, whitespace: true, message: '请填写实际核验人' }]}><Input maxLength={2000} placeholder="填写你的姓名" /></Form.Item>
        <Form.Item label="核验说明" name="note" rules={[{ required: true, whitespace: true, message: '请填写核验依据和确认范围' }]}><Input.TextArea rows={2} maxLength={2000} placeholder="说明本次同意补查哪些项目及处理范围" /></Form.Item>
        <Form.Item name="confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('请勾选确认本次方案')) }]}><Checkbox>我确认以上补查及有限处理范围，仅用于本研究当前A03；生成的新A04另行复核。</Checkbox></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} disabled={!ids.length || !info?.enabled}>确认方案并应用到A04</Button>
      </Form>
    </Modal>
  </div>;
}
