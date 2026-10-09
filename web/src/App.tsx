// 文件用途：应用外壳。负责顶栏、路由切换、全局待办与后台任务面板，以及“有活动任务时每 3 秒轮询、任务结束后刷新页面”。
import { Badge, Button, Result, Spin } from 'antd';
import { UnorderedListOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, errorText, loadSession } from './api/client';
import type { GlobalInboxEntry, Session, Task } from './api/types';
import { AppContext, type AppContextValue } from './lib/appContext';
import { hrefFor, useRoute } from './lib/route';
import HomePage from './pages/HomePage';
import StudyPage from './pages/StudyPage';
import TaskDrawer from './components/TaskDrawer';
import InboxDrawer from './components/InboxDrawer';

// 任务仍在进行的状态
const ACTIVE = new Set(['queued', 'running']);

/** 应用根组件 */
export default function App() {
  const route = useRoute(); // 当前路由
  const [session, setSession] = useState<Session | null>(null); // 会话信息
  const [sessionError, setSessionError] = useState<string | null>(null); // 会话读取失败说明
  const [refreshTick, setRefreshTick] = useState(0); // 刷新信号
  const [tasksOpen, setTasksOpen] = useState(false); // 任务面板是否打开
  const [focusTask, setFocusTask] = useState<string | undefined>(); // 面板中默认展开的任务
  const [inboxOpen, setInboxOpen] = useState(false); // 待办面板是否打开
  const [inbox, setInbox] = useState<GlobalInboxEntry[]>([]); // 全局待办
  const [tracked, setTracked] = useState<Set<string>>(new Set()); // 正在跟踪的活动任务编号
  const [crumb, setCrumb] = useState<string | null>(null); // 顶栏位置中的研究名
  const trackedRef = useRef(tracked); // 轮询回调中读取最新值
  trackedRef.current = tracked;

  // 启动时读取会话（取得令牌和决定中文名）
  useEffect(() => {
    loadSession().then(setSession).catch((e) => setSessionError(errorText(e)));
  }, []);

  /** 触发一次全局刷新 */
  const bumpRefresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  // 每次刷新信号变化时更新全局待办数
  useEffect(() => {
    api.inbox().then((r) => setInbox(r.items)).catch(() => undefined); // 待办读取失败不影响页面
  }, [refreshTick]);

  /** 登记活动任务；只跟踪排队中或运行中的任务 */
  const trackTasks = useCallback((tasks: (Task | null | undefined)[]) => {
    const ids = tasks.filter((t): t is Task => !!t && ACTIVE.has(t.state)).map((t) => t.task_id); // 活动任务编号
    if (!ids.length) return; // 没有新任务
    setTracked((old) => {
      if (ids.every((id) => old.has(id))) return old; // 已全部在跟踪
      const next = new Set(old); // 复制后加入新编号
      ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  // 有活动任务时每 3 秒轮询；发现任务结束就刷新当前页面
  useEffect(() => {
    if (tracked.size === 0) return; // 没有活动任务时不轮询
    const timer = window.setInterval(async () => {
      try {
        const r = await api.tasks({ active: true }); // 读取全部活动任务
        const still = new Set(r.items.map((t) => t.task_id)); // 仍在进行的编号
        const ended = [...trackedRef.current].filter((id) => !still.has(id)); // 已结束的编号
        if (ended.length) {
          setTracked(new Set([...trackedRef.current].filter((id) => still.has(id)))); // 移除已结束任务
          bumpRefresh(); // 刷新研究与模块数据
        }
      } catch {
        // 轮询失败时下一轮再试
      }
    }, 3000);
    return () => window.clearInterval(timer); // 清理定时器
  }, [tracked, bumpRefresh]);

  /** 打开任务面板 */
  const openTasks = useCallback((taskId?: string) => {
    setFocusTask(taskId); // 记下要展开的任务
    setTasksOpen(true); // 打开抽屉
  }, []);

  // 上下文内容
  const ctx: AppContextValue = useMemo(
    () => ({
      session,
      refreshTick,
      bumpRefresh,
      openTasks,
      openInbox: () => setInboxOpen(true),
      trackTasks,
      setCrumb,
      currentStudyId: route.page === 'study' ? route.studyId || null : null,
    }),
    [session, refreshTick, bumpRefresh, openTasks, trackTasks, route.page, route.studyId],
  );

  // 会话读取失败：服务未启动等
  if (sessionError) {
    return (
      <Result
        status="warning"
        title="无法连接本机工作台服务"
        subTitle={sessionError}
        extra={<Button type="primary" onClick={() => window.location.reload()}>重新连接</Button>}
      />
    );
  }

  return (
    <AppContext.Provider value={ctx}>
      {/* 顶栏：品牌、位置、待办、后台任务 */}
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/" style={{ color: '#17212B', textDecoration: 'none' }}>
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="#0F5E6E" strokeWidth="1.8" aria-hidden="true">
              <circle cx="7" cy="8" r="3" />
              <circle cx="19" cy="8" r="3" />
              <circle cx="13" cy="19" r="3" />
              <path d="M9.5 9.8 11.4 16.4M16.5 9.8 14.6 16.4M10 8h6" />
            </svg>
            <span>ModuleA 研究工作台</span>
          </a>
          <nav className="crumbs" aria-label="位置">
            <a href={hrefFor({ page: 'home' })}>研究列表</a>
            {/* 研究页时显示研究名 */}
            {route.page === 'study' && crumb && (
              <>
                <span aria-hidden="true">/</span>
                <span className="here">{crumb}</span>
              </>
            )}
          </nav>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {/* 全局待办入口 */}
            <Button onClick={() => setInboxOpen(true)}>
              待你处理
              <Badge count={inbox.length} showZero color="#C76E00" style={{ marginLeft: 6 }} />
            </Button>
            {/* 后台任务入口；有活动任务时显示数量 */}
            <Button icon={<UnorderedListOutlined />} onClick={() => openTasks()}>
              后台任务
              {tracked.size > 0 && <Badge count={tracked.size} color="#1D5FB8" style={{ marginLeft: 6 }} />}
            </Button>
          </div>
        </div>
      </header>

      {/* 页面主体：会话就绪后再渲染 */}
      {!session ? (
        <div style={{ padding: 80, textAlign: 'center' }}><Spin tip="正在连接本机服务…"><div style={{ height: 40 }} /></Spin></div>
      ) : route.page === 'study' && route.studyId ? (
        <StudyPage key={route.studyId} studyId={route.studyId} moduleId={route.moduleId} runId={route.runId} />
      ) : (
        <HomePage />
      )}

      {/* 后台任务抽屉 */}
      <TaskDrawer
        open={tasksOpen}
        focusTaskId={focusTask}
        onClose={() => setTasksOpen(false)}
        studyId={ctx.currentStudyId}
        onTaskEnded={bumpRefresh}
        onActive={trackTasks}
      />
      {/* 全局待办抽屉 */}
      <InboxDrawer open={inboxOpen} items={inbox} onClose={() => setInboxOpen(false)} />
    </AppContext.Provider>
  );
}
