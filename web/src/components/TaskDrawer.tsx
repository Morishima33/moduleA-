// 文件用途：后台任务面板（抽屉）。列出任务、查看增量日志、取消与重试；有活动任务时每 3 秒刷新列表与日志。
import { Alert, App as AntApp, Button, Drawer, Empty, Progress, Segmented, Space, Spin } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { Task } from '../api/types';
import { fmtTime } from '../lib/format';
import { taskColor } from '../lib/theme';

// 进行中的任务状态
const ACTIVE = new Set(['queued', 'running']);

/** 组件参数 */
interface Props {
  open: boolean; // 是否打开
  focusTaskId?: string; // 默认展开日志的任务
  onClose: () => void; // 关闭回调
  studyId: string | null; // 当前研究（用于“仅本研究”筛选）
  onTaskEnded: () => void; // 发现任务结束时通知外层刷新
  onActive: (tasks: Task[]) => void; // 把活动任务交给外层跟踪
}

/** 后台任务抽屉 */
export default function TaskDrawer({ open, focusTaskId, onClose, studyId, onTaskEnded, onActive }: Props) {
  const { message } = AntApp.useApp(); // 轻提示
  const [scope, setScope] = useState<'study' | 'all'>('study'); // 筛选范围
  const [items, setItems] = useState<Task[]>([]); // 任务列表
  const [loading, setLoading] = useState(false); // 是否加载中
  const [error, setError] = useState<string | null>(null); // 加载错误
  const [logTask, setLogTask] = useState<string | undefined>(); // 正在查看日志的任务
  const prevActive = useRef<Set<string>>(new Set()); // 上一次的活动任务编号

  // 打开时默认展开指定任务的日志
  useEffect(() => {
    if (open && focusTaskId) setLogTask(focusTaskId);
  }, [open, focusTaskId]);

  // 没有当前研究时只能看全部
  const effectiveScope = studyId ? scope : 'all';

  /** 读取任务列表 */
  const load = useCallback(async () => {
    try {
      const r = await api.tasks({ study: effectiveScope === 'study' ? studyId || undefined : undefined }); // 按范围读取
      setItems(r.items); // 更新列表
      setError(null); // 清除错误
      const active = r.items.filter((t) => ACTIVE.has(t.state)); // 当前活动任务
      const nowActive = new Set(active.map((t) => t.task_id)); // 活动编号集合
      const ended = [...prevActive.current].some((id) => !nowActive.has(id)); // 是否有任务刚结束
      prevActive.current = nowActive; // 记下本次结果
      if (ended) onTaskEnded(); // 通知外层刷新研究
      onActive(active); // 交给外层跟踪
    } catch (e) {
      setError(errorText(e)); // 显示错误
    } finally {
      setLoading(false); // 结束加载状态
    }
  }, [effectiveScope, studyId, onTaskEnded, onActive]);

  // 打开或切换范围时读取一次
  useEffect(() => {
    if (!open) return; // 关闭时不读取
    setLoading(true);
    load();
  }, [open, load]);

  // 有活动任务时每 3 秒刷新列表
  const hasActive = items.some((t) => ACTIVE.has(t.state));
  useEffect(() => {
    if (!open || !hasActive) return; // 没有活动任务时不轮询
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [open, hasActive, load]);

  /** 取消任务 */
  const cancel = async (t: Task) => {
    try {
      await api.cancelTask(t.task_id); // 请求取消
      message.success('已请求取消任务');
      load(); // 刷新列表
    } catch (e) {
      message.error(errorText(e));
    }
  };

  /** 重试任务 */
  const retry = async (t: Task) => {
    try {
      const r = await api.retryTask(t.task_id); // 请求重试
      message.success(r.created ? '已重新排队' : '已有同类任务在进行，未重复创建');
      setLogTask(r.task.task_id); // 展开新任务日志
      onActive([r.task]); // 交给外层跟踪
      load();
    } catch (e) {
      message.error(errorText(e));
    }
  };

  return (
    <Drawer title="后台任务" open={open} onClose={onClose} width={560} styles={{ body: { paddingTop: 12 } }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="small muted">联网获取、STRING 查询、R 富集、结构准备、对接和报告生成都在后台排队运行；网页在计算期间照常可用。</div>
        {/* 范围切换：仅本研究 / 全部 */}
        {studyId && (
          <Segmented
            value={scope}
            onChange={(v) => setScope(v as 'study' | 'all')}
            options={[{ label: '仅本研究', value: 'study' }, { label: '全部研究', value: 'all' }]}
          />
        )}
        {error && <Alert type="error" showIcon message={error} />}
        {loading && !items.length ? (
          <Spin />
        ) : !items.length ? (
          <Empty description="当前没有后台任务" />
        ) : (
          items.map((t) => (
            <TaskCard
              key={t.task_id}
              task={t}
              showLog={logTask === t.task_id}
              onToggleLog={() => setLogTask(logTask === t.task_id ? undefined : t.task_id)}
              onCancel={() => cancel(t)}
              onRetry={() => retry(t)}
            />
          ))
        )}
      </Space>
    </Drawer>
  );
}

/** 单个任务卡片：状态、类型、时间、说明/错误、进度与操作 */
function TaskCard({ task, showLog, onToggleLog, onCancel, onRetry }: { task: Task; showLog: boolean; onToggleLog: () => void; onCancel: () => void; onRetry: () => void }) {
  const color = taskColor(task.state); // 状态配色
  const active = ACTIVE.has(task.state); // 是否进行中
  const canRetry = ['failed', 'cancelled', 'interrupted'].includes(task.state); // 失败/取消/中断可重试
  return (
    <div style={{ border: '1px solid #DCE1E5', borderRadius: 10, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        {/* 状态胶囊 */}
        <span className="pill" style={{ background: color.bg, color: color.fg }}>{task.state_zh}</span>
        {/* 任务类型 */}
        <strong style={{ fontSize: 14 }}>{task.kind_zh}</strong>
        <span className="tiny muted mono">{task.task_id}</span>
      </div>
      {/* 时间信息 */}
      <div className="tiny muted">
        创建 {fmtTime(task.created_at)}
        {task.started_at && <> · 开始 {fmtTime(task.started_at)}</>}
        {task.finished_at && <> · 结束 {fmtTime(task.finished_at)}</>}
        {task.requested_by && <> · 发起：{task.requested_by}</>}
      </div>
      {/* 进度 */}
      {task.progress && (
        <div>
          <div className="small">{task.progress.step_zh}（第 {task.progress.done} 步 / 共 {task.progress.total} 步）</div>
          <Progress percent={task.progress.total ? Math.round((task.progress.done / task.progress.total) * 100) : 0} size="small" showInfo={false} />
        </div>
      )}
      {/* 说明与错误：失败原因如实显示 */}
      {task.message_zh && <div className="small">{task.message_zh}</div>}
      {task.error_zh && <Alert type="error" showIcon message="失败原因" description={<span style={{ overflowWrap: 'anywhere' }}>{task.error_zh}</span>} />}
      {/* 操作按钮 */}
      <Space wrap>
        <Button size="small" onClick={onToggleLog}>{showLog ? '收起日志' : '查看日志'}</Button>
        {active && <Button size="small" danger onClick={onCancel}>取消任务</Button>}
        {canRetry && <Button size="small" type="primary" onClick={onRetry}>重试</Button>}
      </Space>
      {/* 增量日志 */}
      {showLog && <TaskLog taskId={task.task_id} active={active} />}
    </div>
  );
}

/** 增量日志：按 offset 逐段读取，任务进行中每 3 秒追加 */
function TaskLog({ taskId, active }: { taskId: string; active: boolean }) {
  const [text, setText] = useState(''); // 已读取的日志
  const [error, setError] = useState<string | null>(null); // 读取错误
  const offset = useRef(0); // 下一次读取的位置
  const boxRef = useRef<HTMLPreElement>(null); // 日志框，用于滚到底部

  /** 读取新增部分 */
  const busy = useRef(false); // 是否正在读取（避免并发读取造成重复追加）
  const wasActive = useRef(active); // 上一次是否进行中
  const pull = useCallback(async () => {
    if (busy.current) return; // 上一次读取尚未结束
    busy.current = true;
    try {
      // 连续读取直到没有新内容（单次最多 64KB）
      for (let i = 0; i < 20; i++) {
        const r = await api.taskLog(taskId, offset.current); // 从当前位置读取
        if (r.text) setText((old) => old + r.text); // 追加文本
        const moved = r.next_offset > offset.current; // 是否前进
        offset.current = r.next_offset; // 更新位置
        if (!moved || !r.text) break; // 没有更多内容
      }
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      busy.current = false; // 允许下一次读取
    }
  }, [taskId]);

  // 首次展开时读取
  useEffect(() => {
    offset.current = 0; // 换任务时从头读
    setText('');
    pull();
  }, [pull]);

  // 进行中时轮询（结束后再读一次，补齐最后的输出）
  useEffect(() => {
    const ended = wasActive.current && !active; // 刚从进行中变为结束
    wasActive.current = active; // 记下本次状态
    if (ended) pull(); // 结束时补读一次
    if (!active) return; // 已结束不再轮询
    const timer = window.setInterval(pull, 3000);
    return () => window.clearInterval(timer);
  }, [active, pull]);

  // 有新内容时滚到底部
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [text]);

  return (
    <div>
      {error && <Alert type="warning" showIcon message={error} style={{ marginBottom: 6 }} />}
      <pre className="log-box" ref={boxRef}>{text || '（暂无日志输出）'}</pre>
    </div>
  );
}
