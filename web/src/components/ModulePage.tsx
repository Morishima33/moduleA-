// 文件用途：研究模块页。待核验事项紧接标题，先核验、后计算和查看结果；历史只读提示保留。
// 状态、后台任务、
// （窄屏时）复核栏、需要知悉、关键数字、数量变化、模块专属图、三个页签、（窄屏时）下游影响。
import { Alert, Button, Collapse, Progress, Tooltip } from 'antd';
import { useState, type ReactNode } from 'react';
import type { ModuleView } from '../api/types';
import { useApp } from '../lib/appContext';
import { fmtTime } from '../lib/format';
import { hrefFor } from '../lib/route';
import { stateStyle, taskColor } from '../lib/theme';
import { StatusPill } from './common';
import DataTabs from './DataTabs';
import DockingCandidates from './DockingCandidates';
import CompoundSelection from './CompoundSelection';
import DockingMatrix from './DockingMatrix';
import DockingPreparation from './DockingPreparation';
import DockingCoverage from './DockingCoverage';
import DockingTrial from './DockingTrial';
import AutomaticDocking from './AutomaticDocking';
import DockingArtifacts from './DockingArtifacts';
import TrialPreparation from './TrialPreparation';
import { FlowChain, FocusSection, KnowSection, KpiGrid } from './ModuleSections';
import EnrichmentTop from './special/EnrichmentTop';
import EnrichmentConfirmation from './EnrichmentConfirmation';
import EnrichmentDisplay from './special/EnrichmentDisplay';
import Heatmap from './special/Heatmap';
import PpiTop from './special/PpiTop';
import PpiDual from './special/PpiDual';
import ReportSummary from './special/ReportSummary';
import Venn from './special/Venn';
import ComponentTop from './special/ComponentTop';
import SourceUploads from './SourceUploads';
import DiseaseScopeReview from './DiseaseScopeReview';
import NormalizationReview from './NormalizationReview';
import DiseaseWorkflowGuide from './DiseaseWorkflowGuide';
import ModuleOperationGuide from './ModuleOperationGuide';
import InputAudit from './InputAudit';
import PpiRun from './PpiRun';
import IdentityReview, { IdentityPlanStatus } from './IdentityReview';
import ReferenceQualification from './ReferenceQualification';
import ReviewablePreparation from './ReviewablePreparation';
import PlanScoring from './PlanScoring';
import CreationPlan from './CreationPlan';
import PlanA01 from './PlanA01';
import PlanA05, { PlanA05Results } from './PlanA05';
import PlanA05Display from './PlanA05Display';
import PlanStages from './PlanStages';
import PlanCompounds from './PlanCompounds';
import PlanSelection from './PlanSelection';
import PlanPreparation from './PlanPreparation';
import ReferenceEvidencePanel from './ReferenceEvidencePanel';
import ReferencePreparationBinding from './ReferencePreparationBinding';
import ScoringReadiness from './ScoringReadiness';

// 需要在标题下方用说明框强调的状态（其他状态只有接口给出 reason_zh 时才显示说明框）
// 新拟定名单不可借用旧评分或旧规模指标。
const stIsStale = (view:ModuleView) => view.state.code === 'stale';
const BOXED = new Set(['idle', 'ready', 'running', 'incomplete', 'failed', 'waiting', 'empty', 'stale', 'unavailable']);

