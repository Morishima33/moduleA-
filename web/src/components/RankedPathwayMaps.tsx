// 当前A05排名首位原生通路命中图；选择排名与命中数据均来自后端归档。
import { Alert, Button, message } from 'antd';
import { useState } from 'react';
import type { RankedPathwayMapsInfo } from '../api/types';
import { api, errorText } from '../api/client';
import { useApp } from '../lib/appContext';

// 只在用户明确点击时生成，页面显示本研究归档链接。
export default function RankedPathwayMaps({studyId, info}: {studyId: string; info: RankedPathwayMapsInfo}) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function generate() {
    setBusy(true); setError(null);
    try {
      const response = await api.rankedPathwayMaps(studyId, info.expected_a05);
      app.trackTasks([response.task]); app.openTasks(response.task.task_id); app.bumpRefresh();
      message.success(response.message_zh);
    } catch (e) {setError(errorText(e)); app.bumpRefresh();}
    finally {setBusy(false);}
  }
  return <section id="a05-ranked-pathway-maps" aria-label="KEGG首位命中通路图" style={{scrollMarginTop: 88}}>
    <h3>KEGG首位命中通路图</h3>
    <p className="small muted">{info.semantics_zh}</p>
    {error && <Alert type="error" showIcon message={error}/>}
    {info.items.length ? info.items.map(item => <figure key={item.ranking} style={{margin:'18px 0'}}>
      <h4>{item.ranking === 'count' ? '命中基因数首位' : '统计显著性首位'}：{item.name_zh}（{item.name_en}）</h4>
      <a href={item.png_url} target="_blank" rel="noreferrer"><img src={item.png_url} alt={item.caption_zh} style={{width:'100%',height:'auto',display:'block'}}/></a>
      <figcaption className="small muted">{item.caption_zh}</figcaption>
      <Button size="small" href={item.png_url.replace('?inline=1','')} download>下载本图</Button>
    </figure>) : <>
      <Button type="primary" loading={busy} disabled={!info.enabled} onClick={generate}>生成两个首位通路命中图</Button>
      {info.disabled_reason_zh && <p className="small muted">{info.disabled_reason_zh}</p>}
    </>}
  </section>;
}
