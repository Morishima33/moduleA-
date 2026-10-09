// 文件用途：复核决定选择器（三个大号单选项）。可选项由接口的 allowed_decisions 决定，“通过”被禁用时显示 blocked_reason_zh。
import { useId } from 'react';
import type { Decision } from '../api/types';

/** 决定选择器：三个大号单选项；“通过”被禁用时显示原因 */
export default function DecisionPicker({ value, onChange, options, blockedReason }: {
  value?: Decision; onChange?: (v: Decision) => void; options: { value: Decision; label: string; disabled: boolean }[]; blockedReason?: string | null;
}) {
  const name = useId(); // 每组单选框独立的名称
  return (
    <div role="radiogroup" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {options.map((o) => (
        <div key={o.value}>
          <label className={'decision' + (value === o.value ? ' on' : '') + (o.disabled ? ' disabled' : '')}>
            <input type="radio" name={name} checked={value === o.value} disabled={o.disabled}
              onChange={() => onChange?.(o.value)} style={{ width: 16, height: 16, margin: 0 }} />
            {o.label}
          </label>
          {/* “通过”不可选时说明原因 */}
          {o.disabled && o.value === 'approved' && blockedReason && <div className="tiny" style={{ color: '#4E3780', margin: '4px 2px 0' }}>{blockedReason}</div>}
        </div>
      ))}
    </div>
  );
}
