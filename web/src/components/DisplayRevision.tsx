// 文件用途：展示同批修订图、双语表和完整附件；明确操作只另存展示，不签署复核或生成Word。
import { Alert, Button, Checkbox, Collapse, Input, Table } from 'antd';
import { useEffect, useId, useRef, useState } from 'react';
import type {
  DisplayRevisionDownload, DisplayRevisionFigure, DisplayRevisionHistory,
  DisplayRevisionInfo, DisplayRevisionTable,
} from '../api/types';
import { api, apiUrl, ApiError, errorText } from '../api/client';
import { useApp } from '../lib/appContext';
import { fmtBytes, fmtTime } from '../lib/format';

/** 下载地址只采用本研究服务端已登记链接，不从文件名或磁盘路径构造。 */
function RevisionFiles({ files }: { files: DisplayRevisionDownload[] }) {
  return <div className="display-revision-files">{files.map((file, index) =>
    <a key={`${file.url}:${index}`} href={apiUrl(file.url)}
      title={[file.name, file.bytes === undefined ? '' : fmtBytes(file.bytes)].filter(Boolean).join(' · ')}>
      {file.label_zh || file.name}
    </a>)}</div>;
}

/** 图像独立按需加载；加载失败明确显示错误，不把空白视作已验证图。 */
function RevisionFigure({ figure }: { figure: DisplayRevisionFigure }) {
  const [failed, setFailed] = useState(false);
  return <figure className="display-revision-figure">
    <h3>{figure.label_zh}</h3>
    {failed ? <Alert type="error" showIcon message="图像未能加载，请刷新核对本批来源或打开图像查看错误。" /> :
      <img src={apiUrl(figure.image_url)} alt={figure.label_zh} loading="lazy" decoding="async" onError={() => setFailed(true)} />}
    <figcaption>{figure.caption_zh}</figcaption>
    <div className="display-revision-files">
      <a href={apiUrl(figure.image_url)} target="_blank" rel="noreferrer">打开完整图像</a>
      <RevisionFiles files={figure.downloads} />
    </div>
  </figure>;
}

/** 只转换显示格式，保留字符串、NA与完整数值精度，不填零或计算科学结果。 */
function valueText(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** 后台可提供明确标注的预览；total与完整CSV均采用服务端原值。 */
function RevisionTable({ table }: { table: DisplayRevisionTable }) {
  const headingId = useId();
  return <section className="display-revision-table" aria-labelledby={headingId}>
    <h3 id={headingId}>{table.label_zh}</h3>
    <p className="small muted">完整表共 {table.total} 条。{table.preview_note_zh}</p>
    <div className="display-revision-table-scroll">
      <Table<Record<string, unknown>> size="small" dataSource={table.rows}
        rowKey={(_, index) => `${table.key}:${index}`}
        columns={table.columns.map(column => ({
          key: column.key, dataIndex: column.key, title: column.label_zh,
          render: (value: unknown) => <span className="display-revision-cell" title={valueText(value)}>{valueText(value)}</span>,
        }))}
        pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 25, 50], showSizeChanger: true, showTotal: total => `当前预览 ${total} 条` }}
        scroll={{ x: 'max-content' }} locale={{ emptyText: '本表没有可展示记录，请核对本批说明与完整附件。' }} />
    </div>
    <RevisionFiles files={table.downloads} />
  </section>;
}

/** 来源编号只作只读追溯，历史修订不会替换当前来源或科学状态。 */
function RevisionArchive({ revision }: { revision: DisplayRevisionHistory }) {
  return <div className="display-revision-archive stack">
    <p><strong>{fmtTime(revision.created_at)}</strong> · {revision.matches_input === true ? '与当前来源一致' : revision.matches_input === false ? '历史来源' : '归档来源'}</p>
    <p className="small muted mono">{revision.revision_id}</p>
    <dl className="dl">{Object.entries(revision.source_run_ids).map(([moduleId, runId]) =>
      <div key={moduleId} className="display-revision-source"><dt>{moduleId}</dt><dd className="mono">{runId}</dd></div>)}</dl>
    <RevisionFiles files={revision.downloads} />
  </div>;
}

