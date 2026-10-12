// 展示官方结构摘要和真实缺口，历史通过与失败均不代替本次质控。
import {Alert,Collapse,Table,Tag} from 'antd';
import type {ReceptorMetadataReview,ReceptorMetadataRow,ReceptorMetadataCandidate} from '../api/types';

// 每个受体可展开查看候选链、片段长度、共晶组分与同源历史限制。
function details(row:ReceptorMetadataRow){
 return <><p className="small">{row.identity_state_zh}；UniProt全长 {row.sequence_length} 残基。</p>
 {row.historical&&<Alert type={row.historical.status_zh.startsWith('失败')?'warning':'info'} message={'历史 '+row.historical.pdb_id+'：'+row.historical.status_zh+'（不能视为本次通过）'} description={row.historical.reason_zh}/>}
 {row.plan_proposal&&<Alert type="warning" message={row.plan_proposal.route_zh+'：'+(row.plan_proposal.first_pdb_id||row.plan_proposal.second_pdb_id||'待补位点／环境')} description={<><p>{row.plan_proposal.domain_zh}；{row.plan_proposal.reference_zh}</p><p>{row.plan_proposal.reason_zh}</p><p>待核查：{row.plan_proposal.pending_zh.join('；')}</p>{row.plan_proposal.alternatives.length>0&&<p>备用资料：{row.plan_proposal.alternatives.map(a=><span key={a.pdb_id}><a href={a.url} target="_blank" rel="noreferrer">{a.pdb_id}</a>（{a.state_zh}）；</span>)}</p>}{row.plan_proposal.model_metadata?.map(x=><p key={x.entry_id}>{x.entry_id}，序列{x.sequence_start}—{x.sequence_end}，数据库版本{x.model_version}：{x.state_zh}</p>)}</>}/>}
 <p className="small">{row.limitations_zh}</p>
 <Table<ReceptorMetadataCandidate> rowKey="pdb_id" size="small" dataSource={row.candidates} pagination={{pageSize:5,showSizeChanger:false}} scroll={{x:780}}
 columns={[{title:'PDB / 方法',render:(_,r)=><><a href={r.url} target="_blank" rel="noreferrer">{r.pdb_id}</a><div className="tiny">{r.methods.join('；')}；{r.resolution.length?r.resolution.join(' / ')+' Å':'分辨率未提供'}</div>{r.source_rejected&&<Tag color="warning">来源核查不采用：{r.source_reason_zh}</Tag>}{r.blocked_previous_failure&&<Tag color="warning">已有失败：不可换口袋绕过</Tag>}</>},
 {title:'目标作者链 / 长度',render:(_,r)=>r.target_chains.map(c=><div key={c.entity_id}>{c.chains.join('、')}；{c.length} 残基<div className="tiny muted">{c.fragment||c.description}；突变数 {c.mutation_count??"未提供"}；全长覆盖 {c.reference_coverage==null?"未提供":(c.reference_coverage*100).toFixed(1)+"%"}</div></div>)},
 {title:'共晶组分（参考适用性待核查）',render:(_,r)=>r.ligands.length?r.ligands.map(c=><div key={c.code}>{c.code}；作者链 {c.author_chains.join('、')}<div className="tiny muted">{c.name}</div></div>):'无非聚合物组分'},
 {title:'结构标题与未决事项',render:(_,r)=><div className="small">{r.title}<p>{r.review_state_zh}</p></div>}]}/>
 <p className="small">第二遍仍优先独立实验结构；<a href={row.alphafold_url} target="_blank" rel="noreferrer">已有AlphaFold模型资料入口</a>仅供后续核查，本轮未获取模型或评估口袋。</p></>;
}

// 资料层不能批量批准；确认按钮保留在下方完整两遍方案区。
export default function ReceptorMetadata({review}:{review:ReceptorMetadataReview}){
 return <div id="a06-receptor-metadata"><h3>本轮受体资料核查</h3>
 <Alert type="info" message={review.receptors.some(r=>r.source_audit)?"官方摘要与原件核查已整理；方案在顶部集中窗口核对":"官方身份与结构摘要已整理；请展开证据核查，再填写两遍方案"} description="来源核查不表示结构质控通过。必要环境、口袋完整性、预测口袋与本次重对接仍待核验。"/>
 <Table<ReceptorMetadataRow> rowKey="target_id" size="small" dataSource={review.receptors} pagination={false} scroll={{x:720}}
 expandable={{expandedRowRender:details,expandRowByClick:true}}
 columns={[{title:'基因 / HGNC',render:(_,r)=><>{r.symbol}<div className="tiny muted">{r.target_id}</div></>},{title:'梯队',dataIndex:'candidate_grade',render:(v:string)=><Tag>{v}</Tag>},{title:'人类UniProt',render:(_,r)=><a href={r.identity_url} target="_blank" rel="noreferrer">{r.uniprot}</a>},{title:'实验结构摘要',render:(_,r)=><>{r.inspected_entry_count} 条已查看<div className="tiny muted">检索返回 {r.search_total} 条；已查看范围有限</div></>},{title:'初步方案',render:(_,r)=>r.plan_proposal?<>{r.plan_proposal.first_pdb_id||r.plan_proposal.second_pdb_id||'待补'}<div className="tiny muted">{r.plan_proposal.route_zh}</div></>:'待整理'},{title:'当前状态',render:(_,r)=><Tag>{r.current_qc_zh}</Tag>}]}/>
 <Collapse size="small" items={[{key:'limits',label:'查看两遍核查与方案确认的区别',children:<p className="small">{review.note_zh} 第一遍未通过对象才进入第二遍；历史失败须另选独立结构，不通过改换口袋绕过。全选只用于下方字段完整的人工方案，资料摘要不自动勾选或代签。</p>}]}/></div>;
}
