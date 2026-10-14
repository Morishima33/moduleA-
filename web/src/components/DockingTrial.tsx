// 独立15×15试算：只显示服务端事实，集中核查一次；正式科研审批保持独立。
import {Alert, Button, Checkbox, Collapse, Input, Modal, Progress, Table, Tag, message} from 'antd';
import {useEffect, useState} from 'react';
import type {DockingTrialInfo, TrialReceptor} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';

const modeLabel: Record<string, string> = {
  fixed_site: '预先固定的共晶位点', predicted_sites: '预测位点探索', partitioned_blind: '分区盲搜',
};

/** 每个分数保留区域、原精度及NA原因，宽矩阵只在容器内滚动。 */
function Scores({info, heatmap = false}: {info: DockingTrialInfo; heatmap?: boolean}) {
  const matrix = info.matrix;
  if (!matrix) return null;
  if (heatmap && matrix.heatmap_svg) return <div style={{overflowX: 'auto'}}>
    <div style={{minWidth: 670, maxWidth: 940, margin: '0 auto'}}
      className="bilingual-heatmap" dangerouslySetInnerHTML={{__html: matrix.heatmap_svg}}/>
  </div>;
  const targets = heatmap ? matrix.columns.filter(c => matrix.heatmap_targets.includes(c.id)) : matrix.columns;
  const rows = heatmap ? matrix.rows.filter(r => matrix.heatmap_compounds.includes(r.id)) : matrix.rows;
  return <div style={{overflowX: 'auto'}}><table style={{borderCollapse: 'collapse', fontSize: 12, width: '100%'}}>
    <thead><tr><th style={{background: '#0F5E6E', color: 'white', padding: 8, minWidth: 130}}>成分</th>
      {targets.map(c => <th key={c.id} style={{background: '#0F5E6E', color: 'white', padding: 7, minWidth: 66}}>
        {c.label}<br/>{c.grade}</th>)}</tr></thead>
    <tbody>{rows.map(row => <tr key={row.id}><td style={{padding: 7, border: '1px solid #DCE1E5'}}>{row.label_zh || row.label}
      {row.label_en && <div style={{fontSize: 10, color: '#586B75', maxWidth: 280}}>{row.label_en}</div>}</td>
      {targets.map(c => {const cell = row.cells.find(v => v.target_id === c.id)!;
        return <td key={c.id} title={cell.score == null ? cell.reason_zh :
          `${cell.score} kcal/mol；${modeLabel[cell.mode]}；${cell.region_id}${cell.partial_regions ? '；部分区域失败' : ''}`}
          style={{textAlign: 'center', padding: 8, border: '1px solid #DCE1E5',
            background: heatmap ? cell.color : undefined,
            color: heatmap ? cell.text_color : undefined}}>{cell.display_score ?? (cell.score == null ? 'NA' : cell.score.toFixed(2))}
            {!heatmap && cell.highlight && <sup style={{marginLeft: 2}}>**</sup>}</td>;
      })}</tr>)}</tbody></table></div>;
}

