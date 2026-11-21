// 文件用途：模块页下方的三个页签——结果明细（摘要表、完整明细、归档文件）、参数与版本、来源与追溯（含运行历史）。
import { Button, Empty, Image, Input, Modal, Table, Tabs, Tag, Tooltip } from 'antd';
import { DownloadOutlined, EyeOutlined, TableOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { api, apiUrl, errorText, fileUrl } from '../api/client';
import type { ModuleView, TableIndex, TablePage } from '../api/types';
import { decisionLabel, useApp } from '../lib/appContext';
import { cellText, fmtBytes, fmtTime, originZh, outcomeZh, shortId } from '../lib/format';
import { hrefFor } from '../lib/route';

/** 三个页签 */
export default function DataTabs({ studyId, view }: { studyId: string; view: ModuleView }) {
  return (
    <section className="card" style={{ padding: '4px 20px 16px' }}>
      <Tabs
        defaultActiveKey="detail"
        items={[
          { key: 'detail', label: '结果明细', children: <DetailTab studyId={studyId} view={view} /> },
          { key: 'params', label: '参数与版本', children: <ParamsTab view={view} /> },
          { key: 'trace', label: '来源与追溯', children: <TraceTab studyId={studyId} view={view} /> },
        ]}
      />
    </section>
  );
}

/** 结果明细页签 */
function DetailTab({ studyId, view }: { studyId: string; view: ModuleView }) {
  const [openTable, setOpenTable] = useState<TableIndex | null>(null); // 正在查看的完整明细表
  const t = view.table; // 摘要表
  const runId = view.historical ? view.run?.run_id : undefined; // 历史视图时读取对应运行的表
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* 摘要表 */}
      {t ? (
        <div>
          <div className="small muted" style={{ marginBottom: 6 }}>
            摘要表{t.source_table ? <>（来自 <span className="mono">{t.source_table}</span>，共 {t.row_count} 行）</> : `（共 ${t.row_count} 行）`}
          </div>
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            dataSource={t.rows}
            pagination={t.rows.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            scroll={{ x: 'max-content' }}
            columns={t.columns.map((c) => ({ title: c.label_zh, dataIndex: c.key, key: c.key, render: (v: unknown) => <CellView v={v} /> }))}
          />
        </div>
      ) : (
        <div className="small muted">本模块没有摘要表。</div>
      )}

      {/* 完整明细表列表 */}
      <div>
        <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>完整明细（{view.tables.length}）</h3>
        {view.tables.length === 0 ? (
          <div className="small muted">没有可分页查看的明细表。</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {view.tables.map((tb) => (
              <Button key={tb.name} icon={<TableOutlined />} onClick={() => setOpenTable(tb)}>
                <span className="mono">{tb.name}</span>
                <span className="muted small" style={{ marginLeft: 6 }}>{tb.kind === 'rows' ? `${tb.row_count ?? '?'} 行` : '结构化记录'}</span>
              </Button>
            ))}
            {view.module.module_id === 'A03' && view.run?.run_id &&
              view.tables.some((tb) => tb.name === 'intersection_targets') &&
              <Button icon={<DownloadOutlined />} href={apiUrl(`/api/v1/studies/${studyId}/runs/${view.run.run_id}/intersection-trace.csv`)}>
                下载交集来源追溯表
              </Button>}
          </div>
        )}
      </div>

      {/* 归档文件 */}
      <div>
        <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>归档文件（{view.files.length}）</h3>
        {view.files.length === 0 ? (
          <div className="small muted">没有归档文件。</div>
        ) : (
          <Table
            size="small"
            rowKey="key"
            dataSource={view.files}
            pagination={view.files.length > 12 ? { pageSize: 12, showSizeChanger: false } : false}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '文件', dataIndex: 'name', key: 'name', render: (v: string, f) => <Tooltip title={f.path}><span className="mono" style={{ overflowWrap: 'anywhere' }}>{v}</span></Tooltip> },
              { title: '类型', dataIndex: 'role', key: 'role', render: (v: string) => <span className="small muted">{v}</span> },
              { title: '大小', dataIndex: 'bytes', key: 'bytes', render: (v: number) => fmtBytes(v) },
              { title: 'SHA-256', dataIndex: 'sha256', key: 'sha256', render: (v: string) => <Tooltip title={v}><span className="mono tiny">{shortId(v, 12)}</span></Tooltip> },
              {
                title: '操作', key: 'op', render: (_, f) => (
                  <span style={{ display: 'inline-flex', gap: 6 }}>
                    {/* 图片可内嵌预览 */}
                    {f.inline && <InlinePreview src={fileUrl(studyId, f.key, true)} />}
                    <Button size="small" icon={<DownloadOutlined />} href={fileUrl(studyId, f.key)}>下载</Button>
                  </span>
                ),
              },
            ]}
          />
        )}
      </div>

      {/* 明细表弹窗 */}
      {openTable && <TableViewer studyId={studyId} moduleId={view.module.module_id} runId={runId} table={openTable} onClose={() => setOpenTable(null)} />}
    </div>
  );
}

