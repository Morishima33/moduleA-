// 文件用途：显示新版A06准备的整体复核资格；只读，不提交复核或启动计算。
import { Alert, Button, Tag } from 'antd';
import { api } from '../api/client';
import type { ReferenceQualificationInfo, ReferenceReviewGate, ReferenceReviewPacket } from '../api/types';

/** 将服务端资格结果用中文卡片呈现，前端不推算资格。 */
export default function ReferenceQualification({ studyId, info, packet, gate }: { studyId: string; info: ReferenceQualificationInfo; packet?: ReferenceReviewPacket | null; gate?: ReferenceReviewGate | null }) {
  if (!info.supported) return null;
  const good = info.qualified && info.can_enter_review;
  return (
    <section className="card" id="a06-reference-qualification" aria-label="A06整体复核资格">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 17 }}>A06_PREP 整体复核资格</h2>
        <Tag color={good ? 'green' : 'orange'}>{good ? '可进入人工复核' : '正式复核通过尚未开放'}</Tag>
      </div>
      <Alert
        type={good ? 'success' : 'warning'}
        showIcon
        message={info.reason_zh}
        description={<span>已核对文件 {info.checked_files ?? '—'} 项；当前评分组合 {info.scored_pairs ?? '—'}；资格核查不会自动批准或启动评分。</span>}
      />
      {packet?.supported && <div className="small muted" style={{ marginTop: 8 }}>
        复核材料包：第 {packet.version || '—'}；已核对 {packet.checked_files} 件文件；参考复核仍需人工决定。
        <div style={{ marginTop: 8 }}><Button size="small" href={api.a06ReviewPacketExport(studyId)}>下载整体复核材料包 JSON</Button></div>
      </div>}
      {gate?.supported && <Alert style={{ marginTop: 10 }} type={gate.can_submit ? 'info' : 'warning'} showIcon message={gate.reason_zh}
        description={`当前允许的复核决定：${gate.allowed_decisions.length ? gate.allowed_decisions.map(d => ({approved:'通过',rejected:'退回',pending:'暂存'}[d] || d)).join('、') : '无'}；阻断项 ${gate.blockers.length} 条。`} />}
      {!!info.blockers.length && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 22 }}>
          {info.blockers.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </section>
  );
}