/** 结构与处理集中在同一窗口，证据默认折叠，不要求用户判断原子参数。 */
export default function DockingTrial({studyId, info}: {studyId: string; info: DockingTrialInfo}) {
  const {bumpRefresh} = useApp();
  const [open, setOpen] = useState(false), [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState(''), [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => {setReviewer(info.review?.reviewer || ''); setNote(info.review?.note || '');
    setChecked(false); setError('');}, [info.trial_id, info.review?.review_id]);
  useEffect(() => {
    if (info.state === 'completed' || info.state === 'interrupted') return;
    const timer = window.setInterval(bumpRefresh, 15000);
    return () => window.clearInterval(timer);
  }, [info.trial_id, info.state, bumpRefresh]);
  async function save(final: boolean) {
    setBusy(true); setError('');
    try {
      const result = await api.saveTrialReview(studyId, {trial_id: info.trial_id, reviewer, note, confirmed: final});
      message.success(result.message_zh); bumpRefresh(); if (final) setOpen(false);
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }
  function evidence(row: TrialReceptor) {
    return <Collapse size="small" items={[{key: 'facts', label: '查看来源、修补和区域证据', children: <>
      <p>{row.processing_zh || row.reason_zh}</p>
      <p>来源：{row.source?.path || '未成功准备'}；原质控：{row.history_quality_zh || '未通过'}
        {row.history_rmsd_A != null && `；原Top-1 RMSD ${row.history_rmsd_A.toFixed(3)} Å`}</p>
      {row.repair && <p>新增侧链原子 {row.repair.added_atoms.length} 个；已解析重原子坐标
        {row.repair.original_coordinates_unchanged ? '保持不变' : '未验证'}；未补建缺失主链。</p>}
      <p>区域集合在计算前固定，同一受体的15个成分一致。详细盒参数和失败诊断随导出归档。</p>
      <pre style={{whiteSpace: 'pre-wrap', fontSize: 11}}>{JSON.stringify({spec: row.spec,
        regions: row.regions, environment: row.environment, attempts: row.attempts}, null, 2)}</pre>
    </>}]}/>;
  }
  const columns = [
    {title: '受体', render: (_: unknown, r: TrialReceptor) => <>{r.symbol}<br/><Tag>{r.candidate_grade}</Tag></>},
    {title: '结构', dataIndex: 'structure_id'},
    {title: '评分来源', render: (_: unknown, r: TrialReceptor) => modeLabel[r.mode]},
    {title: '处理与适用范围', render: (_: unknown, r: TrialReceptor) => <>{r.state === 'ready' ?
      <Tag color="blue">扩展试算</Tag> : <Tag>NA</Tag>}{r.reason_zh}{evidence(r)}</>},
  ];
  return <section id="a06-trial" className="card" style={{border: '2px solid #0F5E6E', marginBottom: 16}}>
    <h3>15×15结合能试算表</h3><p>{info.note_zh}</p>
    {info.stale && <Alert type="warning" message="上游版本已改变，此试算仅供历史核查，不能作为当前结果。"/>}
    {info.state !== 'completed' ? <>
      {info.state === 'interrupted' && <Alert type="warning" message="本次运行未完整结束，保留原文件；可在后台任务中重试。"/>}
      <Alert type="info" message={info.progress.step_zh}/>
      <Progress percent={Math.round(info.progress.pairs_done / 225 * 100)}/>
      <p>组合 {info.progress.pairs_done}/225；区域 {info.progress.regions_done}/{info.progress.regions_total || '待准备确定'}。</p>
      <p className="small">日志、取消和失败重试见“后台任务”。完整计算结束前不填入示例分数。</p>
    </> : <>
      <p><Tag color="blue">真实评分 {info.summary?.completed}/225</Tag><Tag>NA {info.summary?.NA}</Tag>
        <Button type="primary" onClick={() => setOpen(true)}>集中核查试算与保存</Button></p>
      <h4>重点展示：8×8热图</h4><Scores info={info} heatmap/>
      <p className="small">红蓝渐变：评分越负红色越深，越不负蓝色越深；NA灰色。完整同批范围：
        {info.matrix?.score_range?.join(' ～ ') || '无有效评分'} kcal/mol。</p>
      <h4>扩展筛查：15×15表</h4><Scores info={info}/>
      <p className="small">{info.matrix?.annotation_legend}</p>
      <p>{info.downloads.map(file => <Button key={file.url} href={file.url}>{file.name}</Button>)}</p>
      {info.review && <Alert type="success" message={info.review.confirmed ?
        '试算核查已保存；正式科研结果仍独立复核。' : '核查草案已保存，可继续填写。'}/>}
    </>}
    <Modal title="本轮试算集中核查" open={open} onCancel={() => setOpen(false)} width={1150}
      styles={{body: {maxHeight: '70vh', overflowY: 'auto'}}} footer={<>
        <Button onClick={() => setOpen(false)}>返回</Button>
        <Button loading={busy} disabled={!info.enabled} onClick={() => void save(false)}>保存草案</Button>
        <Button type="primary" loading={busy} disabled={!info.enabled || !checked || !reviewer.trim() || !note.trim()}
          onClick={() => void save(true)}>保存本轮试算核查</Button></>}>
      <Alert type="info" message="只核对结构、位点、处理用途和NA原因；本次保存不代替正式A06科研批准。"/>
      {error && <Alert type="error" message={error}/>}
      <Table rowKey="target_id" pagination={false} size="small" columns={columns} dataSource={info.receptors}/>
      <Input aria-label="试算核查人" placeholder="核查人" value={reviewer} onChange={e => setReviewer(e.target.value)}/>
      <Input.TextArea aria-label="试算核查说明" placeholder="核查说明" value={note} onChange={e => setNote(e.target.value)}/>
      <p><Button onClick={() => setChecked(true)} disabled={!info.enabled}>勾选汇总核对</Button>
        <Button onClick={() => setChecked(false)}>取消勾选</Button></p>
      <Checkbox checked={checked} disabled={!info.enabled} onChange={e => setChecked(e.target.checked)}>
        已核对本轮结构、位点、处理范围及未完成项，仅保存试算核查</Checkbox>
    </Modal>
  </section>;
}
