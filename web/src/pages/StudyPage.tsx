// 文件用途：研究工作页。顶部用途横幅与下一步提示；左侧按分组的模块导航；中间模块页；右侧固定复核栏。
// 窄屏时导航折叠为抽屉，复核栏堆叠在“重点核对”之后，不出现横向滚动。
import { Alert, App as AntApp, Button, Drawer, Dropdown, Grid, Result, Skeleton } from 'antd';
import { MenuOutlined, MoreOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useState } from 'react';
import { ApiError, api, errorText } from '../api/client';
import type { ModuleView, StudyView, Task } from '../api/types';
import { ArchiveAlert, KindTag, ProgressSegs, StatusPill } from '../components/common';
import ManageStudyModal from '../components/ManageStudyModal';
import { DownstreamCard } from '../components/ModuleSections';
import ModulePage from '../components/ModulePage';
import ReviewPanel from '../components/ReviewPanel';
import { useApp } from '../lib/appContext';
import { hrefFor, navigate } from '../lib/route';
import { LEGEND, stateStyle } from '../lib/theme';

/** 研究工作页 */
export default function StudyPage({ studyId, moduleId, runId }: { studyId: string; moduleId?: string; runId?: string }) {
  const app = useApp(); // 全局上下文
  const { message, modal } = AntApp.useApp(); // 轻提示与确认框（跟随主题）
  const screens = Grid.useBreakpoint(); // 当前屏幕宽度档位
  const wide = !!screens.xl; // ≥1200：三栏
  const medium = !!screens.lg; // ≥992：导航常驻
  const [study, setStudy] = useState<StudyView | null>(null); // 研究页数据
  const [studyError, setStudyError] = useState<ApiError | null>(null); // 研究读取失败
  const [view, setView] = useState<ModuleView | null>(null); // 模块页数据
  const [moduleError, setModuleError] = useState<ApiError | null>(null); // 模块读取失败
  const [navOpen, setNavOpen] = useState(false); // 窄屏导航抽屉
  const [manage, setManage] = useState<'trash' | 'restore' | null>(null); // 研究管理对话框
  const [reloadTick, setReloadTick] = useState(0); // 本页局部刷新信号

  // 当前模块：地址指定 > 下一步 > 第一个模块
  const firstModule = study?.nav[0]?.modules[0]?.module_id;
  const mid = moduleId || study?.next_step?.module_id || firstModule;

  /** 重新加载研究与模块 */
  const reload = useCallback(() => setReloadTick((n) => n + 1), []);

  // 读取研究页
  useEffect(() => {
    api.study(studyId)
      .then((s) => {
        setStudy(s); // 更新研究数据
        setStudyError(null);
        app.trackTasks(s.active_tasks); // 跟踪活动任务
      })
      .catch((e) => setStudyError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', errorText(e))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId, app.refreshTick, reloadTick]);

  // 顶栏显示研究名
  const { setCrumb } = app;
  useEffect(() => {
    setCrumb(study?.study.title_zh || null);
  }, [study?.study.title_zh, setCrumb]);

  // 读取模块页
  useEffect(() => {
    if (!mid) return; // 研究尚未加载
    api.module(studyId, mid, runId)
      .then((v) => {
        setView(v); // 更新模块数据
        setModuleError(null);
        app.trackTasks(v.tasks); // 跟踪本模块任务
      })
      .catch((e) => {
        setView(null);
        setModuleError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', errorText(e)));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId, mid, runId, app.refreshTick, reloadTick]);

  /** 复核保存成功：刷新研究与模块；有后台任务时打开任务面板 */
  const onSaved = (task: Task | null) => {
    app.bumpRefresh(); // 全局刷新（含待办数）
    if (task) {
      app.trackTasks([task]); // 跟踪新任务
      app.openTasks(task.task_id); // 打开任务面板
    }
  };

  /** 手动推进到下一人工关口 */
  const doContinue = () => {
    modal.confirm({
      title: '推进到下一人工关口',
      content: '将在后台按既定规则生成下一批结果，并停在下一个人工关口；程序不会代签任何模块。',
      okText: '开始',
      cancelText: '取消',
      onOk: async () => {
        try {
          const r = await api.continue(studyId); // 提交后台任务
          // 启动失败已有终态与原因，不能提示成功。
          if (r.task.state === 'failed') message.error(r.task.error_zh || '后台任务启动失败，请查看任务面板。');
          else message.success(r.created ? '后台任务已提交' : '已有同类任务在进行');
          app.trackTasks([r.task]);
          app.openTasks(r.task.task_id);
        } catch (e) {
          message.error(errorText(e));
        }
      },
    });
  };

  // 研究读取失败
  if (studyError && !study) {
    return (
      <div className="home">
        <Result status={studyError.status === 404 ? '404' : 'warning'} title={studyError.status === 404 ? '找不到这项研究' : '研究读取失败'} subTitle={studyError.messageZh}
          extra={<Button type="primary" href={hrefFor({ page: 'home' })}>回到研究列表</Button>} />
      </div>
    );
  }
  // 研究加载中
  if (!study) return <div className="home"><Skeleton active paragraph={{ rows: 8 }} /></div>;

  const s = study.study; // 研究信息
  const segments = study.nav.flatMap((g) => g.modules.map((m) => ({ module_id: m.module_id, code: m.code, label_zh: m.label_zh }))); // 进度分段
  const next = study.next_step; // 下一步

  // 左侧导航内容
  const navContent = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 研究概要 */}
      <div className="card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>{s.title_zh}</div>
        <div className="small muted">
          {s.herbs_zh.join('、')}{s.disease.mesh_ui ? ` · MeSH ${s.disease.mesh_ui}` : ''}
        </div>
        <ProgressSegs segments={segments} height={6} />
        <div className="small muted">{study.progress.approved} / {study.progress.total} 已通过</div>
      </div>
      {/* 模块列表 */}
      <nav className="card" aria-label="流程导航" style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {study.nav.map((g) => (
          <div key={g.group_zh}>
            <div className="nav-group">{g.group_zh}</div>
            {g.modules.map((m) => {
              const on = m.module_id === mid; // 是否当前模块
              const st = stateStyle(m.code); // 状态配色
              return (
                <a key={m.module_id} href={hrefFor({ page: 'study', studyId, moduleId: m.module_id })} onClick={() => setNavOpen(false)}
                  className={'nav-item' + (on ? ' on' : '') + (m.sub ? ' sub' : '')} aria-current={on ? 'page' : undefined} style={{ textDecoration: 'none' }}>
                  <span className="dot" style={{ background: st.dot }} aria-hidden="true" />
                  <span className="txt">
                    <span className="code">{m.module_id}</span>
                    <span className="title" style={{ fontWeight: on ? 700 : 400 }}>{m.title_zh}</span>
                  </span>
                  <StatusPill code={m.code} label={m.label_zh} />
                </a>
              );
            })}
          </div>
        ))}
      </nav>
      {/* 图例 */}
      <div className="legend">
        {LEGEND.map((l) => <span key={l.code}><i style={{ background: stateStyle(l.code).dot }} />{l.text}</span>)}
      </div>
    </div>
  );

  // 模块数据是否与当前地址一致（不一致时显示加载骨架；同一模块刷新时保留旧内容，避免闪烁）
  const viewMatches = !!view && view.module.module_id === mid && (runId ? view.run?.run_id === runId : !view.historical);
  // 复核栏与下游影响
  const reviewPanel = view && viewMatches ? (
    <ReviewPanel key={view.module.module_id + (view.run?.run_id || '')} studyId={studyId} view={view} onSaved={onSaved} onStale={reload} />
  ) : null;
  const downstream = view && viewMatches ? <DownstreamCard studyId={studyId} downstream={view.downstream} /> : null;

  // 研究管理菜单
  const menuItems = s.trashed
    ? [{ key: 'restore', label: '从回收站恢复…' }]
    : [
        { key: 'continue', label: '推进到下一人工关口（后台）' },
        { key: 'trash', label: '移入回收站…', danger: true },
      ];

  return (
    <>
      {/* 研究用途横幅（警示色） */}
      {study.purpose && (
        <div className="purpose-banner" role="note">
          <div className="inner">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M9 2 16.5 15h-15z" /><path d="M9 7v4M9 13.2v.1" /></svg>
            <strong>{study.purpose.banner_zh}</strong>
          </div>
        </div>
      )}
      <div className={'study-layout' + (wide ? '' : medium ? ' no-review' : ' narrow')}>
        {/* 左侧导航：宽屏常驻，窄屏为抽屉 */}
        {medium ? (
          <aside className="side-sticky" aria-label="流程导航">{navContent}</aside>
        ) : (
          <Drawer title="流程导航" placement="left" open={navOpen} onClose={() => setNavOpen(false)} width={300} styles={{ body: { background: '#F2F4F5', padding: 12 } }}>
            {navContent}
          </Drawer>
        )}

        {/* 中间主体 */}
        <main className="stack" style={{ minWidth: 0 }}>
          {/* 研究标题行 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
            {!medium && <Button icon={<MenuOutlined />} onClick={() => setNavOpen(true)}>流程导航</Button>}
            <h1 style={{ margin: 0, fontSize: 20, flex: '1 1 200px', minWidth: 0 }}>{s.title_zh} <KindTag kind={s.kind} /></h1>
            <Dropdown menu={{ items: menuItems, onClick: ({ key }) => (key === 'continue' ? doContinue() : setManage(key as 'trash' | 'restore')) }}>
              <Button icon={<MoreOutlined />}>研究管理</Button>
            </Dropdown>
          </div>
          {/* 回收站中：只读提示 */}
          {s.trashed && (
            <Alert type="warning" showIcon message="该研究在回收站中（只读）" description="资料全部保留；恢复后才能复核。"
              action={<Button onClick={() => setManage('restore')}>恢复…</Button>} />
          )}
          {/* 归档未就绪 */}
          {!study.archive_ok && <ArchiveAlert error={study.archive_error_zh} />}
          {/* 下一步提示 */}
          {next && (
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px 16px', padding: '12px 16px', background: '#FFFFFF', border: `1px solid ${next.code === 'done' ? '#B9DCC8' : '#E9B872'}`, borderRadius: 12 }}>
              <span style={{ fontSize: 14, flex: '1 1 240px' }}><strong>下一步：</strong>{next.text_zh}</span>
              {next.module_id && next.module_id !== mid && (
                <Button style={{ background: '#C76E00', color: '#FFFFFF', border: 0 }} onClick={() => navigate({ page: 'study', studyId, moduleId: next.module_id! })}>
                  前往 {next.module_id}
                </Button>
              )}
            </div>
          )}
          {/* 模块页 */}
          {moduleError ? (
            moduleError.code === 'ARCHIVE_UNAVAILABLE' ? (study.archive_ok ? <ArchiveAlert error={moduleError.messageZh} /> : null) : (
              <Alert type="error" showIcon message="模块读取失败" description={moduleError.messageZh}
                action={<Button onClick={reload}>重试</Button>} />
            )
          ) : !view || !viewMatches ? (
            <div className="card"><Skeleton active paragraph={{ rows: 10 }} /></div>
          ) : (
            <ModulePage
              key={view.module.module_id + (view.run?.run_id || '')}
              studyId={studyId}
              view={view}
              reviewSlot={wide ? undefined : reviewPanel}
              downstreamSlot={wide ? undefined : downstream}
            />
          )}
        </main>

        {/* 右侧复核栏（宽屏） */}
        {wide && (
          <aside className="side-sticky" aria-label="复核决定">
            {reviewPanel}
            {downstream}
          </aside>
        )}
      </div>

      {/* 研究管理对话框 */}
      {manage && (
        <ManageStudyModal open={!!manage} mode={manage} studyId={studyId} title={s.title_zh} onClose={() => setManage(null)}
          onDone={() => { app.bumpRefresh(); if (manage === 'trash') navigate({ page: 'home' }); }} />
      )}
    </>
  );
}
