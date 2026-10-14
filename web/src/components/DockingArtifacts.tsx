// A06精准选择同源出图包和独立图片上传对象；科学资格与评分只读后端结果。
import {Alert, Button, Collapse, Image, Input, Select, Space, Table, message} from 'antd';
import {useEffect, useRef, useState} from 'react';
import type {DockingArtifactInfo, DrawingPair} from '../api/types';
import {api, errorText} from '../api/client';
import {useApp} from '../lib/appContext';
import {fmtTime} from '../lib/format';

/** 下拉按后端身份编号去重，只整理显示选项，不重新计算资格。 */
function compoundOptions(pairs: DrawingPair[]) {
  return Array.from(new Map(pairs.map(p => [p.compound_id, {
    value: p.compound_id, label: p.compound_name_zh,
  }])).values());
}

/** 两级下拉定位一组，上传对象独立保存；按钮点击才提交任务。 */
export default function DockingArtifacts({studyId, info}: {studyId: string; info: DockingArtifactInfo}) {
  const app = useApp();
  const [compound, setCompound] = useState<string>();
  const [target, setTarget] = useState<string>();
  const [selected, setSelected] = useState<string[]>([]);
  const [caption, setCaption] = useState('');
  const [uploadMode, setUploadMode] = useState<'single' | 'batch'>('single');
  const [uploadCompound, setUploadCompound] = useState<string>();
  const [uploadTarget, setUploadTarget] = useState<string>();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setCompound(undefined); setTarget(undefined); setSelected([]);
    setUploadCompound(undefined); setUploadTarget(undefined); setUploadMode('single');
    setFile(null); setCaption(''); setError('');
    if (input.current) input.current.value = '';
  }, [studyId, info.expected_a06]);
  const eligible = info.pairs.filter(p => p.eligible);
  const activePair = eligible.find(p => p.compound_id === compound && p.target_id === target);
  const picked = eligible.filter(p => selected.includes(p.pair_key));
  const allReady = picked.length > 0 && picked.every(p => !!p.package_url);
  const uploadPair = info.pairs.find(p => p.compound_id === uploadCompound && p.target_id === uploadTarget);
  const locked = !info.enabled || busy;

  /** 显式提交指定组合，异步结果沿用已有任务刷新机制。 */
  async function packages(action: 'pair_packages' | 'pair_bundle', pairKeys: string[]) {
    if (!info.enabled || !pairKeys.length) return;
    setBusy(true); setError('');
    try {
      const result = await api.drawingPackages(studyId, action, {expected_a06: info.expected_a06, pair_keys: pairKeys});
      message.success(result.message_zh); app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }

  /** 上传仅绑定独立对象，综合图沿用接口的空组合键。 */
  async function upload() {
    if (!file || !info.enabled || (uploadMode === 'single' && !uploadPair)) return;
    if (file.size > 16 * 1024 * 1024) {setError('图片须不超过16MiB'); return;}
    const form = new FormData();
    form.append('upload', file); form.append('expected_a06', info.expected_a06);
    form.append('caption', caption); form.append('pair_key', uploadMode === 'batch' ? '' : uploadPair!.pair_key);
    setBusy(true); setError('');
    try {
      const result = await api.uploadDockingFigure(studyId, form);
      setFile(null); setCaption(''); if (input.current) input.current.value = '';
      message.success(result.message_zh); app.trackTasks([result.task]); app.bumpRefresh(); app.openTasks(result.task.task_id);
    } catch (e) {setError(errorText(e));} finally {setBusy(false);}
  }

  /** 主动加入才修改队列，重复身份键不会重复加入。 */
  function addPair() {
    if (activePair) setSelected(keys => keys.includes(activePair.pair_key) ? keys : [...keys, activePair.pair_key]);
  }

  /** 用户显式复制；上方后续切换不改变上传选择。 */
  function copyPair() {
    if (!activePair) return;
    setUploadMode('single'); setUploadCompound(activePair.compound_id); setUploadTarget(activePair.target_id);
  }

  const columns = [
    {title: '成分', dataIndex: 'compound_name_zh'},
    {title: '受体', dataIndex: 'target_zh'},
    {title: '结合能（kcal/mol）', dataIndex: 'score', render: (score: number | null) => score ?? 'NA'},
    {title: '操作', render: (_: unknown, row: DrawingPair) => <Space>
      {row.package_url && <Button href={row.package_url}>下载本组</Button>}
      <Button disabled={locked} onClick={() => setSelected(keys => keys.filter(key => key !== row.pair_key))}>移除</Button>
    </Space>},
  ];
  return <section className="card stack" aria-label="对接出图与图片上传">
    <h2 style={{margin: 0}}>对接出图包与结果图片</h2>
    {error && <Alert type="error" showIcon message={error}/>}
    {!info.enabled && <Alert type="info" message={info.disabled_reason_zh}/>}
    <p style={{margin: 0}}>选择成分和受体，精准定位需要的组合。出图包包含同源姿势、合并PDB、PyMOL会话、输入及参数。</p>
    <div style={{display: 'flex', gap: 12, flexWrap: 'wrap'}}>
      <div style={{flex: '1 1 220px', minWidth: 0}}>
        <label htmlFor="drawing-compound">成分</label>
        <Select id="drawing-compound" aria-label="出图成分" style={{width: '100%'}} showSearch allowClear
          placeholder="搜索并选择成分" optionFilterProp="label" value={compound} disabled={locked}
          options={compoundOptions(eligible)} onChange={value => {setCompound(value); setTarget(undefined);}}/>
      </div>
      <div style={{flex: '1 1 220px', minWidth: 0}}>
        <label htmlFor="drawing-target">受体</label>
        <Select id="drawing-target" aria-label="出图受体" style={{width: '100%'}} showSearch allowClear
          placeholder={compound ? '搜索并选择受体' : '请先选择成分'} optionFilterProp="label" value={target}
          disabled={locked || !compound} onChange={setTarget}
          options={eligible.filter(p => p.compound_id === compound).map(p => ({value: p.target_id, label: p.target_zh}))}/>
      </div>
    </div>
    {activePair && <div style={{background: '#F2F4F5', padding: 12, borderRadius: 8}}>
      <Space wrap>
        <strong>{activePair.compound_name_zh} × {activePair.target_zh}</strong>
        <span>结合能：{activePair.score ?? 'NA'} kcal/mol</span>
        {activePair.package_url ? <Button type="primary" href={activePair.package_url}>下载本组出图包</Button> :
          <Button type="primary" disabled={locked} loading={busy}
            onClick={() => void packages('pair_packages', [activePair.pair_key])}>生成本组出图包</Button>}
        <Button disabled={locked || selected.includes(activePair.pair_key)} onClick={addPair}>
          {selected.includes(activePair.pair_key) ? '已加入批量队列' : '加入批量队列'}</Button>
      </Space>
    </div>}
    <Collapse items={[{key: 'queue', label: `批量队列（${picked.length}组）`, children: <div className="stack">
      <Table<DrawingPair> rowKey="pair_key" size="small" columns={columns} dataSource={picked}
        scroll={{x: 600}} pagination={picked.length > 10 ? {pageSize: 10} : false} locale={{emptyText: '选择组合后，点击“加入批量队列”'}}/>
      <Space wrap>
        <Button type="primary" disabled={locked || !picked.length} loading={busy}
          onClick={() => void packages('pair_packages', picked.map(p => p.pair_key))}>生成队列出图包</Button>
        <Button disabled={locked || !allReady} loading={busy}
          onClick={() => void packages('pair_bundle', picked.map(p => p.pair_key))}>打包下载队列</Button>
        <Button disabled={locked || !selected.length} onClick={() => setSelected([])}>清空队列</Button>
      </Space>
    </div>}]} />
    {info.bundles.length > 0 && <Collapse items={[{key: 'downloads', label: '之前生成的下载包', children:
      <Space wrap>{info.bundles.map(b => <Button key={b.artifact_id} href={b.url}>{b.name_zh}</Button>)}</Space>}]} />}
    <p className="small muted" style={{margin: 0}}>本轮可选择原始评分≤−8的{info.eligible_count}组。
      选择和加入队列不会启动计算；点击生成按钮后才制作对应组合，已有包直接复用。双星号标记不表示统计显著性。</p>
    <h3 style={{margin: '8px 0 0'}}>上传分子对接结果图片</h3>
    <p className="small muted" style={{margin: 0}}>上传本批数据制作的PNG/JPEG（≤16MiB），单组图片须选择对应成分和受体。</p>
    <Space wrap>
      <Select aria-label="图片对应范围" value={uploadMode} disabled={locked} onChange={setUploadMode}
        style={{width: 190}} options={[{value: 'single', label: '指定成分与受体'}, {value: 'batch', label: '本批综合图'}]}/>
      <Button disabled={locked || !activePair} onClick={copyPair}>使用上方组合</Button>
    </Space>
    {uploadMode === 'single' && <div style={{display: 'flex', gap: 12, flexWrap: 'wrap'}}>
      <div style={{flex: '1 1 220px', minWidth: 0}}>
        <label htmlFor="upload-compound">图片对应成分</label>
        <Select id="upload-compound" aria-label="图片对应成分" style={{width: '100%'}} showSearch allowClear
          placeholder="搜索并选择成分" optionFilterProp="label" value={uploadCompound} disabled={locked}
          options={compoundOptions(info.pairs)} onChange={value => {setUploadCompound(value); setUploadTarget(undefined);}}/>
      </div>
      <div style={{flex: '1 1 220px', minWidth: 0}}>
        <label htmlFor="upload-target">图片对应受体</label>
        <Select id="upload-target" aria-label="图片对应受体" style={{width: '100%'}} showSearch allowClear
          placeholder={uploadCompound ? '搜索并选择受体' : '请先选择成分'} optionFilterProp="label" value={uploadTarget}
          disabled={locked || !uploadCompound} onChange={setUploadTarget}
          options={info.pairs.filter(p => p.compound_id === uploadCompound).map(p => ({value: p.target_id, label: p.target_zh}))}/>
      </div>
    </div>}
    <p className="small" style={{margin: 0}}>当前上传对象：{uploadMode === 'batch' ? '本批综合图' :
      uploadPair ? `${uploadPair.compound_name_zh} × ${uploadPair.target_zh}` : '请选择成分和受体'}</p>
    <Input.TextArea aria-label="图片说明" placeholder="图片内容与用途说明" value={caption} maxLength={2000}
      disabled={locked} onChange={e => setCaption(e.target.value)}/>
    <Space wrap>
      <input ref={input} aria-label="选择对接结果图片" type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg"
        disabled={locked} onChange={e => setFile(e.target.files?.[0] ?? null)}/>
      <Button type="primary" disabled={locked || !file || !caption.trim() || (uploadMode === 'single' && !uploadPair)}
        loading={busy} onClick={() => void upload()}>上传并保存图片</Button>
    </Space>
    {info.images.map(item => <div key={item.artifact_id} style={{borderTop: '1px solid #DCE1E5', paddingTop: 12}}>
      <p><strong>{item.name_zh}</strong> · {fmtTime(item.created_at)} · {item.width}×{item.height}</p>
      <Image width={Math.min(item.width, 360)} style={{maxWidth: '100%'}} src={item.url + '?inline=1'} alt={item.caption_zh}/>
      <p style={{whiteSpace: 'pre-wrap'}}>{item.caption_zh}</p><Button href={item.url}>下载原图</Button>
    </div>)}
  </section>;
}
