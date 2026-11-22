// 文件用途：A01 与 A02 一次提交的复核弹窗（POST reviews:batch）。共用复核人，两项分别填写决定和意见；
// 已通过的一项可选择“保留原决定”（preserve），不必重复签署。任一项冲突时整批不保存。
import { Alert, App as AntApp, Input, Modal, Radio, Skeleton } from 'antd';
import { useEffect, useState } from 'react';
import { ApiError, api, errorText } from '../api/client';
import type { Decision, ModuleView, Task } from '../api/types';
import { decisionLabel, useApp } from '../lib/appContext';
import { StatusPill } from './common';
import DecisionPicker from './DecisionPicker';
import ReviewBlockers from './ReviewBlockers';

/** 单个模块在批量表单中的填写内容 */
interface Entry { action: 'decide' | 'preserve'; decision?: Decision; note: string }

/** 组件参数 */
interface Props {
  open: boolean; // 是否打开
  studyId: string; // 研究编号
  current: ModuleView; // 当前模块
  otherId: string; // 一起提交的另一个模块
  onClose: () => void; // 关闭
  onSaved: (task: Task | null) => void; // 保存成功
  onStale: () => void; // 版本冲突
}

/** 批量复核弹窗 */
export default function BatchReviewModal({ open, studyId, current, otherId, onClose, onSaved, onStale }: Props) {
  const { session } = useApp(); // 决定中文名
  const { message } = AntApp.useApp(); // 轻提示
  const [other, setOther] = useState<ModuleView | null>(null); // 另一个模块的数据
  const [loadError, setLoadError] = useState<string | null>(null); // 读取失败
  const [reviewer, setReviewer] = useState(''); // 共用复核人
  const [entries, setEntries] = useState<Record<string, Entry>>({}); // 两项的填写内容
  const [saving, setSaving] = useState(false); // 是否提交中
  const [error, setError] = useState<string | null>(null); // 提交错误

  // 打开时读取另一个模块，并按“已通过则默认保留”初始化
  useEffect(() => {
    if (!open) return;
    setError(null);
    setOther(null);
    api.module(studyId, otherId)
      .then((v) => {
        setOther(v);
        setLoadError(null);
        const init = (m: ModuleView): Entry => ({ action: m.review.already_approved ? 'preserve' : 'decide', note: '' }); // 初始值
        setEntries({ [current.module.module_id]: init(current), [otherId]: init(v) });
      })
      .catch((e) => setLoadError(errorText(e)));
  }, [open, studyId, otherId, current]);

  // 两个模块按编号排序（A01 在前）
  const views = other ? [current, other].sort((a, b) => a.module.module_id.localeCompare(b.module.module_id)) : [];

  /** 更新某一项 */
  const patch = (mid: string, p: Partial<Entry>) => setEntries((old) => ({ ...old, [mid]: { ...old[mid], ...p } }));

  /** 提交 */
  const submit = async () => {
    // 前端只做必填检查，合法性以接口为准
    if (!reviewer.trim()) return setError('请填写复核人');
    for (const v of views) {
      const e = entries[v.module.module_id];
      if (e.action === 'decide' && !e.decision) return setError(`请为 ${v.module.module_id} 选择决定`);
      if (e.action === 'decide' && !e.note.trim()) return setError(`请填写 ${v.module.module_id} 的意见`);
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        reviewer: reviewer.trim(),
        entries: Object.fromEntries(views.map((v) => {
          const e = entries[v.module.module_id]; // 该项填写内容
          return [v.module.module_id, {
            run_id: v.review.run_id || '', // 运行编号
            expected_review_id: v.review.expected_review_id, // 并发保护
            action: e.action,
            decision: e.action === 'decide' ? (e.decision as Decision) : ('' as const),
            note: e.note.trim(),
          }];
        })),
      };
      const res = await api.batchReview(studyId, body);
      if (res.task?.state === 'failed') message.warning(res.message_zh);
      else message.success(res.message_zh);
      onClose();
      onSaved(res.task); // 刷新；有任务时打开任务面板
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_VERSION') {
        message.warning('状态已更新，已自动刷新，请核对后重新提交。');
        onClose();
        onStale();
      } else {
        setError(errorText(e));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title={`${views.map((v) => v.module.module_id).join(' 与 ') || current.module.module_id + ' 与 ' + otherId} 一起提交复核`}
      okText="一次保存两项决定" cancelText="取消" onOk={submit} onCancel={onClose} confirmLoading={saving}
      okButtonProps={{ disabled: !other }} width="min(880px, 96vw)" destroyOnClose>
      <p className="small muted" style={{ marginTop: 0 }}>两项分别留下独立复核记录；任一项版本冲突或决定不合法时整批不保存。两项都通过后，后台会自动生成交集并停在交集复核关口。</p>
      {loadError && <Alert type="error" showIcon message={loadError} />}
      {!other && !loadError ? (
        <Skeleton active />
      ) : other && (
        <>
          {/* 共用复核人 */}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14, maxWidth: 360 }}>
            <span>复核人（两项共用）</span>
            <Input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="填写姓名" maxLength={60} />
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))', gap: 14 }}>
            {views.map((v) => {
              const mid = v.module.module_id; // 模块编号
              const e = entries[mid] || { action: 'decide', note: '' }; // 填写内容
              const allowed = new Set(v.review.allowed_decisions); // 允许的决定
              return (
                <div key={mid} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                    <strong>{mid} · {v.module.title_zh}</strong>
                    <StatusPill code={v.state.code} label={v.state.label_zh} />
                  </div>
                  {/* 已通过的一项可保留 */}
                  {v.review.already_approved && (
                    <Radio.Group value={e.action} onChange={(ev) => patch(mid, { action: ev.target.value })}>
                      <Radio value="preserve">保留已通过的决定</Radio>
                      <Radio value="decide">重新决定</Radio>
                    </Radio.Group>
                  )}
                  {e.action === 'preserve' ? (
                    <div className="small muted">保留当前决定：{decisionLabel(session, v.review.current?.decision)}（{v.review.current?.reviewer}）</div>
                  ) : !v.review.can_review ? (
                    <Alert type="info" showIcon message={`${mid} 当前不能复核：${v.state.label_zh}`} />
                  ) : (
                    <>
                      <DecisionPicker value={e.decision} onChange={(d) => patch(mid, { decision: d })} blockedReason={v.review.blockers?.length ? null : v.review.blocked_reason_zh}
                        options={(['approved', 'rejected', 'pending'] as Decision[]).map((d) => ({ value: d, label: decisionLabel(session, d), disabled: !allowed.has(d) }))} />
                      {!!v.review.blockers?.length && <ReviewBlockers studyId={studyId} blockers={v.review.blockers.map(item =>
                        mid === current.module.module_id || item.href ? item : { ...item, section_id: null, href: `#/studies/${studyId}/${mid}` }
                      )} onNavigate={onClose} />}
                      <Input.TextArea rows={3} value={e.note} onChange={(ev) => patch(mid, { note: ev.target.value })} placeholder={`${mid} 的复核意见`} maxLength={2000} />
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} />}
    </Modal>
  );
}
