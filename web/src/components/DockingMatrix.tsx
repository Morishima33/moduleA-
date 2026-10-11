// 同一归档批次的热图和扩展表，色值与完整覆盖校验由服务端提供。
import {Alert,Collapse,Table,Tooltip} from 'antd';
import type {DockingReviewInfo,DockingReviewCompound} from '../api/types';

export default function DockingMatrix({info}:{info:DockingReviewInfo}){
 const m=info.matrix;
 if(!info.enabled||!m)return <section className="card"><h2>对接图表展示</h2><Alert type="warning" message={info.reason_zh}/></section>;
 const h=m.heatmap,t=m.table;
 return <section className="card" id="a06-matrix"><h2>重点热图与扩展结合能表</h2>
 <p>热图 {h.rows.length}×{h.columns.length}；表格 {t.rows.length}×{t.columns.length}；完整记录 {m.full_pair_count} 组。</p>
 <p className="small">同批Vina Top-1评分（kcal/mol）。受体A优先、组内按完整网络Degree降序；截断并列按HGNC编号稳定排列，完整并列及其余组合仍留存。A/B候选级别与严格／探索质控分别记录。</p>
 {!m.ready?<Alert type="info" showIcon message={m.status_zh} description="尚无本轮有效评分，不显示热图色块或填充示例数值。名单确认不代替真实计算授权。"/>:<>
 <h3>重点结合能热图</h3><div style={{overflowX:'auto'}}><svg role="img" aria-label="重点结合能热图" width={220+h.columns.length*90} height={100+h.rows.length*46}>
 {h.columns.map((r,j)=><text key={r.target_id} x={245+j*90} y={30} textAnchor="middle" fontSize={12}>{r.symbol} · {r.candidate_grade}</text>)}
 {h.rows.map((r,i)=><g key={r.compound_id}><text x={210} y={76+i*46} textAnchor="end" fontSize={12}>{r.name_zh}</text>{h.cells[i].map((c,j)=><g key={c.target_id}><title>{r.name_zh} × {h.columns[j].symbol}；{h.columns[j].quality_zh}；{c.reason_zh}</title><rect x={220+j*90} y={50+i*46} width={88} height={44} fill={c.color}/><text x={264+j*90} y={76+i*46} textAnchor="middle" fill={c.text_color} fontSize={12}>{c.score===null?'NA':c.score.toFixed(2)}</text></g>)}</g>)}
 </svg></div><p className="small">评分越负蓝色越深；NA为灰色，保留原因。颜色范围取完整同批评分；对接评分不能直接证明药效。</p>
 <h3>扩展结合能表</h3><Table<DockingReviewCompound> rowKey="compound_id" size="small" pagination={false} scroll={{x:240+t.columns.length*110}} dataSource={t.rows} columns={[{title:'成分',dataIndex:'name_zh',fixed:'left' as const,width:240},...t.columns.map((r,j)=>({title:<Tooltip title={`${r.target_id}；${r.quality_zh}`}>{r.symbol} · {r.candidate_grade}</Tooltip>,key:r.target_id,width:110,render:(_:unknown,_row:DockingReviewCompound,index:number)=><Tooltip title={t.cells[index][j].reason_zh}><span>{t.cells[index][j].score===null?'NA':t.cells[index][j].score!.toFixed(2)}</span></Tooltip>}))]}/><p className="small mono">结果版本：{m.result_version}</p></>}
 <Collapse size="small" items={[{key:'roster',label:'查看本轮展示名单及截取范围',children:<><p>热图成分：{h.rows.map(r=>r.name_zh).join('、')}</p><p>热图受体：{h.columns.map(r=>r.symbol+'（'+r.candidate_grade+'；'+r.quality_zh+'）').join('、')}</p><p>扩展成分：{t.rows.map(r=>r.name_zh).join('、')}</p><p>扩展受体：{t.columns.map(r=>r.symbol+'（'+r.candidate_grade+'；'+r.quality_zh+'）').join('、')}</p></>}]}/>
 </section>
}
