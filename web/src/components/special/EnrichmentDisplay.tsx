// A05图表按归档顺序展示；网页只格式化，不重新计算排序、富集或确认状态。
import { Alert, Button, Table } from 'antd';
import type { EnrichmentCatalogRow, EnrichmentDisplayInfo, RankedPathwayMapsInfo, Special } from '../../api/types';
import { fmtP } from '../../lib/format';
import RankedPathwayMaps from '../RankedPathwayMaps';

const GO = [{ key: 'bp_top15', label: 'BP 生物过程' }, { key: 'cc_top15', label: 'CC 细胞组分' }, { key: 'mf_top15', label: 'MF 分子功能' }] as const;

// 英文和中文分列；标准编号跟在英文后面保持原tiny字号。
const englishColumn = { title: '条目名称（英文）', key: 'english', render: (_: unknown, row: EnrichmentCatalogRow) => <span style={{ overflowWrap: 'anywhere' }}>{row.Description.replace(' - Homo sapiens (human)', '')}<span className="mono tiny muted" style={{ marginLeft: 8 }}>{row.ID}</span></span> };
const chineseColumn = { title: '中文名称', key: 'chinese', render: (_: unknown, row: EnrichmentCatalogRow) => <span style={{ overflowWrap: 'anywhere' }}>{row.description_zh || '中文待核译'}</span> };
const pColumn = { title: '校正后P值（BH）', dataIndex: 'p.adjust', width: 150, render: (p: number) => <span className="mono" title={String(p)}>{fmtP(p)}</span> };

// GO与KEGG分别采用概述、表格、图件，最后展示两张首位通路命中图。
export default function EnrichmentDisplay({ special, info, pending, rankedMaps, studyId }: { special: Special; info?: EnrichmentDisplayInfo | null; pending: boolean; rankedMaps?: RankedPathwayMapsInfo | null; studyId: string }) {
  const tables = special.enrichment_display_tables;
  if (!tables) return null;
  const showKegg = !!info?.kegg_ready && !pending; // 是否应用来自接口；未保存选择仅暂时隐藏。
  function graph(key: 'go' | 'kegg') {
    if (key === 'kegg' && info && info.significant_count > 0 && info.retained_count === 0) return <Alert type="warning" showIcon message={`原统计有${info.significant_count}条显著通路，已全部从本轮展示排除，因此图表为空。`} />;
    const item = special.enrichment_graphs?.[key];
    return item ? <figure style={{ margin: '12px 0 22px' }}><a href={item.url} target="_blank" rel="noreferrer" aria-label={key === 'go' ? '放大GO图' : '放大KEGG图'}><img src={item.url} alt={key === 'go' ? 'GO三分类前八条目科研柱图' : 'KEGG前十五条目科研气泡图'} style={{ width: '100%', height: 'auto', display: 'block' }} /></a><figcaption className="small muted" style={{ marginTop: 8 }}>{item.caption_zh} 点击图片可放大核查。</figcaption></figure> : <Alert type="warning" message="本次归档图尚未就绪，不使用历史图代替。" />;
  }
  return <section className="card" aria-label="A05图表预览">
    <h2>GO与KEGG图表</h2>
    <p className="small muted">统计显著性与通路覆盖是不同指标；富集不代表通路被激活、抑制或已证明疗效。完整编号、精确原值及全表可在下方结果明细下载。</p>
    <h3>GO功能富集</h3><p className="small muted">BP（生物过程）、CC（细胞组分）、MF（分子功能）分别按BH校正后P值升序，反映当前基因集合的统计富集。</p>
    {GO.map((group, i) => <div key={group.key} style={{ marginBottom: 18 }}><h3>表 A05 0{i+1} GO {group.label}前十五</h3><Table rowKey="ID" size="small" pagination={false} dataSource={tables[group.key]} columns={[englishColumn, chineseColumn, pColumn]} scroll={{ x: 720 }} locale={{ emptyText: '本类无显著条目，不放宽阈值补项。' }} /></div>)}
    <h3>图 A05 01 GO三分类前八</h3>{graph('go')}
    {showKegg ? <>
    <h3>KEGG通路富集</h3><p className="small muted">统计显著性按BH校正后P值排序；命中基因数按Count排序。两项分别说明统计证据和命中规模。</p>
    {[{ key: 'kegg_p_top10', title: '表 A05 04 KEGG统计显著性前十', note: '按校正后P值升序，体现统计证据；同值按稳定编号排列。' }, { key: 'kegg_count_top10', title: '表 A05 05 KEGG命中基因数前十', note: '按Count降序，体现命中规模；同值按校正后P值和稳定编号排列。' }].map(group => <div key={group.key} style={{ marginBottom: 18 }}><h3>{group.title}</h3><p className="small muted">{group.note}</p><Table rowKey="ID" size="small" pagination={false} dataSource={tables[group.key]} columns={[{ ...englishColumn, title: '通路名称（英文）' }, chineseColumn, { title: 'Count', dataIndex: 'Count', width: 80 }, pColumn]} scroll={{ x: 790 }} locale={{ emptyText: info && info.significant_count > 0 && info.retained_count === 0 ? '原统计存在显著通路，当前已全部被展示排除；可返回确认区调整清单。' : '原统计无显著KEGG通路，不放宽阈值补项。' }} /></div>)}
    <h3>图 A05 02 KEGG统计显著性前十五</h3>{graph('kegg')}
    {rankedMaps && <RankedPathwayMaps studyId={studyId} info={rankedMaps}/>}
    </> : <Alert type="info" showIcon message="KEGG图表暂不显示" description={pending ? '排除选择有改动或正在提交，请确认清单并等待应用完成；不展示旧图表。' : info?.kegg_reason_zh || '排除范围尚未应用，完成后才显示图和两张表。'} />}
    <p className="small muted">只从显著且未获人工排除的完整名单选取；不足名额按实际数量展示。排除不改变原统计或BH校正。</p>
    <Button onClick={() => document.querySelector('[aria-label="A05需要你确认"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>返回顶部确认区</Button>
  </section>;
}
