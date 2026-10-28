// 文件用途：明确提交只读评分预检，显示同批参数和阻断原因，不启动计算。
import { Alert, Button, Checkbox, Collapse, Descriptions, Input } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { ScoringValidation } from '../api/types';
import { useApp } from '../lib/appContext';

/** 刷新或准备版本变化后清除旧预检，结果仅来自本次服务端响应。 */
export default function ScoringPreflight({ studyId, preparationRunId }: { studyId: string; preparationRunId: string }) {
  const app = useApp();
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ScoringValidation | null>(null);
  const sequence = useRef(0);
  useEffect(() => {
    sequence.current += 1;
    setResult(null); setConfirmed(false); setBusy(false); setError('');
    return () => { sequence.current += 1; };
  }, [studyId, preparationRunId, app.refreshTick]);

  /** 预检确认只请求检查，不登记科学决定或评分授权。 */
  async function submit() {
    if (!confirmed || !reviewer.trim() || !note.trim() || busy) return;
    const request = ++sequence.current;
    setBusy(true); setError(''); setResult(null);
    try {
      const value = await api.validateA06Scoring(studyId, {
        expected_preparation_run_id: preparationRunId, reviewer, note, confirmed: true,
      });
      if (request === sequence.current) { setResult(value); setConfirmed(false); }
    } catch (e) {
      if (request === sequence.current) { setError(errorText(e)); setConfirmed(false); }
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  }

  return <Collapse style={{ marginTop: 12 }} items={[{ key: 'preflight', label: '检查评分前置条件（不启动计算）', children:
    <div className="stack" id="a06-scoring-preflight">
      <p className="small muted">检查本批实际参数、准备和复核状态。此操作不会保存复核决定或启动评分。</p>
      <Input aria-label="评分预检人" placeholder="预检人" value={reviewer} maxLength={2000} disabled={busy}
        onChange={e => { setReviewer(e.target.value); setConfirmed(false); }} />
      <Input.TextArea aria-label="评分预检依据" placeholder="本次预检说明" value={note} maxLength={2000} disabled={busy}
        onChange={e => { setNote(e.target.value); setConfirmed(false); }} />
      <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>仅检查前置条件，不启动评分</Checkbox>
      <Button type="primary" loading={busy} disabled={busy || !confirmed || !reviewer.trim() || !note.trim()} onClick={() => void submit()}>检查评分前置条件</Button>
      {error && <Alert type="error" showIcon message={error} />}
      {result && <div className="stack" id="a06-scoring-preflight-result">
        <Alert type="warning" showIcon message={result.reason_zh} />
        <Descriptions bordered size="small" column={1} items={[
          { key: 'pairs', label: '固定组合', children: result.pair_count },
          { key: 'ready', label: '准备可用组合', children: result.ready_pairs },
          { key: 'na', label: 'NA组合', children: result.na_pairs },
          { key: 'effort', label: '搜索投入', children: result.scoring_parameters.exhaustiveness },
          { key: 'modes', label: '输出姿势数', children: result.scoring_parameters.num_modes },
          { key: 'energy', label: '能量范围（kcal/mol）', children: result.scoring_parameters.energy_range_kcal_mol },
          { key: 'seed', label: '随机种子', children: result.scoring_parameters.seed },
          { key: 'padding', label: '搜索盒外扩（Å）', children: result.box_padding },
          { key: 'rmsd', label: '方案参考RMSD上限（Å）', children: result.requested_rmsd_max_A },
          { key: 'source', label: '来源准备', children: <span style={{ overflowWrap: 'anywhere' }}>{result.source_preparation_run_id}</span> },
        ]} />
        <ul style={{ margin: 0, paddingLeft: 22 }}>{result.blockers.map(item => <li key={item}>{item}</li>)}</ul>
      </div>}
    </div>,
  }]} />;
}
