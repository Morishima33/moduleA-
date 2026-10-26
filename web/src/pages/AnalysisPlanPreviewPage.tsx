// 独立参数界面预览：默认值来自服务端目录，校验结果来自原方案接口，不建档或启动研究。
import { Alert, Button, Collapse, InputNumber, Radio, Select, Skeleton, Switch, Tag } from 'antd';
import { CheckCircleOutlined, DownloadOutlined, SlidersOutlined } from '@ant-design/icons';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { AnalysisParameterCatalog, CompiledAnalysisPlan, PlanValue } from '../api/types';
import { hrefFor } from '../lib/route';

/** 预览与旧建档表单隔离，离开页面不把参数写进任何研究。 */
export default function AnalysisPlanPreviewPage() {
  const [catalog, setCatalog] = useState<AnalysisParameterCatalog | null>(null);
  const [values, setValues] = useState<Record<string, PlanValue>>({});
  const [mode, setMode] = useState<'standard' | 'personalized'>('standard');
  const [groupKey, setGroupKey] = useState('a01');
  const [error, setError] = useState('');
  const [checked, setChecked] = useState<CompiledAnalysisPlan | null>(null);
  const [checking, setChecking] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const sequence = useRef(0);

  useEffect(() => {
    let active = true;
    setError('');
    api.analysisParameters().then(data => {
      if (!active) return;
      if (!data.preview?.preview_only) throw new Error('当前服务尚未加载参数预览，请使用本次交付的独立预览地址。');
      setCatalog(data);
      setValues(Object.fromEntries(Object.entries(data.parameters).map(([key, field]) => [key, field.default])));
    }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; sequence.current++; };
  }, [reloadTick]);

  /** 编辑后立即清除旧校验，迟到的响应不得冒充当前方案。 */
  function invalidate() {
    sequence.current++;
    setChecked(null); setError(''); setChecking(false);
  }

  if (!catalog) return <main className="home">
    <h1>新建研究 · 参数预览</h1>
    {error ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setReloadTick(n => n + 1)}>重试</Button>} /> : <Skeleton active />}
  </main>;

  const defaults = Object.fromEntries(Object.entries(catalog.parameters).map(([key, field]) => [key, field.default]));
  const displayed = mode === 'standard' ? defaults : values;
  const selected = catalog.preview.groups.find(group => group.key === groupKey)!;

  /** 输入只改本页内存；类型、范围和交叉约束最终由后台原校验器处理。 */
  function change(key: string, value: PlanValue) {
    invalidate();
    setValues(old => ({...old, [key]: value}));
  }

  /** 显式校验不写研究、不写草稿，也不触发下载或科研工具。 */
  async function validate() {
    const request = ++sequence.current;
    setChecking(true); setError(''); setChecked(null);
    try {
      const result = await api.validateAnalysisPlan(mode === 'standard' ? {mode} : {mode, parameters: values});
      if (sequence.current === request) setChecked(result.plan);
    } catch (e) { if (sequence.current === request) setError(errorText(e)); }
    finally { if (sequence.current === request) setChecking(false); }
  }

  /** 下载已校验预览，明确未绑定研究；不能把导出当成研究方案已保存。 */
  function download() {
    if (!checked) return;
    const blob = new Blob([JSON.stringify({preview_only: true, unbound_to_study: true, plan: checked}, null, 2)], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'ModuleA_参数预览方案.json';
    a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /** 全部可调控件读取同一参数目录；固定项和非当前模式项不伪装成可编辑。 */
  function field(key: string) {
    const definition = catalog!.parameters[key];
    const detail = catalog!.preview.details[key];
    const inactive = !!definition.active_when && Object.entries(definition.active_when).some(([k, value]) => displayed[k] !== value);
    const disabled = mode === 'standard' || inactive;
    const value = displayed[key];
    let control;
    if (definition.type === 'boolean') {
      control = <Switch aria-label={definition.label} checked={Boolean(value)} disabled={disabled} checkedChildren="纳入" unCheckedChildren="不纳入" onChange={v => change(key, v)} />;
    } else if (definition.choices) {
      control = <Select aria-label={definition.label} value={value as string | number} disabled={disabled}
        style={{width: '100%'}} options={definition.choices.map(v => ({value: v, label: detail?.choices_zh?.[String(v)] || String(v)}))}
        onChange={v => change(key, v)} />;
    } else {
      control = <InputNumber aria-label={definition.label} value={typeof value === 'number' ? value : null} disabled={disabled}
        style={{width: '100%'}} min={definition.min ?? definition.min_exclusive} max={definition.max}
        step={definition.type === 'integer' ? 1 : definition.resolution || (key === 'a01.ob_min' ? 1 : .01)}
        precision={definition.type === 'integer' ? 0 : undefined}
        formatter={key === 'a04.required_score' ? ((v, info) => info.userTyping ? info.input : v == null || String(v) === '' ? '' : Number(v).toFixed(Math.abs(Number(v) * 100 - Math.round(Number(v) * 100)) > 1e-8 ? 3 : 2)) : undefined}
        onChange={v => change(key, v === null ? '' : v)} addonAfter={definition.unit || undefined} />;
    }
    return <div className={'plan-field' + (inactive ? ' inactive' : '')} key={key} data-parameter={key}>
      <label>{definition.label}{inactive && <span className="small muted">（仅A/B模式）</span>}</label>
      {control}<div className="small muted plan-field-help">{detail?.help_zh}</div>
    </div>;
  }

  return <main className="home plan-preview-page">
    <div className="plan-page-heading">
      <div><Tag color="gold">第一部分 · 独立预览</Tag><h1>新建研究 · 分析方案与参数</h1>
        <p className="muted">先选择分析方式，再查看或调整参数。每项研究将使用自己独立的方案与资料。</p></div>
      <Button href={hrefFor({page: 'home'})}>返回研究列表</Button>
    </div>
    <Alert type="info" showIcon message={catalog.preview.message_zh} />

    <section className="card plan-mode-section" aria-label="分析方式">
      <div className="plan-section-heading"><h2>1. 选择分析方式</h2><span className="small muted">旧固定流程继续保留</span></div>
      <Radio.Group className="plan-mode-options" value={mode} onChange={e => { invalidate(); setMode(e.target.value); }}>
        <div className={'plan-mode-card' + (mode === 'standard' ? ' selected' : '')}>
          <Radio value="standard"><strong>标准自动版</strong><Tag color="cyan">默认方案</Tag></Radio>
          <p>沿用当前约定的参数，查看完整规则；无需逐项调整。</p>
        </div>
        <div className={'plan-mode-card' + (mode === 'personalized' ? ' selected' : '')}>
          <Radio value="personalized"><strong>个性化版</strong><Tag>可调参数</Tag></Radio>
          <p>按研究目标调整筛选、网络、富集和对接参数。</p>
        </div>
      </Radio.Group>
    </section>

    <section className="plan-summary-strip" aria-label="当前目标范围">
      <div><span className="small muted">目标热图</span><strong>{String(displayed['a06.component_count'])} × {String(displayed['a06.receptor_count'])}</strong></div>
      <div><span className="small muted">边界处理</span><b>保留并列，不足按实际</b></div>
      <div><span className="small muted">对接包</span><b>结果后按所选组合生成</b></div>
      <p className="small muted">这里是目标范围；实际成分数、受体数和NA由真实数据及质控决定。</p>
    </section>

    <section className="card plan-parameter-section">
      <div className="plan-section-heading"><h2><SlidersOutlined /> 2. 查看与调整详细参数</h2><Tag>{mode === 'standard' ? '标准参数只读' : '当前允许调整'}</Tag></div>
      <div className="plan-parameter-layout">
        <nav className="plan-group-nav" aria-label="参数分组">
          {catalog.preview.groups.map(group => <button key={group.key} type="button" onClick={() => setGroupKey(group.key)}
            className={groupKey === group.key ? 'selected' : ''} aria-current={groupKey === group.key ? 'page' : undefined}>
            <span className="small muted">{group.stage_zh}</span><strong>{group.title_zh}</strong>
          </button>)}
        </nav>
        <div className="plan-group-body" key={groupKey}>
          <div className="plan-section-heading"><h3>{selected.title_zh}</h3>
            <Tag color={selected.status === 'backend_ready' ? 'cyan' : selected.status === 'partial' ? 'blue' : 'default'}>{selected.status_zh}</Tag></div>
          <p className="small muted">{selected.description_zh}</p>
          <div className="plan-field-grid">{selected.fields.map(field)}</div>
          {!!selected.advanced_fields.length && <Collapse className="plan-advanced" items={[{key: 'advanced', label: '更多参数与方法设置', children: <div className="plan-field-grid">{selected.advanced_fields.map(field)}</div>}]} />}
          {selected.key === 'a01' && <div className="plan-source-rules">
            {catalog.preview.source_rules.map(source => <div key={source.name}><strong>{source.name}</strong><span className="small muted">{source.rule_zh}</span></div>)}
          </div>}
        </div>
      </div>
    </section>

    <Collapse className="plan-fixed-rules" items={[{key: 'fixed', label: '固定研究规则（只读，不作为可调参数）', children: <ul>{catalog.preview.fixed_rules_zh.map(rule => <li key={rule}>{rule}</li>)}</ul>}]} />
    {error && <Alert type="error" showIcon message="方案尚未通过校验" description={error} />}
    {checked && <Alert type="success" showIcon icon={<CheckCircleOutlined />} message="当前预览方案已通过参数校验" description={<>
      <div>仅校验通过，尚未保存为研究方案或启动计算。</div>
      {checked.warnings.map(warning => <div key={warning.code}>{warning.message_zh}</div>)}
      <div className="small mono" style={{overflowWrap: 'anywhere'}}>方案指纹：{checked.parameter_hash}</div>
    </>} />}
    <div className="card plan-preview-actions">
      <span className="small muted">预览参数不会带入旧固定流程的新建窗口。</span>
      <div><Button onClick={() => { invalidate(); setValues(defaults); }}>恢复默认参数</Button>
        <Button type="primary" loading={checking} onClick={() => void validate()}>校验当前方案</Button>
        <Button icon={<DownloadOutlined />} disabled={!checked} onClick={download}>下载预览方案</Button></div>
    </div>
  </main>;
}
