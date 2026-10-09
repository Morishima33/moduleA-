// 文件用途：A05 富集前列条目。按 BP/CC/MF/KEGG 页签切换；条长按该类中最大 count 归一，并显示 p.adjust。
import { Segmented, Tooltip } from 'antd';
import { useState } from 'react';
import type { EnrichItem } from '../../api/types';
import { fmtNum, fmtP } from '../../lib/format';
import { SectionHead } from '../common';

// 类别顺序与中文名
const GROUPS: { key: string; label: string }[] = [
  { key: 'bp', label: 'GO BP 生物过程' },
  { key: 'cc', label: 'GO CC 细胞组分' },
  { key: 'mf', label: 'GO MF 分子功能' },
  { key: 'kegg', label: 'KEGG 通路' },
];

/** A05 四类前列条目 */
export default function EnrichmentTop({ data }: { data: Record<string, EnrichItem[]> }) {
  const available = GROUPS.filter((g) => data[g.key]); // 接口实际提供的类别
  const [tab, setTab] = useState(available[0]?.key || 'bp'); // 当前类别
  const items = data[tab] || []; // 当前类别的条目
  const maxCount = Math.max(1, ...items.map((i) => i.count)); // 用于条长归一
  return (
    <section className="card">
      <SectionHead title="富集前列条目" extra="按 p.adjust 升序（与归档展示表同源）" />
      {/* 类别切换 */}
      <div style={{ overflowX: 'auto', marginBottom: 10 }}>
        <Segmented value={tab} onChange={(v) => setTab(String(v))} options={available.map((g) => ({ label: g.label, value: g.key }))} />
      </div>
      {/* 表头 */}
      <div className="enrich-row tiny muted" aria-hidden="true" style={{ borderBottom: '2px solid #DCE1E5' }}>
        <span>条目</span>
        <span className="eb">基因数（count）</span>
        <span style={{ textAlign: 'right' }}>p.adjust</span>
      </div>
      {items.length === 0 ? (
        <div className="small muted" style={{ padding: '10px 0' }}>该类别没有展示条目。</div>
      ) : (
        items.map((i) => (
          <div className="enrich-row" key={i.id}>
            {/* 条目名称与编号 */}
            <span style={{ minWidth: 0 }}>
              <span style={{ overflowWrap: 'anywhere' }}>{i.description}</span>
              <span className="mono tiny muted" style={{ marginLeft: 6 }}>{i.id}</span>
            </span>
            {/* 基因数横条 */}
            <Tooltip title={`count ${i.count} · GeneRatio ${i.gene_ratio} · RichFactor ${fmtNum(i.rich_factor)}`}>
              <span className="eb" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="bar-track" style={{ flex: 1 }}><span className="bar-fill" style={{ width: `${(i.count / maxCount) * 100}%` }} /></span>
                <span style={{ fontVariantNumeric: 'tabular-nums', minWidth: 24, textAlign: 'right' }}>{i.count}</span>
              </span>
            </Tooltip>
            {/* 校正后 p 值 */}
            <span className="mono small" style={{ textAlign: 'right' }}>{fmtP(i.p_adjust)}</span>
          </div>
        ))
      )}
      <p className="small muted" style={{ margin: '10px 0 0' }}>富集表示该基因集合的统计过度代表，不代表通路被激活、抑制或已证实疗效。</p>
    </section>
  );
}
