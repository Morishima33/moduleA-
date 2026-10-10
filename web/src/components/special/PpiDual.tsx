// A04双分支第二轮排名表；完整数值与名次直接来自归档。
import { Alert, Table, Tooltip } from 'antd';
import type { PpiDual as Dual, PpiDualRow } from '../../api/types';
import { SectionHead } from '../common';

// 简短显示数值，悬停查看完整值；不影响名次与阈值判断。
function metric(value: number) { return <Tooltip title={String(value)}>{Number(value.toPrecision(6)).toString()}</Tooltip>; }

// 空结果、边界并列和数量不足均显式呈现，两分支不串成一个筛选链。
export default function PpiDual({ data }: { data: Dual }) {
  const base = [{ title: '名次', dataIndex: 'rank', width: 72 }, { title: '基因', dataIndex: 'symbol', width: 130 }, { title: 'HGNC ID', dataIndex: 'target_id', width: 130 }];
  const metrics = [{ title: 'Degree', dataIndex: 'degree', width: 90 }, { title: 'BC', dataIndex: 'bc', render: metric, width: 110 }, { title: 'CC', dataIndex: 'cc', render: metric, width: 110 }];
  const degreeColumns = [{ title: '基因', dataIndex: 'symbol', width: 130 }, { title: 'HGNC', dataIndex: 'target_id', width: 130 }, metrics[0], { ...metrics[1], title: 'Betweenness', render: (value: number) => <Tooltip title={String(value)}>{value.toFixed(3)}</Tooltip> }, { ...metrics[2], title: 'Closeness', render: (value: number) => <Tooltip title={String(value)}>{value.toFixed(4)}</Tooltip> }];
  return <section className="card">
    <SectionHead title="A04 网络图与候选排名" extra="两分支独立筛选" />
    <p className="small muted">{data.note_zh}</p>
    <h3>Degree{data.degree_round === 1 ? '第一轮' : '第二轮'}前十</h3>
    <p className="small muted">第一轮 {data.counts.degree_round1_count} 个 → 第二轮 {data.counts.degree_round2_count} 个；本表 {data.degree_rows.length} 个。</p>
    <Table<PpiDualRow> size="small" rowKey="target_id" className="ppi-reference-table" columns={degreeColumns} dataSource={data.degree_rows} pagination={false} scroll={{ x: 650 }} locale={{ emptyText: '本表对应轮次没有符合条件的Degree候选，不补足前十。' }} />
    {data.network && <h3 style={{ marginTop: 24 }}>Degree{(data.network_round ?? data.degree_round) === 1 ? '第一轮' : '第二轮'}候选网络</h3>}
    {data.network && <figure style={{ margin: '12px 0' }}>
      <img src={data.network.url} alt={`Degree${(data.network_round ?? data.degree_round) === 1 ? '第一轮' : '第二轮'}候选网络：对应轮次前十及边界并列标红`} style={{ display: 'block', width: '100%', maxWidth: 1000, margin: 'auto' }} />
      <figcaption className="small muted" style={{ marginTop: 12 }}>{data.network.caption_zh}</figcaption>
    </figure>}
    <h3 style={{ marginTop: 24 }}>BC＋CC第二轮前十五</h3>
    <p className="small muted">第一轮 {data.counts.bc_cc_round1_count} 个 → 第二轮 {data.counts.bc_cc_round2_count} 个；本表 {data.bc_cc_rows.length} 个。两项平均名次越小越靠前。</p>
    <Table<PpiDualRow> size="small" rowKey="target_id" className="ppi-reference-table" columns={[...base, metrics[1], metrics[2], { title: '两项平均名次', dataIndex: 'mean_rank', width: 130 }, metrics[0]]} dataSource={data.bc_cc_rows} pagination={false} scroll={{ x: 790 }} locale={{ emptyText: '第二轮没有同时满足BC、CC条件的候选，不补足前十五。' }} />
    <Alert style={{ marginTop: 16 }} type="info" showIcon message={data.network_note_zh} />
  </section>;
}