/** 单元格显示：长文本自动换行，悬停显示原值 */
function CellView({ v }: { v: unknown }) {
  const text = cellText(v); // 显示文本
  const raw = v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v); // 原值
  return (
    <span title={raw !== text ? raw : undefined} style={{ display: 'inline-block', maxWidth: 420, overflowWrap: 'anywhere', whiteSpace: 'normal' }}>
      {text}
    </span>
  );
}

/** 图片预览按钮 */
function InlinePreview({ src }: { src: string }) {
  const [visible, setVisible] = useState(false); // 是否显示预览
  return (
    <>
      <Button size="small" icon={<EyeOutlined />} onClick={() => setVisible(true)}>预览</Button>
      <Image style={{ display: 'none' }} src={src} preview={{ visible, src, onVisibleChange: (v) => setVisible(v) }} />
    </>
  );
}

/** 完整明细表查看器：服务端分页 + 搜索 */
function TableViewer({ studyId, moduleId, runId, table, onClose }: { studyId: string; moduleId: string; runId?: string; table: TableIndex; onClose: () => void }) {
  const [page, setPage] = useState(1); // 当前页
  const [size, setSize] = useState(20); // 每页行数
  const [q, setQ] = useState(''); // 生效的搜索词
  const [input, setInput] = useState(''); // 输入框内容
  const [data, setData] = useState<TablePage | null>(null); // 当前页数据
  const [loading, setLoading] = useState(false); // 加载中
  const [error, setError] = useState<string | null>(null); // 错误说明

  // 页码、每页行数或搜索词变化时读取
  useEffect(() => {
    setLoading(true);
    api.table(studyId, moduleId, table.name, { page, size, q, runId })
      .then((r) => { setData(r); setError(null); })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [studyId, moduleId, table.name, page, size, q, runId]);

  return (
    <Modal open title={<span>明细表 <span className="mono">{table.name}</span></span>} onCancel={onClose} footer={null} width="min(1200px, 96vw)" destroyOnClose>
      {error && <div style={{ color: '#8E1B12', marginBottom: 8 }}>{error}</div>}
      {table.kind === 'object' || data?.kind === 'object' ? (
        // 结构化记录：格式化显示
        data?.kind === 'object' ? <pre className="json-box">{JSON.stringify(data.data, null, 2)}</pre> : <Empty description={loading ? '读取中…' : '无内容'} />
      ) : (
        <>
          {/* 搜索框 */}
          <Input.Search
            allowClear
            placeholder="在全部行中搜索（任意列包含该文字）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSearch={(v) => { setPage(1); setQ(v.trim()); }}
            style={{ maxWidth: 420, marginBottom: 10 }}
          />
          <Table
            size="small"
            loading={loading}
            rowKey={(_, i) => String(i)}
            dataSource={data?.kind === 'rows' ? data.items : []}
            scroll={{ x: 'max-content', y: '55vh' }}
            columns={(data?.kind === 'rows' ? data.columns : table.columns).map((c) => ({ title: c, dataIndex: c, key: c, render: (v: unknown) => <CellView v={v} /> }))}
            pagination={{
              current: page,
              pageSize: size,
              total: data?.kind === 'rows' ? data.total : 0,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: (n) => `共 ${n} 行${q ? `（搜索“${q}”）` : ''}`,
              onChange: (p, s) => { setPage(s !== size ? 1 : p); setSize(s); },
            }}
          />
        </>
      )}
    </Modal>
  );
}

/** 参数与版本页签 */
function ParamsTab({ view }: { view: ModuleView }) {
  if (!view.params.length) return <div className="small muted">没有登记参数。</div>;
  return (
    <dl className="dl">
      {view.params.map((p, i) => [
        <dt key={'k' + i}>{p.label_zh}</dt>,
        <dd key={'v' + i}>
          <span style={{ marginRight: 8 }}>{cellText(p.value)}</span>
          {/* 参数来源 */}
          <Tag bordered={false} color={p.origin === 'decision' ? 'orange' : p.origin === 'outline' ? 'cyan' : 'default'}>{originZh(p.origin)}</Tag>
        </dd>,
      ])}
    </dl>
  );
}

/** 来源与追溯页签：追溯信息、复核记录、运行历史 */
function TraceTab({ studyId, view }: { studyId: string; view: ModuleView }) {
  const { session } = useApp(); // 用于决定中文名
  const mid = view.module.module_id; // 模块编号
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* 追溯信息 */}
      <dl className="dl">
        {view.trace.map((t, i) => [
          <dt key={'k' + i}>{t.label_zh}</dt>,
          <dd key={'v' + i} className="mono" style={{ fontSize: 13, wordBreak: 'break-all' }}>{cellText(t.value)}</dd>,
        ])}
      </dl>

      {/* 复核记录 */}
      <div>
        <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>复核记录（{view.review.history.length}）</h3>
        {view.review.history.length === 0 ? (
          <div className="small muted">尚无复核记录。</div>
        ) : (
          <Table
            size="small"
            rowKey="review_id"
            dataSource={[...view.review.history].reverse()}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '时间', dataIndex: 'created_at', key: 't', render: (v: string) => fmtTime(v) },
              { title: '决定', dataIndex: 'decision', key: 'd', render: (v: string) => decisionLabel(session, v, view.module.module_id) },
              { title: '复核人', dataIndex: 'reviewer', key: 'r' },
              { title: '意见', dataIndex: 'note', key: 'n', render: (v: string) => <span style={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{v}</span> },
              { title: '复核编号', dataIndex: 'review_id', key: 'id', render: (v: string) => <span className="mono tiny">{v}</span> },
            ]}
          />
        )}
      </div>

      {/* 运行历史 */}
      <div>
        <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>运行历史（{view.history.length}）</h3>
        <Table
          size="small"
          rowKey="run_id"
          dataSource={view.history}
          pagination={view.history.length > 10 ? { pageSize: 10 } : false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '版本', dataIndex: 'order_zh', key: 'o', render: (v: string, r) => <span>{v} {r.is_current && <Tag color="green" bordered={false}>当前</Tag>}</span> },
            { title: '时间', dataIndex: 'created_at', key: 't', render: (v: string) => fmtTime(v) },
            { title: '原因', dataIndex: 'reason_zh', key: 'r', render: (v: string) => <span style={{ whiteSpace: 'normal' }}>{v || '—'}</span> },
            { title: '结果', dataIndex: 'outcome', key: 'oc', render: (v: string) => outcomeZh(v) },
            { title: '复核', dataIndex: 'review_decision', key: 'd', render: (v: string) => (v ? decisionLabel(session, v, view.module.module_id) : '未复核') },
            { title: '运行编号', dataIndex: 'run_id', key: 'id', render: (v: string) => <span className="mono tiny">{v}</span> },
            {
              title: '', key: 'op', render: (_, r) =>
                r.is_current
                  ? (view.historical ? <a href={hrefFor({ page: 'study', studyId, moduleId: mid })}>回到当前版本</a> : <span className="small muted">正在查看</span>)
                  : r.run_id === view.run?.run_id
                    ? <span className="small muted">正在查看</span>
                    : <a href={hrefFor({ page: 'study', studyId, moduleId: mid, runId: r.run_id })}>查看此版本</a>,
            },
          ]}
        />
      </div>
    </div>
  );
}
