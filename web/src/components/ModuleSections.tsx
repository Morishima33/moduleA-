// 文件用途：模块页的通用区块：重点核对、需要知悉、关键数字、数量变化链、下游影响。内容全部来自 ModuleView，不在前端推算。
import type { ReactNode } from 'react';
import type { FlowStep, FocusItem, Kpi, ModuleView } from '../api/types';
import { hrefFor } from '../lib/route';
import { StatusPill } from './common';

/** “本轮你只需核对这些”：只列 must_handle，编号显示；为空时给出“没有需要处理的事项” */
export function FocusSection({ items, evidence }: { items: FocusItem[]; evidence?: ReactNode }) {
  const must = items.filter((f) => f.tier === 'must_handle'); // 必须处理项
  if (!must.length) {
    // 没有必须处理项
    return (
      <section className="card" style={{ borderColor: '#B9DCC8', display: 'flex', alignItems: 'center', gap: 12 }}>
        <CheckBadge />
        <span style={{ fontSize: 14 }}>本模块没有需要你处理的事项。</span>
      </section>
    );
  }
  return (
    <section className="card focus-box" aria-label="本轮你只需核对这些" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <CheckBadge warn />
        <h2 style={{ margin: 0, fontSize: 18 }}>本轮需要你核验</h2>
      </div>
      {must.map((f, i) => (
        // 每个必须处理项：编号、标题、说明、影响
        <div key={i} className="focus-item">
          <span className="focus-n">{i + 1}</span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, width: '100%' }}>
            <strong style={{ fontSize: 15 }}>{f.title_zh}</strong>
            {f.body_zh && <span style={{ fontSize: 14, color: '#3A4651' }}>{f.body_zh}</span>}
            {f.impact_zh && <span style={{ fontSize: 13, color: '#7A4100' }}>{f.impact_zh}</span>}
            {f.source_table === 'identity_issues' && evidence}
          </div>
        </div>
      ))}
    </section>
  );
}

/** “需要知悉”：随总体复核知悉，不逐条确认 */
export function KnowSection({ items, evidence }: { items: FocusItem[]; evidence?: ReactNode }) {
  const know = items.filter((f) => f.tier !== 'must_handle'); // 需要知悉项
  if (!know.length) return null; // 没有就不显示
  return (
    <section className="card" aria-label="需要知悉">
      <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>需要知悉</h2>
      <p className="small muted" style={{ margin: '0 0 10px' }}>以下事项随总体复核一并知悉，不需要逐条确认。</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {know.map((f, i) => (
          <div key={i} className="know-item">
            <strong style={{ fontSize: 14 }}>{f.title_zh}</strong>
            {f.body_zh && <span style={{ fontSize: 14, color: '#3A4651' }}>{f.body_zh}</span>}
            {f.impact_zh && <span style={{ fontSize: 13, color: '#7A4100' }}>{f.impact_zh}</span>}
            {f.source_table === 'identity_issues' && evidence}
          </div>
        ))}
      </div>
    </section>
  );
}

/** 圆形勾选徽标：绿色表示无事项，橙色表示需要核对 */
function CheckBadge({ warn }: { warn?: boolean }) {
  return (
    <span aria-hidden="true" style={{ width: 28, height: 28, flex: '0 0 28px', borderRadius: '50%', background: warn ? '#FFF0D6' : '#E3F2EA', color: warn ? '#7A4100' : '#17633F', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">{warn ? <path d="M8 3v6M8 12v1" /> : <path d="M3 8.5 6.5 12 13 4.5" />}</svg>
    </span>
  );
}

/** 关键数字卡片 */
export function KpiGrid({ kpis }: { kpis: Kpi[] }) {
  if (!kpis.length) return null; // 没有关键数字
  return (
    <section className="kpis" aria-label="关键数字">
      {kpis.map((k, i) => (
        <div key={i} className="kpi" title={k.source || undefined}>
          <span className="small muted">{k.label_zh}</span>
          <span className="v">{k.text}</span>
          {k.note_zh && <span className="tiny muted">{k.note_zh}</span>}
        </div>
      ))}
    </section>
  );
}

// 数量变化链各类步骤的底色与边框
const FLOW_TONE: Record<string, [string, string]> = {
  main: ['#E6EEF0', '#9DC0C8'], // 起点/主要输入
  end: ['#E3F2EA', '#9FCFB4'], // 结果
  plain: ['#F6F8F9', '#DCE1E5'], // 中间步骤
};

/** 数量变化链：每一步之间显示变化说明，以“−”开头的减少用红色 */
export function FlowChain({ steps, note }: { steps: FlowStep[]; note: string }) {
  if (!steps.length) return null; // 没有数量变化
  return (
    <section className="card" aria-label="数量变化">
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 17 }}>数量变化</h2>
        <span className="small muted">每一步减少了多少、为什么减少</span>
      </div>
      <div className="flow">
        {steps.map((s, i) => {
          const tone = FLOW_TONE[s.kind] || FLOW_TONE.plain; // 该步配色
          const minus = s.delta_zh.startsWith('−') || s.delta_zh.startsWith('-'); // 是否为减少
          return [
            // 与上一步之间的箭头和变化说明（第一步之前不显示）
            i > 0 && (
              <div key={'a' + i} className="flow-arrow" style={{ color: minus ? '#8E1B12' : '#3A4651' }}>
                <svg width="28" height="12" viewBox="0 0 28 12" fill="none" stroke="#8C969E" strokeWidth="1.6" aria-hidden="true"><path d="M1 6h24M20 1.5 25.5 6 20 10.5" /></svg>
                {s.delta_zh && <span>{s.delta_zh}</span>}
              </div>
            ),
            // 步骤卡片
            <div key={'s' + i} className="flow-step" style={{ background: tone[0], border: `1px solid ${tone[1]}` }}>
              <span className="tiny" style={{ color: '#3A4651', lineHeight: 1.35 }}>{s.label_zh}</span>
              <span className="v">{s.text}</span>
              {s.note_zh && <span className="tiny muted" style={{ lineHeight: 1.35 }}>{s.note_zh}</span>}
            </div>,
          ];
        })}
      </div>
      {note && <p className="tiny muted" style={{ margin: '10px 0 0' }}>{note}</p>}
    </section>
  );
}

/** 下游影响：说明 + 下游模块当前状态（可点击跳转） */
export function DownstreamCard({ studyId, downstream }: { studyId: string; downstream: ModuleView['downstream'] }) {
  return (
    <section className="card" style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
      <strong style={{ fontSize: 14 }}>影响范围</strong>
      <span style={{ color: '#3A4651' }}>{downstream.note_zh}</span>
      {downstream.modules.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {downstream.modules.map((m) => (
            <a key={m.module_id} href={hrefFor({ page: 'study', studyId, moduleId: m.module_id })}
              style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#17212B', textDecoration: 'none' }}>
              <span className="mono tiny muted" style={{ minWidth: 76 }}>{m.module_id}</span>
              <span style={{ flex: 1, minWidth: 0 }}>{m.title_zh}</span>
              <StatusPill code={m.code} label={m.label_zh} />
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
