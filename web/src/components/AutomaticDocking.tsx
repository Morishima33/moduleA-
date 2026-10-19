// 一次授权对接：连接、明确授权、后台执行、逐分数追溯；不预选科研批准。
import {Alert, Button, Checkbox, Collapse, Drawer, Input, Table, message} from 'antd';
import {useEffect, useRef, useState} from 'react';
import type {AutomaticDockingInfo, AutomaticPair} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';
import {hrefFor} from '../lib/route';

/** 表单一次提交固定范围，后续进度由现有后台任务队列回报。 */
export default function AutomaticDocking({studyId, info}: {studyId: string; info: AutomaticDockingInfo}) {
  const {bumpRefresh, openTasks} = useApp();
  const [busy, setBusy] = useState(false), [checked, setChecked] = useState(false);
  const [reviewer, setReviewer] = useState(''), [note, setNote] = useState('');
  const [error, setError] = useState(''), [trace, setTrace] = useState<AutomaticPair | null>(null);
  const requestId = useRef('auto_' + crypto.randomUUID().replace(/-/g, ''));
  useEffect(() => {setChecked(false); requestId.current = 'auto_' + crypto.randomUUID().replace(/-/g, '');}, [info.expected_connection_id, info.expected_a06]);
  const connection = info.connection, latest = info.latest;
  const usable = !!connection && connection.summary.connected_compounds > 0 && connection.summary.connected_receptors > 0;
  const image = latest?.files.find(f => f.name === 'A06_automatic_heatmap.png');
  async function submit(calculate: boolean) {
    setBusy(true); setError('');
    try {
      const result = calculate ? await api.automaticRun(studyId, {expected_binding: info.expected_binding,
        expected_connection_id: info.expected_connection_id!, expected_a06: info.expected_a06,
        request_id: requestId.current, policy_version: info.policy.version, reviewer: reviewer.trim(), note: note.trim(), confirmed: checked}) :
        await api.automaticConnect(studyId, info.expected_binding);
      message.success(result.message_zh); openTasks(result.task.task_id); bumpRefresh();
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }
  return <section className="card stack" id="module-automatic-docking" style={{scrollMarginTop: 90, minWidth: 0}}>
    <h2 style={{margin: 0}}>A06 一次确认，自动计算</h2>
    <p>连接本研究资料 → 核对范围并一次确认 → 后台准备、质控、对接和出图 → 独立复核结果。</p>
    <p>当前范围：{info.counts.compounds} 个成分、{info.counts.receptors} 个受体，共 {info.counts.pairs} 个组合。异常对象保留原因，其余继续。</p>
    {!info.enabled && <Alert type="info" showIcon message={info.disabled_reason_zh || '当前不可提交'}/>}
    {error && <Alert type="error" showIcon message={error}/>}
    <Button style={{alignSelf:'flex-start'}} loading={busy} disabled={!info.enabled} onClick={() => submit(false)}>
      {connection ? '重新连接资料（生成新版本）' : '1. 连接资料（不计算对接）'}</Button>
    {connection && <>
      <Alert type="info" showIcon message={`连接完成：成分 ${connection.summary.connected_compounds}/${info.counts.compounds}，受体 ${connection.summary.connected_receptors}/${info.counts.receptors}；异常 ${connection.summary.exceptions} 项。`}/>
      <Collapse items={[{key:'objects', label:'查看连接对象、构型及集中异常', children:<>
        <Table rowKey="id" size="small" scroll={{x:680}} dataSource={connection.objects} columns={[
          {title:'对象',dataIndex:'name'}, {title:'编号',dataIndex:'id'}, {title:'状态',render:(_,r) => ({connected:'连接完成',failed:'连接失败',unavailable:'资料待核对'}[r.state] || r.state)},
          {title:'来源与构型',render:(_,r) => r.cid ? `PubChem CID ${r.cid}` : r.structures.map(s => `${s.pdb_id} / 链 ${s.chains.join(',')} / ${s.pocket === 'reference' ? '共晶位点' : '首位预测口袋'} / ${s.altloc || '无替代构象'}`).join('；')},
          {title:'异常原因',dataIndex:'reason_zh'}]}/>
        <p>没有通过连接或质控的组合保留为NA或失败，不填零、不挪用其他研究资料。</p>
      </>}, {key:'policy', label:'查看固定自动策略及适用范围', children:<ul>{info.policy.details_zh.map(x => <li key={x}>{x}</li>)}</ul>} ]}/>
      <p>{info.policy.summary_zh}</p>
      <Input aria-label="执行确认人" placeholder="执行确认人" value={reviewer} onChange={e => setReviewer(e.target.value)} maxLength={200}/>
      <Input.TextArea aria-label="执行说明" placeholder="执行说明（例如本次采用的范围与用途）" value={note} onChange={e => setNote(e.target.value)} maxLength={2000}/>
      <Checkbox checked={checked} onChange={e => setChecked(e.target.checked)}>我确认本次范围及上述策略，授权自动准备、质控、对接和出图；预测位点结果单列为探索，结果另行复核。</Checkbox>
      <Button type="primary" style={{alignSelf:'flex-start', whiteSpace:'normal', height:'auto', padding:10}} loading={busy}
        disabled={!info.enabled || !usable || !checked || !reviewer.trim() || !note.trim()} onClick={() => submit(true)}>2. 一次确认并开始自动计算</Button>
    </>}
    {latest && <>
      <h3>本批执行结果</h3>
      <Alert type={['failed','interrupted','stale'].includes(latest.state) ? 'warning' : 'info'} message={{completed:'计算已完成，结果复核见A06',running:'后台正在计算',authorized:'执行授权已登记',failed:'本次执行失败，证据保留',interrupted:'执行已中断，证据保留',stale:'旧批次来源已更新，仅供追溯'}[latest.state] || latest.state} description={latest.error_zh}/>
      {latest.summary && <p>成功 {String(latest.summary['成功组合数'])}；失败 {String(latest.summary['失败组合数'])}；NA {String(latest.summary['NA组合数'])}。严格受体 {String(latest.summary['严格受体数'])}，探索受体 {String(latest.summary['探索受体数'])}。</p>}
      {image && <a href={image.url} target="_blank" rel="noreferrer"><img alt="本批自动对接评分热图" src={image.url} style={{width:'100%', maxWidth:1400}}/></a>}
      <Table rowKey={r => r.compound_id + ':' + r.target_id} size="small" scroll={{x:700}} dataSource={latest.pairs} columns={[
        {title:'成分',dataIndex:'compound_name'}, {title:'受体',dataIndex:'symbol'}, {title:'评分 kcal/mol',render:(_,r) => r.score ?? 'NA'},
        {title:'范围',dataIndex:'quality'}, {title:'状态 / 原因',render:(_,r) => r.state === 'completed' ? '完成' : r.reason_zh},
        {title:'溯源',render:(_,r) => <Button size="small" onClick={() => setTrace(r)}>查看计算依据</Button>} ]}/>
      {latest.state === 'completed' && <Button href={hrefFor({page:'study',studyId,moduleId:'A06'})}>前往A06独立结果复核</Button>}
    </>}
    <Collapse items={[{key:'files', label:'原件、参数、姿势与运行日志', children:<div className="stack">{(latest?.files || connection?.files || []).map((f,i) => <a key={i} href={f.url} target="_blank" rel="noreferrer" style={{overflowWrap:'anywhere'}}>{f.path || f.name}</a>)}</div>} ]}/>
    <Drawer title="本分数计算依据" open={!!trace} onClose={() => setTrace(null)} width="min(760px, 95vw)">
      <p>保留实际输入、采用构型、搜索盒、质控、软件参数及执行命令；原始文件在本批文件清单中下载。</p>
      {trace && <><p>成分：{trace.compound_name}（{trace.compound_id}）</p><p>受体：{trace.symbol}（{trace.target_id}）</p><p>评分：{trace.score ?? 'NA'} kcal/mol；采用范围：{trace.quality}</p><p>{trace.reason_zh}</p></>}
      <div className="stack">{trace?.evidence_files?.map(f => <a key={f.url} href={f.url} target="_blank" rel="noreferrer" style={{overflowWrap:'anywhere'}}>{f.path || f.name}</a>)}</div>
      <Collapse items={[{key:'raw', label:'展开构型、位点、参数和完整执行依据', children:<pre style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', fontSize:12}}>{trace ? JSON.stringify(trace, null, 2) : ''}</pre>}]}/>
    </Drawer>
  </section>;
}
