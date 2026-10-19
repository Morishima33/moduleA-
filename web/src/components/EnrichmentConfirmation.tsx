// A05人工确认区紧接标题；批量勾选只调整展示范围，后台应用及整体复核分别显示。
import { Alert, Button, Checkbox, Input, Radio, Space, Table, Tag, message } from 'antd';
import { useEffect, useId, useMemo, useState } from 'react';
import type { EnrichmentDisplayInfo, EnrichmentCatalogRow } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';
import { fmtP, fmtTime } from '../lib/format';

// 每个研究和运行使用自己的已保存清单，刷新后恢复归档值，不从其他研究继承。
export default function EnrichmentConfirmation({ studyId, info, onPendingChange, navigationRequest = 0 }: { studyId: string; info: EnrichmentDisplayInfo; onPendingChange?: (pending: boolean) => void; navigationRequest?: number }) {
  const app = useApp();
  const [expanded, setExpanded] = useState(false); // 默认收起核查表单，折叠不清除已填写内容。
  useEffect(() => {if (navigationRequest > 0) setExpanded(true);}, [navigationRequest]); // 导航只展开显示，不保存。
  const detailsId = useId(); // 为展开按钮关联当前组件的详情区域。
  const [selected, setSelected] = useState<string[]>(info.excluded_ids);
  const [mode, setMode] = useState<'proposed' | 'uncertain' | 'all'>('proposed');
  const [excludeAllConfirmed, setExcludeAllConfirmed] = useState(false);
  const [query, setQuery] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [scopeChecked, setScopeChecked] = useState(false);
  const [layoutChecked, setLayoutChecked] = useState(false);
  const [busy, setBusy] = useState<'exclusions' | 'layout' | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setSelected(info.excluded_ids); setScopeChecked(false); setLayoutChecked(false); setExcludeAllConfirmed(false); setError(null);
    setReviewer(info.latest?.reviewer || ''); setNote('');
  }, [studyId, info.expected_a05]);
  const filtered = useMemo(() => info.catalog.filter(r => (mode === 'all' || (mode === 'proposed' ? r.proposed : r.classification_status === 'uncertain')) && (r.ID+' '+r.Description+' '+r.description_zh).toLowerCase().includes(query.trim().toLowerCase())), [info.catalog, mode, query]);
  const proposedIds = info.catalog.filter(r => r.proposed).map(r => r.ID);
  const allExcluded = info.significant_count > 0 && selected.length === info.significant_count;
  // 这些是本地排除草稿的数量，不是新统计或已保存范围。
  useEffect(() => { setExcludeAllConfirmed(false); }, [selected]);
  const sameScope = selected.length === info.excluded_ids.length && selected.every(id => info.excluded_ids.includes(id));
  // 本地名单修改或提交中暂时隐藏旧KEGG图，不将未保存选择当成已归档排除。
  useEffect(() => { onPendingChange?.(!sameScope || !!busy); }, [sameScope, busy, info.expected_a05, onPendingChange]);
  const writable = info.enabled && !busy;
  const filled = !!reviewer.trim() && !!note.trim();
  // 两个动作都要求用户明确勾选和填写；任何全选都不调用保存接口。
  async function submit(action: 'exclusions' | 'layout') {
    setBusy(action); setError(null);
    try {
      const response = await api.confirmEnrichmentDisplay(studyId, { expected_a03: info.expected_a03, expected_a05: info.expected_a05, expected_decision_id: info.expected_decision_id, action, reviewer: reviewer.trim(), note: note.trim(), excluded_ids: selected, confirmed: true, exclude_all_confirmed: excludeAllConfirmed });
      app.trackTasks([response.task]); app.bumpRefresh(); app.openTasks(response.task.task_id);
      if (response.task.state === 'failed') { setError(response.task.error_zh || '任务启动失败，请重试。'); message.error(response.task.error_zh || '任务启动失败'); }
      else message.success(response.message_zh);
    } catch (e) { setError(errorText(e)); app.bumpRefresh(); }
    finally { setBusy(null); }
  }
  function toggle(id: string, checked: boolean) {
    setSelected(current => checked ? Array.from(new Set([...current, id])) : current.filter(x => x !== id));
    setScopeChecked(false); setLayoutChecked(false);
  }
  // 证据行展示实际命中基因和原通路链接，查看证据不会自动确认。
  const columns = [
    { title: '排除', key: 'select', width: 70, render: (_: unknown, row: EnrichmentCatalogRow) => <Checkbox aria-label={'从展示中排除 '+row.ID} checked={selected.includes(row.ID)} disabled={!writable} onChange={e => toggle(row.ID, e.target.checked)} /> },
    // 中文名后只保留疾病标题提示；完整理由随证据展开，避免逐行重复。
    { title: '疾病／通路名称（中文）', key: 'term', render: (_: unknown, row: EnrichmentCatalogRow) => <div style={{ overflowWrap: 'anywhere' }}><strong>{row.description_zh || '中文待核译'}</strong>{row.proposed && <Tag color="orange">其他疾病类，拟排除</Tag>}{row.classification_status === 'uncertain' && <Tag color="gold">待判断</Tag>}{row.classification_zh && <div className="tiny muted">{row.classification_zh}</div>}</div> },
    { title: '英文名称', key: 'english', render: (_: unknown, row: EnrichmentCatalogRow) => <span style={{ overflowWrap: 'anywhere' }}>{row.Description.replace(' - Homo sapiens (human)', '')}<span className="mono tiny muted" style={{ marginLeft: 8 }}>{row.ID}</span></span> },
    { title: 'Count', dataIndex: 'Count', width: 72 },
    { title: '校正后P值', dataIndex: 'p.adjust', width: 110, render: (p: number) => <span className="mono" title={String(p)}>{fmtP(p)}</span> },
  ];
  return <section className="card" aria-label="A05需要你确认" style={{ border: '2px solid #0F5E6E' }}>
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
      <h2 style={{ marginTop: 0, marginBottom: 8 }}>A05 需要你确认</h2>
      <Button aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded(value => !value)}>{expanded ? '收起核查与确认' : '展开核查与确认'}</Button>
    </div>
    <Space wrap style={{ marginBottom: 12 }}>
      <Tag color={info.exclusions_confirmed ? 'green' : 'gold'}>1 展示范围：{info.exclusions_confirmed ? '已确认' : '待确认'}</Tag>
      <Tag color={info.layout_confirmed ? 'green' : 'gold'}>2 图表版式：{info.layout_confirmed ? '已确认' : '待确认'}</Tag>
      <span className="small">3 A05结果：在“复核决定”中独立确认</span>
      <Button size="small" onClick={() => document.getElementById('module-review-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>前往A05结果复核</Button>
    </Space>
    <Alert type="info" showIcon message={`显著总数 ${info.significant_count}；拟排除 ${info.screening?.proposed_count ?? proposedIds.length}；当前选择排除 ${selected.length}；预计保留 ${info.significant_count - selected.length}`} description={info.screening ? <>依据KEGG官方分类，其他人类疾病及癌症机制统一列为建议，本病直接条目保留。待判断 {info.screening.uncertain_count} 项。选择仅为草稿，确认后才应用。<a href={info.screening.source_url} target="_blank" rel="noreferrer">查看分类依据</a></> : '当前版本尚未归档官方分类候选；原选择继续保留，历史研究不自动改写。'} style={{ marginBottom: 12 }} />
    {allExcluded && <Alert type="warning" showIcon message="当前选择将排除全部KEGG显著通路，图表将为空" description={<Checkbox checked={excludeAllConfirmed} disabled={!writable} onChange={e => setExcludeAllConfirmed(e.target.checked)}>我确认本次需要排除全部KEGG显著通路</Checkbox>} style={{ marginBottom: 12 }} />}
    {!sameScope && info.exclusions_confirmed && <Alert type="warning" style={{ marginBottom: 10 }} message="排除选择有未保存修改；请先确认新清单，再核查新图表版式。" />}
    {error && <Alert type="error" showIcon style={{ marginBottom: 10 }} message={error} />}
    {/* 保留表单挂载；仅隐藏详情，收起和再次展开不会重置选择或发起提交。 */}
    <div id={detailsId} hidden={!expanded}>
    <Alert type="info" showIcon message="勾选表示从图表展示中排除，不删除原统计结果。" description="先核对清单并确认展示范围，再查看下方图表并确认版式。全选／全取消不会自动保存或批准A05；未勾选的条目保留。" />
    {info.latest && <Alert style={{ marginTop: 12 }} type={info.latest.applied ? 'success' : 'warning'} showIcon message={info.latest.status_zh} description={info.latest.reviewer+' · '+fmtTime(info.latest.created_at)+' · '+info.latest.note_zh} />}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, margin: '14px 0' }}>
      <label style={{ flex: '1 1 160px' }}>核验人<Input aria-label="A05核验人" value={reviewer} onChange={e => setReviewer(e.target.value)} maxLength={60} disabled={!writable} placeholder="填写姓名" /></label>
      <label style={{ flex: '3 1 260px' }}>核验说明<Input aria-label="A05核验说明" value={note} onChange={e => setNote(e.target.value)} maxLength={2000} disabled={!writable} placeholder="简要说明排除依据或版式核查意见" /></label>
    </div>
    {/* 主按钮就在核对区上方，当前选择和是否提交明确可见。 */}
    <div className="stack" style={{ gap: 10 }}>
      <Checkbox checked={scopeChecked} disabled={!writable} onChange={e => setScopeChecked(e.target.checked)}>已核对本次排除清单，包括不排除任何条目的情况</Checkbox>
      <Button type="primary" loading={busy === 'exclusions'} disabled={!writable || !filled || !scopeChecked || (allExcluded && !excludeAllConfirmed)} onClick={() => submit('exclusions')}>确认排除清单并生成图表</Button>
      <Checkbox checked={layoutChecked} disabled={!writable || !info.exclusions_confirmed || !sameScope || !!info.missing_translations.length} onChange={e => setLayoutChecked(e.target.checked)}>已查看下方GO、KEGG图表，认可中英文、科研配色、图例和排序</Checkbox>
      <Button type="primary" loading={busy === 'layout'} disabled={!writable || !filled || !layoutChecked || !info.exclusions_confirmed || !sameScope || !!info.missing_translations.length || info.layout_confirmed} onClick={() => submit('layout')}>{info.layout_confirmed ? '当前图表版式已确认' : '确认当前图表版式'}</Button>
    </div>
    {!filled && writable && <p className="small muted">填写核验人、说明，并勾选对应核对项后，确认按钮即可使用。</p>}
    {!!info.missing_translations.length && <Alert type="warning" style={{ marginTop: 10 }} message={'当前图表有待核译条目：'+info.missing_translations.join('、')} />}
    {!info.enabled && <Alert type="info" style={{ marginTop: 10 }} message={info.disabled_reason_zh} />}
    <h3 style={{ marginBottom: 8 }}>KEGG拟排除清单与完整显著通路</h3>
    <p className="small">已归档：{info.significant_count}条显著通路，展示保留{info.retained_count}条，排除{info.excluded_count}条。当前勾选{selected.length}条；点击确认前不会改变归档。</p>
    <Space wrap style={{ marginBottom: 12 }}>
      <Radio.Group value={mode} onChange={e => setMode(e.target.value)}><Radio.Button value="proposed">拟排除清单</Radio.Button><Radio.Button value="uncertain">待判断</Radio.Button><Radio.Button value="all">全部显著通路</Radio.Button></Radio.Group>
      <Button disabled={!writable || !proposedIds.length} onClick={() => { setSelected(current => Array.from(new Set([...current, ...proposedIds]))); setScopeChecked(false); setLayoutChecked(false); }}>勾选全部拟排除项（{proposedIds.length}项）</Button>
      <Input.Search aria-label="搜索KEGG清单" placeholder="搜索编号、中英文" value={query} onChange={e => setQuery(e.target.value)} allowClear style={{ width: 230, maxWidth: '100%' }} />
      <Button disabled={!writable || !filtered.length} onClick={() => { setSelected(current => Array.from(new Set([...current, ...filtered.map(r => r.ID)]))); setScopeChecked(false); setLayoutChecked(false); }}>将当前筛选结果勾选为排除（{filtered.length}项）</Button>
      <Button disabled={!writable || !selected.length} onClick={() => { setSelected([]); setScopeChecked(false); setLayoutChecked(false); }}>全部取消勾选</Button>
    </Space>
    <p className="tiny muted">批量勾选覆盖对应清单的全部分页；切换列表不清除选择。拟排除依据报告范围，不表示这些疾病与本病在生物学上完全无关。</p>
    <Table rowKey="ID" size="small" dataSource={filtered} columns={columns} scroll={{ x: 680 }} pagination={{ pageSize: 25, showSizeChanger: false, showTotal: total => '共 '+total+' 项' }} locale={{ emptyText: '当前筛选没有条目；可切换至全部显著通路。' }} expandable={{ expandedRowRender: row => <div>{row.reason_zh && <p className="small muted">{row.reason_zh}</p>}<p className="small" style={{ overflowWrap: 'anywhere' }}>实际命中基因：{row.gene_symbols || '原归档未提供符号，请查明细'}</p><a href={row.evidence_url} target="_blank" rel="noreferrer">查看官方通路定义与机制依据</a></div>, columnTitle: '证据', expandIcon: ({ expanded, onExpand, record }) => <Button size="small" onClick={e => onExpand(record,e)}>{expanded ? '收起' : '查看'}</Button>, columnWidth: 65 }} />
    </div>
  </section>;
}
