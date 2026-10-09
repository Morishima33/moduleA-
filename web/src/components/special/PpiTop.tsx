// 文件用途：A04 第一轮主候选前 10（按 Degree 横条）。条长使用接口给出的 bar（0–1），并标注是否第二轮也入选。
import { Tooltip } from 'antd';
import type { PpiTopItem } from '../../api/types';
import { fmtNum } from '../../lib/format';
import { SectionHead } from '../common';

/** A04 前 10 Degree 横条图 */
export default function PpiTop({ items }: { items: PpiTopItem[] }) {
  return (
    <section className="card">
      <SectionHead title={`第一轮主候选（按 Degree 前 ${items.length}）`} extra="条长按 Degree 相对最大值" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {/* 表头 */}
        <div className="bar-row tiny muted" aria-hidden="true">
          <span>基因</span>
          <span>Degree</span>
          <span style={{ textAlign: 'right' }}>值</span>
          <span className="r2">第二轮</span>
        </div>
        {items.map((g) => (
          // 每个基因一行
          <Tooltip key={g.symbol} title={`Degree ${g.degree} · BC ${fmtNum(g.bc)} · CC ${fmtNum(g.cc)}`} placement="topLeft">
            <div className="bar-row">
              <span className="mono" style={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{g.symbol}</span>
              <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, g.bar)) * 100}%` }} /></span>
              <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{g.degree}</span>
              <span className="r2 tiny" style={{ color: g.round2 ? '#0A4350' : '#56636F' }}>{g.round2 ? '第二轮也入选' : '仅第一轮'}</span>
            </div>
          </Tooltip>
        ))}
      </div>
      <p className="small muted" style={{ margin: '10px 0 0' }}>阈值与完整指标见“结果明细”中的阈值表和 round1 / round2 明细；孤立节点单列，不记作 Degree = 0。</p>
    </section>
  );
}