/** 明确提交五字段请求；网络重试保留同内容请求号，409只刷新、不自动重交。 */
function RevisionForm({ studyId, info }: { studyId: string; info: DisplayRevisionInfo }) {
  const app = useApp();
  const formId = useId();
  const [author, setAuthor] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null);
  const pending = useRef<{ signature: string; requestId: string } | null>(null);
  // 后台忙碌或资格改变后，旧勾选不沿用；该同步不会产生写请求。
  useEffect(() => { if (!info.enabled) setConfirmed(false); }, [info.enabled]);
  const canSubmit = info.enabled && !!info.expected_input_hash && !!author.trim() && !!note.trim() && confirmed && !busy;

  /** 只由表单提交触发写操作，后台独立核验本批来源。 */
  async function submit() {
    if (!canSubmit || !info.expected_input_hash) return;
    const signature = JSON.stringify([info.expected_input_hash, author.trim(), note.trim()]);
    if (pending.current?.signature !== signature) {
      pending.current = { signature, requestId: 'displayreq_' + crypto.randomUUID().replace(/-/g, '') };
    }
    setBusy(true); setConfirmed(false); setNotice(null);
    try {
      const result = await api.reviseDisplay(studyId, {
        request_id: pending.current.requestId, expected_input_hash: info.expected_input_hash,
        author: author.trim(), note: note.trim(), confirmed: true,
      });
      if (result.task) {
        app.trackTasks([result.task]);
        app.openTasks(result.task.task_id);
      }
      setNotice({ text: result.message_zh || '本批展示修订已登记，请查看后台任务或已归档的修订。', failed: false });
      app.bumpRefresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        pending.current = null;
        app.bumpRefresh();
      }
      setNotice({ text: errorText(error), failed: true });
    } finally { setBusy(false); }
  }

  return <form className="display-revision-form stack" onSubmit={event => { event.preventDefault(); void submit(); }}>
    <div>
      <label htmlFor={`${formId}-author`}>登记人</label>
      <Input id={`${formId}-author`} value={author} disabled={busy || !info.enabled} autoComplete="name"
        onChange={event => { setAuthor(event.target.value); setConfirmed(false); }} />
    </div>
    <div>
      <label htmlFor={`${formId}-note`}>本次更新说明</label>
      <Input.TextArea id={`${formId}-note`} value={note} disabled={busy || !info.enabled} rows={3}
        onChange={event => { setNote(event.target.value); setConfirmed(false); }} />
    </div>
    <Checkbox checked={confirmed} disabled={busy || !info.enabled}
      onChange={event => setConfirmed(event.target.checked)}>我确认仅另存同批图表与译名展示，保留原始结果和历史附件。</Checkbox>
    <div><Button htmlType="submit" type="primary" loading={busy} disabled={!canSubmit}>更新图表与译名</Button></div>
    {notice && <Alert type={notice.failed ? 'error' : 'info'} showIcon message={notice.text} />}
  </form>;
}

/** 按本模块选择展示类别，所有数量、成员、译名及资格均直接采用服务端事实。 */
export default function DisplayRevision({ studyId, moduleId, info }: { studyId: string; moduleId: string; info: DisplayRevisionInfo }) {
  const scoped = info.module_current?.module_id === moduleId ? info.module_current : null;
  if (!info.supported && !scoped) return null;
  const current = info.current;
  const matching = current?.matches_input ? current : scoped?.record || null;
  const figures = matching?.figures.filter(figure => moduleId === 'A07' || figure.module_id === moduleId) || [];
  const tables = matching?.tables.filter(table => moduleId === 'A07' || table.module_id === moduleId) || [];
  const primaryFigures = figures.filter(figure => figure.role !== 'full_network_overview');
  const overviewFigures = figures.filter(figure => figure.role === 'full_network_overview');
  const history = info.history.filter(revision => revision.revision_id !== current?.revision_id);
  return <section id="display-revision" className="card stack display-revision" aria-label="同批图表与译名">
    <div>
      <h2>同批图表与译名</h2>
      <p>另存本批图表、双语术语表与核译依据，原始统计、评分和历史附件均可追溯。展示修订不代表科研复核通过。</p>
    </div>
    {current && !matching && <Alert type="warning" showIcon message="已有展示修订对应历史来源，本页继续显示当前原始结果。"
      description="请先核对当前资料与阻断说明，再明确更新图表与译名。" />}
    {scoped && !current?.matches_input && <Alert type="info" showIcon message="沿用本模块已登记图表" description={scoped.note_zh} />}
    {matching && <>
      <p className="small muted">修订保存于 {fmtTime(matching.created_at)}</p>
      <dl className="display-revision-counts">{matching.counts.map((count, index) => <div key={`${count.label_zh}:${index}`}>
        <dt>{count.label_zh}</dt><dd>{count.text}</dd>
      </div>)}</dl>
      <p className="small">译名覆盖：需核译 {matching.translation_coverage.required} 条，已核译 {matching.translation_coverage.verified} 条。</p>
      {matching.translation_coverage.missing.length > 0 && <Alert type="error" showIcon message="本批仍有缺译，最终交付已阻断。"
        description={<span className="display-revision-cell">缺少稳定编号：{matching.translation_coverage.missing.join('、')}</span>} />}
      {primaryFigures.map(figure => <RevisionFigure key={`${matching.revision_id}:${figure.key}`} figure={figure} />)}
      {overviewFigures.length > 0 && <Collapse items={[{ key: 'overview', label: '全网概览（与Degree第二轮主图分开）', children:
        <div className="stack">{overviewFigures.map(figure => <RevisionFigure key={`${matching.revision_id}:${figure.key}`} figure={figure} />)}</div> }]} />}
      {tables.map(table => <RevisionTable key={`${matching.revision_id}:${table.key}`} table={table} />)}
      <Collapse items={[{ key: 'archive', label: '完整附件、核译依据与本批来源', children: <RevisionArchive revision={matching} /> }]} />
    </>}
    {!info.enabled && info.blockers.length > 0 && <Alert type="info" showIcon message="当前不能更新展示"
      description={<ul>{info.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul>} />}
    <details className="display-revision-action" open={!current}>
      <summary>更新图表与译名</summary>
      <RevisionForm key={info.expected_input_hash || 'no-source'} studyId={studyId} info={info} />
    </details>
    {(current && !matching || history.length > 0) && <Collapse items={[{ key: 'history', label: '历史展示修订（保留）', children:
      <div className="stack">{current && !matching && <RevisionArchive revision={current} />}
        {history.map(revision => <RevisionArchive key={revision.revision_id} revision={revision} />)}</div> }]} />}
  </section>;
}
