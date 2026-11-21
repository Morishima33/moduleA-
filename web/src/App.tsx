// 文件用途：应用外壳。负责顶栏、路由切换、全局待办与后台任务面板，以及“有活动任务时每 3 秒轮询、任务结束后刷新页面”。
import { Badge, Button, Result, Spin } from 'antd';
import { UnorderedListOutlined } from '@ant-design/icons';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, errorText, loadSession } from './api/client';
import type { GlobalInboxEntry, Session, Task } from './api/types';
import { AppContext, type AppContextValue } from './lib/appContext';
import { hrefFor, useRoute } from './lib/route';
import HomePage from './pages/HomePage';

const StudyPage = lazy(() => import('./pages/StudyPage'));
const TaskDrawer = lazy(() => import('./components/TaskDrawer'));
const InboxDrawer = lazy(() => import('./components/InboxDrawer'));
const NewStudyModal = lazy(() => import('./components/NewStudyModal'));
const AnalysisPlanPreviewPage = lazy(() => import('./pages/AnalysisPlanPreviewPage'));
const PlanStudyCreationPage = lazy(() => import('./pages/PlanStudyCreationPage'));
const CreationSourceWorkspace = lazy(() => import('./components/CreationSourceWorkspace'));
const PlanPocketPage = lazy(() => import('./pages/PlanPocketPage'));
const SystemPipelinePage = lazy(() => import('./pages/SystemPipelinePage'));

// 任务仍在进行的状态
const ACTIVE = new Set(['queued', 'running']);

