// A04待核验清单直接展示；只读查看同一次运行的证据，不代签身份决定。
import { Alert, Button, Descriptions, Drawer, Table, Tag } from 'antd';
import { useEffect, useState } from 'react';
import type { ModuleView, PpiIdentity, PpiIdentityRow } from '../api/types';
import { fileUrl } from '../api/client';

// 顶部核验区：逐项查看输入与返回名称；下载只使用后端提供的归档文件索引。
export default function IdentityReview({ studyId, view, data }: { studyId: string; view: ModuleView; data: PpiIdentity }) {
  const [selected, setSelected] = useState<PpiIdentityRow | null>(null);
  const source = view.files.find(f => f.role === 'string_source');
  const list = view.files.find(f => f.name === 'identity_issues.csv');
  useEffect(() => { setSelected(null); }, [studyId, view.run?.run_id]); // 版本改变时关闭旧证据，避免混用。
  return <div className="identity-review">
    <div className="identity-review-heading">
      <strong>身份核验清单</strong><Tag color="orange">{data.total}项待核验</Tag>
      {list && <Button size="small" href={fileUrl(studyId, list.key)}>下载本轮清单</Button>}
    </div>
    <Table<PpiIdentityRow> size="small" rowKey="target_id" pagination={false} dataSource={data.rows}
      scroll={{ x: 780, y: 330 }} columns={[
        { title: '输入基因', dataIndex: 'symbol', width: 125, render: (value: string, row) => <Button type="link" style={{ padding: 0 }} onClick={() => setSelected(row)} aria-label={`核查${row.symbol}的身份`}>{value}</Button> },
        { title: 'HGNC编号', dataIndex: 'target_id', width: 130 },
        { title: 'STRING返回名称', dataIndex: 'returned', width: 150, render: (value: string) => value || <span className="muted">未返回名称</span> },
        { title: '待核验原因', dataIndex: 'reason_zh', width: 180 },
        { title: '核验入口', key: 'check', width: 100, render: (_, row) => <Button size="small" onClick={() => setSelected(row)} aria-label={`查看${row.symbol}的核查证据`}>核查本项</Button> },
      ]} />
    <p className="small muted" style={{ margin: '8px 0 0' }}>{data.note_zh}</p>
    <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected ? `身份核查：${selected.symbol}` : '身份核查'} width="min(620px, 96vw)" destroyOnClose>
      {selected && <>
        <Alert type="warning" showIcon message="身份待核验" description="这里展示本次归档证据。处理方案确认前，不能将本项视为已核实或通过A04。" />
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
      </>}
    </Drawer>
  </div>;
}
