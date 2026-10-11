// A05图表按归档顺序展示；网页只格式化，不重新计算排序、富集或确认状态。
import { Alert, Button, Table } from 'antd';
import type { EnrichmentCatalogRow, Special } from '../../api/types';
import { fmtP } from '../../lib/format';

const GO = [{ key: 'bp_top15', label: 'BP 生物过程' }, { key: 'cc_top15', label: 'CC 细胞组分' }, { key: 'mf_top15', label: 'MF 分子功能' }] as const;

// 英文和中文分列；标准编号跟在英文后面保持原tiny字号。
const englishColumn = { title: '条目名称（英文）', key: 'english', render: (_: unknown, row: EnrichmentCatalogRow) => <span style={{ overflowWrap: 'anywhere' }}>{row.Description.replace(' - Homo sapiens (human)', '')}<span className="mono tiny muted" style={{ marginLeft: 8 }}>{row.ID}</span></span> };
const chineseColumn = { title: '中文名称', key: 'chinese', render: (_: unknown, row: EnrichmentCatalogRow) => <span style={{ overflowWrap: 'anywhere' }}>{row.description_zh || '中文待核译'}</span> };
const pColumn = { title: '校正后P值（BH）', dataIndex: 'p.adjust', width: 150, render: (p: number) => <span className="mono" title={String(p)}>{fmtP(p)}</span> };

// 先GO图、GO三段表，再KEGG图及两张表；与专业报告A05段落同序。
export default function EnrichmentDisplay({ special }: { special: Special }) {
  const tables = special.enrichment_display_tables;
  if (!tables) return null;
  function graph(key: 'go' | 'kegg') {
    const item = special.enrichment_graphs?.[key];
    return item ? <figure style={{ margin: '12px 0 22px' }}><a href={item.url} target="_blank" rel="noreferrer" aria-label={key === 'go' ? '放大GO图' : '放大KEGG图'}><img src={item.url} alt={key === 'go' ? 'GO三分类前八条目科研柱图' : 'KEGG前十五条目科研气泡图'} style={{ width: '100%', height: 'auto', display: 'block' }} /></a><figcaption className="small muted" style={{ marginTop: 8 }}>{item.caption_zh} 点击图片可放大核查。</figcaption></figure> : <Alert type="warning" message="本次归档图尚未就绪，不使用历史图代替。" />;
  }
  return <section className="card" aria-label="A05图表预览">
    <h2>GO与KEGG图表</h2>
    <p className="small muted">统计显著性与通路覆盖是不同指标；富集不代表通路被激活、抑制或已证明疗效。完整编号、精确原值及全表可在下方结果明细下载。</p>
    <h3>图 A05 01 GO三分类前八</h3>{graph('go')}
    {GO.map((group, i) => <div key={group.key} style={{ marginBottom: 18 }}><h3>表 A05 0{i+1} GO {group.label}前十五</h3><Table rowKey="ID" size="small" pagination={false} dataSource={tables[group.key]} columns={[englishColumn, chineseColumn, pColumn]} scroll={{ x: 720 }} locale={{ emptyText: '本类无显著条目，不放宽阈值补项。' }} /></div>)}
    <h3>图 A05 02 KEGG统计显著性前十五</h3>{graph('kegg')}
    {[{ key: 'kegg_p_top10', title: '表 A05 04 KEGG统计显著性前十', note: '按校正后P值升序，体现统计证据；同值按稳定编号排列。' }, { key: 'kegg_count_top10', title: '表 A05 05 KEGG命中基因数前十', note: '按Count降序，体现命中规模；同值按校正后P值和稳定编号排列。' }].map(group => <div key={group.key} style={{ marginBottom: 18 }}><h3>{group.title}</h3><p className="small muted">{group.note}</p><Table rowKey="ID" size="small" pagination={false} dataSource={tables[group.key]} columns={[{ ...englishColumn, title: '通路名称（英文）' }, chineseColumn, { title: 'Count', dataIndex: 'Count', width: 80 }, pColumn]} scroll={{ x: 790 }} locale={{ emptyText: '当前展示范围无显著通路，不补造条目。' }} /></div>)}
    <p className="small muted">只从显著且未获人工排除的完整名单选取；不足名额按实际数量展示。排除不改变原统计或BH校正。</p>
    <Button onClick={() => document.querySelector('[aria-label="A05需要你确认"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>返回顶部确认区</Button>
  </section>;
}