/** 模块页 */
export default function ModulePage({ studyId, view, reviewSlot, downstreamSlot }: {
  studyId: string; view: ModuleView; reviewSlot?: ReactNode; downstreamSlot?: ReactNode;
}) {
  const [keggPending, setKeggPending] = useState(false); // 本地未保存勾选只控制旧图可见性。
  const [scopeDirty, setScopeDirty] = useState(false); // 仅阻止使用未保存的本页范围继续核查。
  const [enrichmentNavigation, setEnrichmentNavigation] = useState(0); // 仅展开显示区，不确认清单。
  const app = useApp(); // 全局上下文（打开任务面板）
  if (view.trial_preparation && !view.historical) {
    return <div className="stack"><TrialPreparation info={view.trial_preparation} label={view.state.label_zh}
      guide={view.operation_guide && <ModuleOperationGuide studyId={studyId} moduleId={view.module.module_id} info={view.operation_guide}/>}/>
      {reviewSlot && <div id="module-review-panel">{reviewSlot}</div>}{downstreamSlot}</div>;
  }
  const m = view.module; // 模块信息
  const preparationEvidenceAvailable = !view.plan_preparation_ui || !!(view.plan_preparation_ui.current?.completed && view.plan_preparation_ui.current.active && view.plan_preparation_ui.current.matches_input);
  const oldIntersection = !view.historical && m.module_id === 'A03' && view.state.code === 'stale'; // 上游更新后，旧零交集只供追溯。
  const oldSelection = !view.historical && ((m.module_id === 'A03_SELECT' && !(view.plan_compounds?.current||view.compound_selection?.previous_active)) || (['A06', 'A06_PREP'].includes(m.module_id) && !!view.docking_review && !view.docking_review.matrix?.ready && stIsStale(view)));
  const st = view.state; // 状态
  const sp = view.special || {}; // 专属数据
  const style = stateStyle(st.code); // 状态配色
  const showBox = BOXED.has(st.code) || !!st.reason_zh; // 是否显示状态说明框
  return (
    <div className="stack">
      {/* 历史版本（只读）提示 */}
      {view.historical && (
        <Alert
          type="info"
          showIcon
          message="历史版本（只读）"
          description={<span>正在查看 {view.run?.order_zh}（<span className="mono">{view.run?.run_id}</span>）。历史版本不能复核。</span>}
          action={<Button href={hrefFor({ page: 'study', studyId, moduleId: m.module_id })} type="primary">回到当前版本</Button>}
        />
      )}

      {/* 标题与状态 */}
      <section id="module-status" className="card" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px 18px', padding: '18px 22px' }}>
        <div style={{ flex: '999 1 300px', minWidth: 0 }}>
          <div className="mono small muted">{m.module_id}{m.group_zh ? ` · ${m.group_zh}` : ''}</div>
          <h1 style={{ margin: '2px 0 0', fontSize: 24 }}>{m.title_zh}</h1>
          <p className="small muted" style={{ margin: '4px 0 0' }}>{m.purpose_zh}</p>
        </div>
        <div style={{ flex: '1 1 200px', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, minWidth: 0 }}>
          <StatusPill code={st.code} label={st.label_zh} large />
          {view.run ? (
            <span className="tiny muted" style={{ textAlign: 'right' }}>
              <Tooltip title={`运行编号：${view.run.run_id}`}><span>{view.historical ? '查看版本' : '当前版本'} {view.run.order_zh}</span></Tooltip>
              <br />生成于 {fmtTime(view.run.finished_at || view.run.created_at)}
            </span>
          ) : (
            <span className="tiny muted">尚无运行结果</span>
          )}
        </div>
      </section>

      {view.operation_guide && <ModuleOperationGuide studyId={studyId} moduleId={m.module_id} info={view.operation_guide} pending={m.module_id === 'A05' && keggPending}
        onLocate={target => {if (target === 'module-enrichment-confirmation') setEnrichmentNavigation(n => n + 1);}}/>}
      {view.creation_plan&&<CreationPlan studyId={studyId} info={view.creation_plan}/>}
      {view.plan_stages&&<PlanStages key={view.plan_stages.expected_input_hash} studyId={studyId} info={view.plan_stages}/>}
      {view.plan_compounds&&<PlanCompounds key={view.plan_compounds.expected_input_hash} studyId={studyId} info={view.plan_compounds}/>}
      {view.plan_preparation_ui&&<PlanPreparation key={view.plan_preparation_ui.input_hash} studyId={studyId} info={view.plan_preparation_ui}/>}
      {view.plan_selection_ui&&<PlanSelection key={view.plan_selection_ui.input_hash} studyId={studyId} info={view.plan_selection_ui}/>}
      {view.plan_a05&&<PlanA05 key={[view.plan_a05.expected_a00,view.plan_a05.expected_a03,view.plan_a05.expected_a05,view.plan_a05.expected_plan_id].join(':')} studyId={studyId} info={view.plan_a05}/>}
      {view.plan_a05_display&&<PlanA05Display key={view.plan_a05_display.expected_input_hash} studyId={studyId} info={view.plan_a05_display}/>}
      {sp.plan_enrichment&&<PlanA05Results studyId={studyId} files={view.files} data={sp.plan_enrichment}/>}
      {view.plan_a01&&<PlanA01 key={[view.plan_a01.expected_a00,view.plan_a01.expected_a01,view.plan_a01.expected_plan_id,view.plan_a01.expected_staging].join(':')} studyId={studyId} info={view.plan_a01}/>}
      {m.module_id === 'A06_PREP' && view.reference_qualification && <ReferenceQualification studyId={studyId} info={view.reference_qualification} packet={view.review_packet} gate={view.review_gate} />}
      {m.module_id === 'A06_PREP' && view.reviewable_preparation && <ReviewablePreparation key={view.reviewable_preparation.current_run_id} studyId={studyId} info={view.reviewable_preparation} />}
      {m.module_id === 'A06_PREP' && !view.historical && preparationEvidenceAvailable && <ReferenceEvidencePanel studyId={studyId} />}
      {m.module_id === 'A06_PREP' && !view.historical && preparationEvidenceAvailable && <ReferencePreparationBinding studyId={studyId} />}
      {m.module_id === 'A06_PREP' && view.scoring_readiness && <ScoringReadiness studyId={studyId} info={view.scoring_readiness} />}
      {view.plan_scoring && <PlanScoring key={`${view.plan_scoring.expected_preparation_run_id}-${view.plan_scoring.current_run_id}`} studyId={studyId} moduleId={m.module_id} info={view.plan_scoring} />}
      {m.module_id === 'A07' && <div id="module-report-downloads"><ReportSummary special={sp} studyId={studyId} downloadsOnly />{!sp.report_files?.length && <Alert type="info" message="本版报告尚未生成，请先查看当前模块状态与输入条件。"/>}</div>}
      {view.disease_workflow && <DiseaseWorkflowGuide studyId={studyId} info={view.disease_workflow} scopeDirty={scopeDirty} />}
      {view.input_audit && <InputAudit studyId={studyId} moduleId={m.module_id} info={view.input_audit} archived={oldIntersection}/>}
      {view.compound_selection && <div id="module-compound-selection"><CompoundSelection studyId={studyId} info={view.compound_selection} review={view.docking_review}/></div>}
      {/* 对接人工关口紧接标题，先核对方案，再阅读矩阵。 */}
      {view.trial_handoff && <div className="card" style={{border:'2px solid #0F5E6E',marginBottom:12}}>
        <strong>当前A06复核：225组合扩展试算结果</strong><p>{view.trial_handoff.note_zh}</p>
        {m.module_id === 'A06' ? <Button type="primary" onClick={() => document.getElementById('module-review-panel')?.scrollIntoView({behavior:'smooth',block:'start'})}>定位正式复核按钮</Button> :
          <Button type="primary" href={view.trial_handoff.review_url}>前往A06结果复核</Button>}
      </div>}
      {view.automatic_docking && <AutomaticDocking key={view.automatic_docking.expected_binding} studyId={studyId} info={view.automatic_docking} moduleId={m.module_id} readOnly={view.historical}/>}
      {!view.automatic_docking && view.docking_trial && <DockingTrial studyId={studyId} info={view.docking_trial}/>}
      {view.docking_artifacts && <div id="module-docking-artifacts"><DockingArtifacts studyId={studyId} info={view.docking_artifacts}/></div>}
      {!view.automatic_docking && (view.docking_coverage || view.docking_preparation) && <div id="module-preparation" className="stack">
      {view.docking_coverage && (view.docking_trial ? <Collapse items={[{key:'strict-history',label:'原严格准备与历史核查（保留）',children:<DockingCoverage studyId={studyId} info={view.docking_coverage}/>}]}/> : <DockingCoverage studyId={studyId} info={view.docking_coverage}/>)}
      {view.docking_preparation && !view.docking_coverage && <DockingPreparation studyId={studyId} info={view.docking_preparation}/>}
      </div>}
      {view.docking_review && !view.automatic_docking && !view.docking_trial && m.module_id !== 'A03_SELECT' && <div id="module-docking-matrix"><DockingMatrix info={view.docking_review}/></div>}
      {view.docking_candidates && !view.automatic_docking && m.module_id !== 'A04' && <DockingCandidates studyId={studyId} moduleId={m.module_id} info={view.docking_candidates} />}
      {view.automatic_docking && <Collapse items={[{key:'legacy', label:'原分步流程与历史资料（可追溯）', children:<div className="stack">{view.docking_coverage ? <DockingCoverage studyId={studyId} info={view.docking_coverage}/> : view.docking_preparation && <DockingPreparation studyId={studyId} info={view.docking_preparation}/>}</div>}]}/>}
      {view.enrichment_display && <div id="module-enrichment-confirmation"><EnrichmentConfirmation studyId={studyId} info={view.enrichment_display} onPendingChange={setKeggPending} navigationRequest={enrichmentNavigation}/></div>}
      {/* 待核验事项紧接标题；证据直接展开，不藏在结果末尾。 */}
      {!view.historical && !oldIntersection && <div id="module-focus"><FocusSection items={view.focus} evidence={sp.ppi_identity ? <IdentityReview studyId={studyId} view={view} data={sp.ppi_identity} /> : undefined} /></div>}
      {m.module_id === 'A02' && !view.historical && view.source_uploads && <SourceUploads studyId={studyId} moduleId={m.module_id} info={view.source_uploads} />}
      {view.disease_scope && <DiseaseScopeReview key={view.run?.run_id} studyId={studyId} info={view.disease_scope} onDirtyChange={setScopeDirty} />}
      {view.normalization && <NormalizationReview key={'normalization-' + view.run?.run_id + (view.normalization.preview?.stamp || '')} studyId={studyId} info={view.normalization} scopeDirty={scopeDirty} />}
      {view.historical && sp.ppi_identity && <section className="card"><h2>历史身份问题清单（只读）</h2><IdentityReview studyId={studyId} view={view} data={sp.ppi_identity} /></section>}
      {!sp.ppi_identity && view.identity_plan?.latest && <section className="card"><h2>身份核验方案与应用结果</h2><IdentityPlanStatus info={view.identity_plan} /></section>}
      {/* 窄屏时整体复核栏也在结果之前。 */}
      {reviewSlot && <div id="module-review-panel">{reviewSlot}</div>}

      {/* 状态说明框：失败、等待资料、空结果、已失效等 */}
      {showBox && (
        <div style={{ padding: '12px 14px', borderRadius: 8, background: style.boxBg, border: `1px solid ${style.boxLine}`, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <strong style={{ fontSize: 14 }}>{st.label_zh}</strong>
          {st.reason_zh && <span style={{ fontSize: 14, color: '#26323C', overflowWrap: 'anywhere' }}>{st.reason_zh}</span>}
          {st.code === 'failed' && <span className="small muted">这是执行失败，不是“0 条结果”。</span>}
          {st.is_empty_result && <span className="small muted">计算已完整执行，结果为空；完整统计表照常保存，可按正常流程复核。</span>}
          {st.handoff_blocked && <span className="small" style={{ color: '#4E3780' }}>资料补齐或例外确认前不能选择“通过”。</span>}
        </div>
      )}

      {/* 本模块进行中的后台任务 */}
      {view.tasks.length > 0 && (
        <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>后台任务</h2>
          {view.tasks.map((t) => (
            <div key={t.task_id} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
              <span className="pill" style={{ background: taskColor(t.state).bg, color: taskColor(t.state).fg }}>{t.state_zh}</span>
              <span>{t.kind_zh}</span>
              {t.progress && <span className="small muted">{t.progress.step_zh}（{t.progress.done}/{t.progress.total}）</span>}
              <Button size="small" onClick={() => app.openTasks(t.task_id)}>查看日志</Button>
              {t.progress && <Progress style={{ flex: '1 1 100%' }} percent={t.progress.total ? Math.round((t.progress.done / t.progress.total) * 100) : 0} size="small" showInfo={false} />}
              {t.error_zh && <span style={{ color: '#8E1B12', flex: '1 1 100%' }}>{t.error_zh}</span>}
            </div>
          ))}
        </section>
      )}

      {view.ppi_run && !view.plan_stages && <div id="module-ppi-run"><PpiRun studyId={studyId} info={view.ppi_run} /></div>}
      {view.source_uploads && (m.module_id !== 'A02' || view.historical) && <div id="module-source-inputs"><SourceUploads studyId={studyId} moduleId={m.module_id} info={view.source_uploads} /></div>}

      {/* 需要知悉 */}
      {!oldIntersection && <KnowSection items={view.focus} />}
      <div id="module-results" className="stack">
      <PreviousIntersection collapsed={oldIntersection}>
      {oldIntersection && <KnowSection items={view.focus} />}
      {/* 关键数字 */}
      {!oldSelection && <KpiGrid kpis={view.kpis} />}
      {/* 数量变化 */}
      {!oldSelection && <FlowChain steps={view.flow} note={view.flow_note_zh} />}

      {/* 模块专属图 */}
      {sp.venn && <Venn data={sp.venn} />}
      {sp.component_top && sp.component_top.length > 0 && <ComponentTop items={sp.component_top} note={sp.component_top_note_zh} />}
      {sp.ppi_dual && <PpiDual data={sp.ppi_dual} />}
      {sp.ppi_top && sp.ppi_top.length > 0 && <PpiTop items={sp.ppi_top} />}
      {sp.enrichment_display_tables && <EnrichmentDisplay special={sp} info={view.enrichment_display} pending={keggPending} rankedMaps={view.ranked_pathway_maps} studyId={studyId} />}
      {sp.enrichment_top && <EnrichmentTop data={sp.enrichment_top} />}
      {sp.heatmap && !view.docking_review && <Heatmap data={sp.heatmap} />}
      {(sp.conclusion_zh || sp.leads || sp.limits || sp.report_files) && <ReportSummary special={sp} studyId={studyId} />}
      {!view.run && <Alert type="info" message="本模块尚无运行结果，请先核对上游状态及本页提示。"/>}
      </PreviousIntersection>
      </div>

      {/* 结果明细 / 参数与版本 / 来源与追溯 */}
      <div id="module-details">{oldSelection ? <Collapse items={[{key:'old-result',label:'已失效历史名单与结果（仅供对照）',children:<><KpiGrid kpis={view.kpis}/><FlowChain steps={view.flow} note={view.flow_note_zh}/><DataTabs studyId={studyId} view={view}/></>}]} /> : oldIntersection ? <Collapse items={[{key:'old-intersection-details',label:'查看旧A03明细及版本（仅供追溯）',children:<DataTabs studyId={studyId} view={view}/>}]} /> : <DataTabs studyId={studyId} view={view} />}</div>
      {view.docking_candidates && m.module_id === 'A04' && <DockingCandidates studyId={studyId} moduleId={m.module_id} info={view.docking_candidates} />}
      {/* 窄屏时下游影响放在最后 */}
      {downstreamSlot}
    </div>
  );
}

/** 上游变更后的旧交集保留但默认折叠，不能让旧零值冒充已修复的新疾病输入。 */
function PreviousIntersection({collapsed, children}: {collapsed: boolean; children: ReactNode}) {
  return collapsed ? <Collapse items={[{key: 'previous-intersection', label: '查看已失效的旧A03图表（仅供追溯）', children: <div className="stack">{children}</div>}]}/> : <>{children}</>;
}
