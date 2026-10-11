// 展示同研究已归档两梯队，A04末尾仅展示交集表。
import { Alert, Button, Table, message } from 'antd';
import { useState } from 'react';
import type { DockingCandidateRow, DockingCandidatesInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';
import { hrefFor } from '../lib/route';

// 五列沿用PPI表顺序；只格式化小数，原指标不改变。
const columns = [
  { title: '基因', dataIndex: 'symbol' },
  { title: 'HGNC', dataIndex: 'target_id' },
  { title: 'Degree', dataIndex: 'degree' },
  { title: 'Betweenness', dataIndex: 'bc', render: (v: number) => <span title={String(v)}>{v.toFixed(3)}</span> },
  { title: 'Closeness', dataIndex: 'cc', render: (v: number) => <span title={String(v)}>{v.toFixed(4)}</span> },
];

// 空交集保留为空，不降低阈值晋升其他基因。
function GeneTable({ rows }: { rows: DockingCandidateRow[] }) {
  return <Table rowKey="target_id" size="small" className="ppi-reference-table" columns={columns} dataSource={rows} pagination={false} scroll={{ x: 650 }} locale={{ emptyText: '本组没有候选；不降低阈值补足。' }} />;
}

// 生成按钮仅整理已批准A04，不触发结构准备或真实对接。
export default function DockingCandidates({ studyId, moduleId, info }: { studyId: string; moduleId: string; info: DockingCandidatesInfo }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const data = info.data;
  const intersectionOnly = moduleId === 'A04';
  async function generate() {
    setBusy(true);
    try {
      const result = await api.dockingCandidates(studyId, intersectionOnly ? 'A04' : 'A06_PREP', {
        expected_a03: info.expected_a03, expected_a04: info.expected_a04,
        expected_a04_review: info.expected_a04_review, reason: '按已确认第二轮两梯队规则生成候选，真实对接另行确认',
      });
      app.trackTasks([result.task]); app.bumpRefresh();
      if (result.task.state === 'failed') message.error(result.task.error_zh || '候选任务启动失败');
      else message.success(result.message_zh);
    } catch (error) { message.error(errorText(error)); app.bumpRefresh(); }
    finally { setBusy(false); }
  }
  return <section className="card" id="a06-candidate-groups">
    <h2>{intersectionOnly ? 'Degree第二轮前十与BC＋CC第二轮前十五交集基因表（A组）' : 'A06 对接候选：两个梯队'}</h2>
    <p className="small muted">A组取两分支第二轮前十／前十五交集；B组取Degree第二轮前十五，重复优先A。边界并列全部保留。</p>
    {data ? <>
      {!intersectionOnly && <h3>第一梯队：候选证据级别 A（项目约定）</h3>}
      <p>A组 {data.counts.a} 个{!intersectionOnly && (' · B组 ' + data.counts.b + ' 个')}</p>
      <GeneTable rows={data.group_a} />
      {!intersectionOnly && <><h3>第二梯队：候选证据级别 B（项目约定）</h3><p className="small muted">Degree第二轮前十五含边界并列共 {data.counts.degree_top15} 个；已归A组者优先A，不重复列入B。</p><GeneTable rows={data.group_b} /></>}
      <p className="small muted">{data.note_zh}</p>
      <Button size="small" href={'/api/v1/studies/' + studyId + '/docking_candidates/' + data.group_id}>下载两梯队完整名单</Button>
    </> : <Alert type="info" message="两梯队名单尚未生成；请使用下方按钮。" />}
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
      <Button type={data ? 'default' : 'primary'} disabled={!info.enabled} loading={busy} onClick={generate}>{data ? '更新候选分组（保留历史）' : '生成候选分组'}</Button>
      {!intersectionOnly && <Button href={hrefFor({ page: 'study', studyId, moduleId: 'A03_SELECT' })}>前往对接成分核查</Button>}
    </div>
    {!info.enabled && <p className="small muted">{info.disabled_reason_zh}</p>}
    {!intersectionOnly && <Alert style={{ marginTop: 12 }} type="info" message={info.preparation_note_zh} description="当前为候选与微调准备阶段，真实分子对接未启动。A/B分组与受体结构质控分别记录。" />}
  </section>;
}
