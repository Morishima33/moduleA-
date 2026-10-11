// 同一归档批次的热图和扩展表，色值与完整覆盖校验由服务端提供。
import {Alert,Button,Collapse,Table,Tooltip,message} from 'antd';
import type {DockingReviewInfo,DockingReviewCompound} from '../api/types';

export default function DockingMatrix({info}:{info:DockingReviewInfo}){
 const m=info.matrix;
 if(!info.enabled||!m)return <section className="card"><h2>对接图表展示</h2><Alert type="warning" message={info.reason_zh}/></section>;
 const h=m.heatmap,t=m.table;
 // 导出已验证的同源SVG；PNG仅栅格化同一图件，不填充或计算评分。
 async function download(kind:'svg'|'png'){try{const svg=m?.heatmap_svg;if(!svg)throw new Error('本轮没有可导出的评分图');let blob:Blob;
 if(kind==='svg')blob=new Blob([svg],{type:'image/svg+xml;charset=utf-8'});else{const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);await image.decode();const canvas=document.createElement('canvas');canvas.width=image.naturalWidth*3;canvas.height=image.naturalHeight*3;const context=canvas.getContext('2d');if(!context)throw new Error('浏览器无法导出图件');context.scale(3,3);context.drawImage(image,0,0);blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('PNG导出失败')),'image/png'));}
 const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='A06_01_重点结合能热图.'+kind;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(e){message.error(e instanceof Error?e.message:'图件导出失败')}}
 return <section className="card" id="a06-matrix"><h2>重点热图与扩展结合能表</h2>
 <p>热图 {h.rows.length}×{h.columns.length}；表格 {t.rows.length}×{t.columns.length}；完整记录 {m.full_pair_count} 组。</p>
 <p className="small">同批Vina Top-1评分（kcal/mol）。受体A优先、组内按完整网络Degree降序；截断并列按HGNC编号稳定排列，完整并列及其余组合仍留存。A/B候选级别与严格／探索质控分别记录。</p>
 <p className="small">本轮配色：{m.palette.label_zh}（{m.palette.high_color} → {m.palette.low_color}）。</p>
 {!m.ready?<Alert type="info" showIcon message={m.status_zh} description="尚无本轮有效评分，不显示热图色块或填充示例数值。名单确认不代替真实计算授权。"/>:<>
 <h3>重点结合能热图</h3><div className="toolbar"><Button disabled={!m.heatmap_svg} onClick={()=>download('svg')}>下载SVG图</Button><Button disabled={!m.heatmap_svg} onClick={()=>download('png')}>下载PNG图</Button></div>
 <div style={{overflowX:'auto'}}>{m.heatmap_svg&&<img alt="重点结合能热图" src={'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(m.heatmap_svg)} style={{maxWidth:'none'}}/>}</div><p className="small">{m.palette.label_zh}；颜色范围取完整同批有效评分，图中注明实际范围与kcal/mol。对接评分不能直接证明药效。</p>
 <h3>扩展结合能表</h3><Table<DockingReviewCompound> rowKey="compound_id" size="small" pagination={false} scroll={{x:240+t.columns.length*110}} dataSource={t.rows} columns={[{title:'成分',dataIndex:'name_zh',fixed:'left' as const,width:240},...t.columns.map((r,j)=>({title:<Tooltip title={`${r.target_id}；${r.quality_zh}`}>{r.symbol} · {r.candidate_grade}</Tooltip>,key:r.target_id,width:110,render:(_:unknown,_row:DockingReviewCompound,index:number)=><Tooltip title={t.cells[index][j].reason_zh}><span>{t.cells[index][j].score===null?'NA':t.cells[index][j].score!.toFixed(2)}</span></Tooltip>}))]}/><p className="small mono">结果版本：{m.result_version}</p></>}
 <Collapse size="small" items={[{key:'roster',label:'查看本轮展示名单及截取范围',children:<><p>热图成分：{h.rows.map(r=>r.name_zh).join('、')}</p><p>热图受体：{h.columns.map(r=>r.symbol+'（'+r.candidate_grade+'；'+r.quality_zh+'）').join('、')}</p><p>扩展成分：{t.rows.map(r=>r.name_zh).join('、')}</p><p>扩展受体：{t.columns.map(r=>r.symbol+'（'+r.candidate_grade+'；'+r.quality_zh+'）').join('、')}</p></>}]}/>
 </section>
}
