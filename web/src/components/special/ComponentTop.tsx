// 文件用途：A03前十成分核查表；名次与数字均来自归档结果，不改变候选选择。
import { Table } from 'antd';
import type { Special } from '../../api/types';
import { SectionHead } from '../common';

/** 展示排名前十及截断并列，完整排名仍在结果明细中。 */
export default function ComponentTop({ items, note }: { items: NonNullable<Special['component_top']>; note?: string }) {
  return <section className="card">
    <SectionHead title="成分按疾病交集靶点覆盖数排名 · 前十" />
    <p className="small muted">{note}</p>
    <Table rowKey="compound_id" dataSource={items} pagination={false} size="small" scroll={{ x: 650 }} columns={[
      { title: '名次', dataIndex: 'main_rank', width: 65 },
      { title: '成分名称', dataIndex: 'name' },
      { title: '来源药味', dataIndex: 'herbs', width: 130 },
      { title: '不同交集靶点数', dataIndex: 'intersection_count', width: 140 },
      { title: '混合 Degree（参考）', dataIndex: 'mixed_degree', width: 160 },
    ]} />
  </section>;
}
