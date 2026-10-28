// 文件用途：首页。显示研究卡片（进度、下一步、待办数、继续按钮）、全局待办、回收站（列表与恢复）。
import { Alert, Button, Empty, Skeleton } from 'antd';
import { useEffect, useState } from 'react';
import { api, errorText } from '../api/client';
import type { GlobalInboxEntry, StudyCard } from '../api/types';
import { ArchiveAlert, KindTag, ProgressSegs, PurposeTag, StatusPill } from '../components/common';
import ManageStudyModal from '../components/ManageStudyModal';
import { useApp } from '../lib/appContext';
import { fmtDate } from '../lib/format';
import { hrefFor, navigate } from '../lib/route';
import { taskColor } from '../lib/theme';

/** 首页 */
export default function HomePage() {
  const app = useApp(); // 全局上下文
  const [cards, setCards] = useState<StudyCard[] | null>(null); // 研究卡片
  const [error, setError] = useState<string | null>(null); // 读取失败说明
  const [inbox, setInbox] = useState<GlobalInboxEntry[]>([]); // 全局待办
  const [showTrash, setShowTrash] = useState(false); // 是否展开回收站
  const [trash, setTrash] = useState<StudyCard[] | null>(null); // 回收站研究
  const [restoring, setRestoring] = useState<StudyCard | null>(null); // 正在恢复的研究

  // 进入首页时清空顶栏研究名
  const { setCrumb } = app; // 设置顶栏研究名的函数
  useEffect(() => setCrumb(null), [setCrumb]);

  // 读取研究卡片与待办；刷新信号变化时重读
  useEffect(() => {
    let current = true;
    api.studies()
      .then((r) => {
        if (!current) return;
        setCards(r.items); // 更新卡片
        setError(null);
        app.trackTasks(r.items.map((c) => c.active_task)); // 跟踪活动任务
      })
      .catch((e) => { if (current) setError(errorText(e)); });
    api.inbox().then((r) => { if (current) setInbox(r.items); }).catch(() => undefined); // 待办读取失败不影响卡片
    return () => { current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.refreshTick]);

  // 展开回收站时读取列表
  useEffect(() => {
    if (!showTrash) return;
    let current = true;
    api.trash().then((r) => { if (current) setTrash(r.items); }).catch((e) => { if (current) setError(errorText(e)); });
    return () => { current = false; };
  }, [showTrash, app.refreshTick]);

  return (
    <div className="home">
      {/* 标题与新建按钮 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26 }}>我的研究</h1>
          <p className="muted small" style={{ margin: '4px 0 0' }}>一个方剂 + 一个疾病 = 一项研究。点击研究进入工作页。</p>
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 10}}>
          <Button size="large" href={hrefFor({page: 'parameters-preview'})}>个性化参数预览</Button>
          <Button size="large" type="primary" href={hrefFor({page:'new-plan-study'})}>标准／个性化新建</Button>
          <Button type="primary" size="large" disabled={!app.session?.capabilities.create_study} onClick={app.openNewStudy}>新建研究</Button>
        </div>
      </div>
      <div className="small muted" style={{ marginTop: -12 }}>每项研究独立保存资料、运行结果、复核记录和报告。</div>

      {error && <Alert type="error" showIcon message={error} />}

      {/* 全局待办 */}
      {inbox.length > 0 && (
        <section className="card" aria-label="待你处理" style={{ borderColor: '#E9B872' }}>
          <h2 style={{ margin: '0 0 10px', fontSize: 16 }}>待你处理（{inbox.length}）</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {inbox.map((e) => (
              <a
                key={e.study_id + e.module_id}
                href={hrefFor({ page: 'study', studyId: e.study_id, moduleId: e.module_id })}
                style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px 12px', color: '#17212B', textDecoration: 'none', padding: '6px 0', borderBottom: '1px solid #ECEFF1' }}
              >
                <StatusPill code={e.code} label={e.label_zh} />
                <span style={{ flex: 1, minWidth: 200 }}>{e.text_zh}</span>
                <span className="small muted">{e.study_title_zh}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      {/* 研究卡片 */}
      {cards === null && !error ? (
        <Skeleton active />
      ) : cards && cards.length === 0 ? (
        <Empty description="还没有研究" />
      ) : (
        cards?.map((c) => <StudyCardView key={c.study.study_id} card={c} />)
      )}

      {/* 回收站入口与列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Button type="link" style={{ alignSelf: 'flex-start', padding: 0 }} onClick={() => setShowTrash(!showTrash)}>
          {showTrash ? '收起回收站' : `查看回收站${trash ? `（${trash.length}）` : ''}`}
        </Button>
        {showTrash && (
          <div style={{ background: '#FFFFFF', border: '1px dashed #A9B5BF', borderRadius: 12, padding: '14px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="small muted">回收站中的研究只读、可恢复，资料全部保留；当前不提供永久删除。</div>
            {trash === null ? (
              <Skeleton active paragraph={{ rows: 1 }} />
            ) : trash.length === 0 ? (
              <div className="small">回收站是空的。</div>
            ) : (
              trash.map((c) => (
                <div key={c.study.study_id} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ minWidth: 0 }}>
                    {/* 研究名与编号 */}
                    <a href={hrefFor({ page: 'study', studyId: c.study.study_id })}>{c.study.title_zh}</a>{' '}
                    <span className="mono tiny muted">{c.study.study_id}</span>
                  </span>
                  <Button size="small" onClick={() => setRestoring(c)}>恢复…</Button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* 恢复对话框 */}
      {restoring && (
        <ManageStudyModal
          open={!!restoring}
          mode="restore"
          studyId={restoring.study.study_id}
          title={restoring.study.title_zh}
          onClose={() => setRestoring(null)}
          onDone={app.bumpRefresh}
        />
      )}
    </div>
  );
}

/** 单张研究卡片 */
function StudyCardView({ card }: { card: StudyCard }) {
  const s = card.study; // 研究信息
  const mesh = s.disease.mesh_ui ? `MeSH ${s.disease.mesh_ui}${s.disease.mesh_term ? `（${s.disease.mesh_term}）` : ''}` : ''; // MeSH 显示
  const meta = [s.herbs_zh.join('、'), mesh, s.updated_at ? `更新于 ${fmtDate(s.updated_at)}` : ''].filter(Boolean).join(' · '); // 副标题
  const next = card.next_step; // 下一步
  const done = next?.code === 'done'; // 是否全部完成
  // 打开研究：有下一步模块时直接定位到该模块
  const open = () => navigate({ page: 'study', studyId: s.study_id, moduleId: next?.module_id || undefined });
  const t = card.active_task; // 活动任务
  return (
    <article className="card study-card">
      <div className="left">
        {/* 标题与标签 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 19 }}>{s.title_zh}</h2>
          <PurposeTag purpose={card.purpose} />
          <KindTag kind={s.kind} />
        </div>
        <div className="small muted">{meta}</div>
        <div className="small muted" style={{ overflowWrap: 'anywhere' }}>项目编号：<span className="mono">{s.study_id}</span></div>
        {/* 归档未就绪时显示原因 */}
        {!card.archive_ok && <ArchiveAlert error={card.archive_error_zh} compact />}
        {/* 进度分段条 */}
        <ProgressSegs segments={card.progress.segments} />
        <div className="small muted">{card.progress.scope_confirmed ? <>{card.progress.completed} / {card.progress.total} 关口已完成 · {card.progress.approved}项正式通过 · {card.progress.scope_confirmed}项准备已核查</> : <>{card.progress.approved} / {card.progress.total} 已通过</>}</div>
        {/* 活动任务 */}
        {t && (
          <div className="small">
            <span className="pill" style={{ background: taskColor(t.state).bg, color: taskColor(t.state).fg }}>{t.state_zh}</span>{' '}
            后台任务：{t.kind_zh}
          </div>
        )}
      </div>
      <div className="right">
        {/* 下一步提示 */}
        {next && <span style={{ fontSize: 14, fontWeight: 500, color: done ? '#17633F' : '#7A4100' }}>{next.text_zh}</span>}
        {/* 待办数 */}
        <span className="small muted">待办 {card.todo_count} 项</span>
        <Button type="primary" size="large" onClick={open}>{card.todo_count > 0 ? '继续' : '查看研究'}</Button>
      </div>
    </article>
  );
}
