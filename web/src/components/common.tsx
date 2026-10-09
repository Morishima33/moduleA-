// 文件用途：多处复用的小组件：状态胶囊、进度分段条、归档未就绪提示、研究用途标签、区块标题。
import { Alert, Tag, Tooltip } from 'antd';
import type { ReactNode } from 'react';
import type { Purpose, StateCode } from '../api/types';
import { purposeShort } from '../lib/format';
import { stateStyle } from '../lib/theme';

/** 状态胶囊：颜色按状态码取，文字一律用接口给出的中文 */
export function StatusPill({ code, label, large }: { code: StateCode | string; label: string; large?: boolean }) {
  const s = stateStyle(code); // 该状态的配色
  return (
    <span className={'pill' + (large ? ' lg' : '')} style={{ background: s.bg, color: s.fg, border: s.border }}>
      {label}
    </span>
  );
}

/** 进度分段条：每个模块一段，颜色表示该模块状态，悬停显示模块名与状态 */
export function ProgressSegs({ segments, height = 8 }: { segments: { module_id: string; code: string; label_zh: string }[]; height?: number }) {
  return (
    <div className="segs" role="img" aria-label={segments.map((s) => `${s.module_id} ${s.label_zh}`).join('，')}>
      {segments.map((s) => (
        // 每一段一个色块
        <Tooltip key={s.module_id} title={`${s.module_id} · ${s.label_zh}`}>
          <span style={{ background: stateStyle(s.code).dot, height }} />
        </Tooltip>
      ))}
    </div>
  );
}

/** 归档未就绪提示：说明原因，并提示可能是大文件尚未下载完整 */
export function ArchiveAlert({ error, compact }: { error: string | null | undefined; compact?: boolean }) {
  return (
    <Alert
      type="error"
      showIcon
      message="研究归档未就绪，暂不能显示结果"
      description={
        <div className={compact ? 'small' : undefined}>
          {/* 接口给出的具体原因 */}
          {error && <div style={{ overflowWrap: 'anywhere' }}>{error}</div>}
          {/* 常见原因说明 */}
          <div className="muted">文件可能尚未下载完整：请在项目目录执行 <span className="mono">git lfs pull</span> 后刷新页面。</div>
        </div>
      }
    />
  );
}

/** 研究用途标签（例如“流程测试”） */
export function PurposeTag({ purpose }: { purpose: Purpose | null }) {
  if (!purpose) return null; // 未登记用途时不显示
  const warn = purpose.severity === 'warning'; // 警示色还是普通色
  return (
    <Tooltip title={purpose.banner_zh}>
      <span className="pill" style={{ background: warn ? '#FFF0D6' : '#E6EEF0', color: warn ? '#7A4100' : '#0A4350' }}>
        {purposeShort(purpose.analysis_purpose)}
      </span>
    </Tooltip>
  );
}

/** 研究类型标签：只对已知类型显示中文，其余不显示 */
export function KindTag({ kind }: { kind: string | null | undefined }) {
  if (kind === 'contract_test') return <Tag color="default">接口演示数据</Tag>; // 演示数据目录
  return null;
}

/** 卡片标题行：左侧标题，右侧补充说明 */
export function SectionHead({ title, extra }: { title: ReactNode; extra?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 17 }}>{title}</h2>
      {extra && <span className="small muted">{extra}</span>}
    </div>
  );
}
