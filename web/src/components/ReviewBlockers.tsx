// 文件用途：在禁用的复核选项旁说明待处理事项，并定位现有证据和操作入口。
import { Button, Space } from 'antd';
import { fileUrl } from '../api/client';
import type { ReviewBlocker } from '../api/types';

/** 显示本批阻塞详情，展开现有核查区域时不触发查询或复核提交。 */
export default function ReviewBlockers({ studyId, blockers, onNavigate }: {
  studyId: string; blockers: ReviewBlocker[]; onNavigate?: () => void;
}) {
  return <ul aria-label="通过前需要处理的事项" style={{ paddingLeft: 18, margin: '8px 0 4px' }}>
    {blockers.map((item) => <li key={item.title_zh} style={{ marginBottom: 10, overflowWrap: 'anywhere' }}>
      <strong>{item.title_zh}</strong>
      <div>{item.owner_zh}</div>
      <div className="small">{item.action_zh}</div>
      {item.examples.length > 0 && <div className="small muted">例如 {item.examples.join('；')}</div>}
      <Space wrap style={{ marginTop: 4 }}>
        {item.href && <Button size="small" href={item.href} onClick={onNavigate}>前往处理</Button>}
        {item.section_id && <Button size="small" onClick={() => {
          onNavigate?.();
          requestAnimationFrame(() => {
            const target = document.getElementById(item.section_id!) || document.getElementById('module-details');
            if (target instanceof HTMLDetailsElement) target.open = true;
            target?.scrollIntoView({ block: 'start' });
          });
        }}>定位核查区</Button>}
        {item.file_key && <Button size="small" href={fileUrl(studyId, item.file_key)}>下载完整清单</Button>}
      </Space>
    </li>)}
  </ul>;
}
