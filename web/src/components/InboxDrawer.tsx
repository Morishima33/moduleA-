// 文件用途：全局待办收件箱（抽屉）。按研究分组列出 GET /inbox 返回的待办，点击直接跳到对应模块。
import { Alert, Drawer, Empty } from 'antd';
import type { GlobalInboxEntry } from '../api/types';
import { hrefFor } from '../lib/route';
import { StatusPill } from './common';

/** 全局待办抽屉 */
export default function InboxDrawer({ open, items, onClose }: { open: boolean; items: GlobalInboxEntry[]; onClose: () => void }) {
  // 按研究分组，保持接口给出的顺序
  const groups: { id: string; title: string; entries: GlobalInboxEntry[] }[] = [];
  for (const it of items) {
    let g = groups.find((x) => x.id === it.study_id); // 找已有分组
    if (!g) {
      g = { id: it.study_id, title: it.study_title_zh, entries: [] }; // 新建分组
      groups.push(g);
    }
    g.entries.push(it); // 加入条目
  }
  return (
    <Drawer title={`待你处理（${items.length}）`} open={open} onClose={onClose} width={460}>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} message="“等待”表示还有资料或确认事项需要处理；不会因继续等待而自动完成。后台是否正在计算，请查看“后台任务”的运行状态。" />
      {!items.length ? (
        <Empty description="目前没有需要你处理的事项" />
      ) : (
        groups.map((g) => (
          <div key={g.id} style={{ marginBottom: 18 }}>
            {/* 研究名 */}
            <div style={{ fontWeight: 700, marginBottom: 8 }}>{g.title}</div>
            {g.entries.map((e) => (
              // 每条待办都是跳转链接
              <a
                key={e.module_id}
                href={hrefFor({ page: 'study', studyId: e.study_id, moduleId: e.module_id })}
                onClick={onClose}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', border: '1px solid #DCE1E5', borderRadius: 8, marginBottom: 8, color: '#17212B', textDecoration: 'none' }}
              >
                <span className="mono small muted" style={{ minWidth: 86 }}>{e.module_id}</span>
                <span style={{ flex: 1, minWidth: 0 }}>{e.text_zh}</span>
                <StatusPill code={e.code} label={e.label_zh} />
              </a>
            ))}
          </div>
        ))
      )}
    </Drawer>
  );
}
