// A06同源出图包选择下载和用户结果图片回传；不推算评分或审批状态。
import {Alert, Button, Collapse, Image, Input, Select, Space, Table, message} from 'antd';
import {useEffect, useRef, useState} from 'react';
import type {DockingArtifactInfo, DrawingPair} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';
import {fmtTime} from '../lib/format';

/** 组合只按后端资格筛选，勾选后下载同源包，图片独立留存。 */
export default function DockingArtifacts({studyId, info}: {studyId: string; info: DockingArtifactInfo}) {
  const app = useApp();
  const [selected, setSelected] = useState<string[]>([]);
  const [caption, setCaption] = useState('');
  const [pair, setPair] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {setSelected([]); setPair(''); setFile(null); setCaption('');}, [info.expected_a06]);
  const eligible = info.pairs.filter(p => p.eligible);
  const picked = eligible.filter(p => selected.includes(p.pair_key));
  const allReady = picked.length > 0 && picked.every(p => !!p.package_url);

  /** 异步任务立即返回，活动任务和结果均通过已有刷新机制读取。 */
  async function packages(action: 'pair_packages' | 'pair_bundle') {
    setBusy(true); setError('');
    try {
      const result = await api.drawingPackages(studyId, action, {expected_a06: info.expected_a06, pair_keys: selected});
      message.success(result.message_zh); app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }

  /** 原始图片与说明提交，验证成功后显示归档预览，不改已批准报告。 */
  async function upload() {
    if (!file) return;
    if (file.size > 16 * 1024 * 1024) {setError('图片须不超过16MiB'); return;}
    const form = new FormData();
    form.append('upload', file); form.append('expected_a06', info.expected_a06);
    form.append('caption', caption); form.append('pair_key', pair);
    setBusy(true); setError('');
    try {
      const result = await api.uploadDockingFigure(studyId, form);
      setFile(null); setCaption(''); if (input.current) input.current.value = '';
      message.success(result.message_zh); app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }

  const columns = [
    {title: '成分', dataIndex: 'compound_name_zh'},
    {title: '受体', dataIndex: 'target_zh'},
    {title: '结合能（kcal/mol）', dataIndex: 'score', render: (score: number | null) => score ?? 'NA'},
    {title: '出图包', render: (_: unknown, row: DrawingPair) => row.package_url ?
      <Button href={row.package_url}>下载本组</Button> : <span className="muted">待整理</span>},
  ];
  return <section className="card stack" aria-label="对接出图与图片上传">
    <h2 style={{margin: 0}}>对接出图包与结果图片</h2>
    {error && <Alert type="error" showIcon message={error}/>}
    {!info.enabled && <Alert type="info" message={info.disabled_reason_zh}/>}
    <p style={{margin: 0}}>勾选需要的组合，点击“生成所选出图包”。已完成的包直接复用。
      出图包包含同源姿势、合并PDB、PyMOL会话、输入及参数。</p>
    <Table<DrawingPair> rowKey="pair_key" size="small" columns={columns} dataSource={eligible} scroll={{x: 600}}
      pagination={{pageSize: 10, showSizeChanger: true}}
      rowSelection={{selectedRowKeys: selected, onChange: keys => setSelected(keys.map(String)),
        getCheckboxProps: () => ({disabled: !info.enabled || busy})}}/>
    <Space wrap>
      <span>已选{selected.length}组</span>
      <Button type="primary" disabled={!info.enabled || !selected.length} loading={busy}
        onClick={() => void packages('pair_packages')}>生成所选出图包</Button>
      {allReady && <Button disabled={!info.enabled} loading={busy}
        onClick={() => void packages('pair_bundle')}>打包下载已准备的所选组合</Button>}
      <Button onClick={() => setSelected([])}>取消选择</Button>
    </Space>
    {info.bundles.length > 0 && <Button type="primary" href={info.bundles[info.bundles.length - 1].url}>
      下载：{info.bundles[info.bundles.length - 1].name_zh}</Button>}
    {info.bundles.length > 0 && <Collapse items={[{key: 'downloads', label: '之前生成的下载包', children:
      <Space wrap>{info.bundles.map(b => <Button key={b.artifact_id} href={b.url}>{b.name_zh}</Button>)}</Space>}]} />}
    <p className="small muted" style={{margin: 0}}>本轮可选择原始评分≤−8的{info.eligible_count}组。
      仅点击按钮后制作选中组合；**不表示统计显著性。</p>
    <h3 style={{margin: '8px 0 0'}}>上传分子对接结果图片</h3>
    <p className="small muted" style={{margin: 0}}>上传你用本批数据制作的PNG/JPEG（≤16MiB），保存后可在此预览和下载。</p>
    <Select aria-label="图片对应组合" showSearch optionFilterProp="label" value={pair}
      disabled={!info.enabled || busy} onChange={setPair}
      options={[{value: '', label: '本批综合图（不限定单个组合）'}, ...info.pairs.map(p =>
        ({value: p.pair_key, label: `${p.compound_name_zh} × ${p.target_zh}`}))]}/>
    <Input.TextArea aria-label="图片说明" placeholder="图片内容与用途说明" value={caption} maxLength={2000}
      disabled={!info.enabled || busy} onChange={e => setCaption(e.target.value)}/>
    <Space wrap>
      <input ref={input} aria-label="选择对接结果图片" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg"
        disabled={!info.enabled || busy} onChange={e => setFile(e.target.files?.[0] ?? null)}/>
      <Button type="primary" disabled={!info.enabled || !file || !caption.trim()} loading={busy} onClick={() => void upload()}>上传并保存图片</Button>
    </Space>
    {info.images.map(item => <div key={item.artifact_id} style={{borderTop: '1px solid #DCE1E5', paddingTop: 12}}>
      <p><strong>{item.name_zh}</strong> · {fmtTime(item.created_at)} · {item.width}×{item.height}</p>
      <Image width={Math.min(item.width, 360)} style={{maxWidth: '100%'}} src={item.url + '?inline=1'} alt={item.caption_zh}/>
      <p style={{whiteSpace: 'pre-wrap'}}>{item.caption_zh}</p><Button href={item.url}>下载原图</Button>
    </div>)}
  </section>;
}