/** 应用根组件 */
export default function App() {
  const route = useRoute(); // 当前路由
  const [session, setSession] = useState<Session | null>(null); // 会话信息
  const [sessionError, setSessionError] = useState<string | null>(null); // 会话读取失败说明
  const [refreshTick, setRefreshTick] = useState(0); // 刷新信号
  const [tasksOpen, setTasksOpen] = useState<boolean | null>(null); // 首次打开才加载，随后保留抽屉筛选
  const [focusTask, setFocusTask] = useState<string | undefined>(); // 面板中默认展开的任务
  const [newStudyOpen, setNewStudyOpen] = useState(false); // 新建登记窗口
  const [inboxOpen, setInboxOpen] = useState(false); // 待办面板是否打开
  const [inbox, setInbox] = useState<{ status: 'loading' } | { status: 'ready'; items: GlobalInboxEntry[] } | { status: 'failed'; message: string }>({ status: 'loading' });
  const [inboxRetry, setInboxRetry] = useState(0);
  const [tracked, setTracked] = useState<Set<string>>(new Set()); // 正在跟踪的活动任务编号
  const [crumb, setCrumb] = useState<string | null>(null); // 顶栏位置中的研究名
  const trackedRef = useRef(tracked); // 轮询回调中读取最新值
  trackedRef.current = tracked;
  const needsFinalRefresh = useRef(false); // 只有实际跟踪过任务，结束后才补一次落盘核对。

  // 启动时读取会话（取得令牌和决定中文名）
  useEffect(() => {
    loadSession().then(setSession).catch((e) => setSessionError(errorText(e)));
  }, []);

  /** 触发一次全局刷新 */
  const bumpRefresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  // 仅打开待办时核验跨研究状态，避免争用当前页面的归档读取。
  useEffect(() => {
    if (!session || !inboxOpen) return;
    let current = true;
    setInbox({ status: 'loading' });
    api.inbox()
      .then(({ items }) => { if (current) setInbox({ status: 'ready', items }); })
      .catch((error) => { if (current) setInbox({ status: 'failed', message: errorText(error) }); });
    return () => { current = false; }; // 新刷新后，不让旧请求覆盖最新待办。
  }, [refreshTick, session, inboxOpen, inboxRetry]);

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

  // 启动、进入研究及重新回到页面时发现活动任务，避免漏掉快速完成的任务。
  useEffect(() => {
    let current = true, pending = false;
    async function recover(refresh: boolean) {
      if (document.visibilityState === 'hidden' || pending) return;
      pending = true;
      try { const r = await api.tasks({ active: true }); if (current) { trackTasks(r.items); if (refresh) bumpRefresh(); } }
      catch { /* 保留现有页面，下一次聚焦重试。 */ }
      finally { pending = false; }
    }
    // 新页面自身已经读取当前归档；发现任务不再立即重发整套页面请求。
    void recover(false);
    const refocus = () => { void recover(true); };
    window.addEventListener('focus', refocus);
    document.addEventListener('visibilitychange', refocus);
    return () => { current = false; window.removeEventListener('focus', refocus); document.removeEventListener('visibilitychange', refocus); };
  }, [trackTasks, bumpRefresh, route.studyId]);

  // 串行轻量轮询；终态刷新并补一次核对，不在每次轮询重载研究归档。
  useEffect(() => {
    if (tracked.size === 0) return;
    let current = true, pending = false;
    async function poll() {
      if (pending) return;
      pending = true;
      try {
        const r = await api.tasks({ active: true });
        if (!current) return;
        const still = new Set(r.items.map((t) => t.task_id));
        const ended = new Set([...trackedRef.current].filter((id) => !still.has(id)));
        if (ended.size) {
          setTracked(old => new Set([...old].filter(id => !ended.has(id))));
          bumpRefresh();
        }
      } catch { /* 网络失败不终止跟踪，也不把失败当作完成。 */ }
      finally { pending = false; }
    }
    void poll();
    const timer = window.setInterval(poll, 3000);
    return () => { current = false; window.clearInterval(timer); };
  }, [tracked, bumpRefresh]);

  // 终态清空跟踪后再核对一次，覆盖任务落盘与页面读取的边界。
  useEffect(() => {
    if (tracked.size) { needsFinalRefresh.current = true; return; }
    if (!needsFinalRefresh.current) return;
    const timer = window.setTimeout(() => { needsFinalRefresh.current = false; bumpRefresh(); }, 1000);
    return () => window.clearTimeout(timer);
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
      openNewStudy: () => setNewStudyOpen(true),
      trackTasks,
      setCrumb,
      currentStudyId: route.page === 'study' || route.page === 'plan-pockets' ? route.studyId || null : null,
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
              {inbox.status === 'ready' && <Badge count={inbox.items.length} showZero color="#C76E00" style={{ marginLeft: 6 }} />}
            </Button>
            {route.page === 'study' && <Button disabled={!session?.capabilities.create_study} onClick={() => setNewStudyOpen(true)}>新建研究</Button>}
            {route.page === 'study' && route.moduleId === 'A06_PREP' && <Button href={hrefFor({page: 'plan-pockets', studyId: route.studyId})}>新版口袋核查</Button>}
            {/* 后台任务入口；有活动任务时显示数量 */}
            <Button icon={<UnorderedListOutlined />} onClick={() => openTasks()}>
              后台任务
              {tracked.size > 0 && <Badge count={tracked.size} color="#1D5FB8" style={{ marginLeft: 6 }} />}
            </Button>
          </div>
        </div>
      </header>

      {/* 首页登记目录是只读入口，可与会话并行。其他页面仍等待会话就绪。 */}
      <Suspense fallback={<div style={{ padding: 80, textAlign: 'center' }}><Spin /> 正在加载页面…</div>}>
      {!session && route.page !== 'home' ? (
        <div style={{ padding: 80, textAlign: 'center' }}><Spin tip="正在连接本机服务…"><div style={{ height: 40 }} /></Spin></div>
      ) : route.page === 'parameters-preview' ? (
        <AnalysisPlanPreviewPage />
      ) : route.page === 'new-plan-study' ? (
        <PlanStudyCreationPage />
      ) : route.page === 'creation-sources' && route.studyId ? (
        <CreationSourceWorkspace key={route.studyId} studyId={route.studyId} initialTarget={route.sourceSection??'disease'}/>
      ) : route.page === 'system-pipeline' && route.studyId ? (
        <SystemPipelinePage key={route.studyId} studyId={route.studyId} />
      ) : route.page === 'plan-pockets' && route.studyId ? (
        <PlanPocketPage key={route.studyId} studyId={route.studyId} />
      ) : route.page === 'study' && route.studyId ? (
        <StudyPage key={route.studyId} studyId={route.studyId} moduleId={route.moduleId} runId={route.runId} />
      ) : (
        <HomePage />
      )}
      </Suspense>

      <Suspense fallback={null}>
      {/* 后台任务抽屉 */}
      {tasksOpen !== null && <TaskDrawer
        open={tasksOpen}
        focusTaskId={focusTask}
        onClose={() => setTasksOpen(false)}
        studyId={ctx.currentStudyId}
        onTaskEnded={bumpRefresh}
        onActive={trackTasks}
      />}
      {newStudyOpen && <NewStudyModal open={newStudyOpen} onClose={() => setNewStudyOpen(false)} onCreated={bumpRefresh} />}
      {/* 全局待办抽屉 */}
      {inboxOpen && <InboxDrawer
        open={inboxOpen}
        items={inbox.status === 'ready' ? inbox.items : null}
        error={inbox.status === 'failed' ? inbox.message : undefined}
        onRetry={() => setInboxRetry((n) => n + 1)}
        onClose={() => setInboxOpen(false)}
      />}
      </Suspense>
    </AppContext.Provider>
  );
}
