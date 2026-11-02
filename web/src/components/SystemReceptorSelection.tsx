// 展示服务端已归档的本批最终名单，保持原顺序，不计算名单或提交决定。
import {Alert, Button, Table, Tag} from 'antd';
import type {SystemReceptorSelectionInfo} from '../api/types';
import {hrefFor} from '../lib/route';

/** 最终名单与全网候选统计分开，缺少归档时不显示零项或推算组合。 */
export default function SystemReceptorSelection({studyId,info}:{studyId:string;info:SystemReceptorSelectionInfo}) {
 const modes={degree:'Degree',bc_cc:'BC＋CC',dual_ab:'双分支A/B'};
 return <section className="card stack" id="system-receptor-selection" style={{scrollMarginTop:90,gap:12}}>
  <h2>本批最终受体名单</h2>
  <Alert type={info.archive_state==='source_changed'?'warning':'info'} showIcon message={info.message_zh}/>
  {info.archive_state==='archived'&&<>
   <div style={{display:'flex',flexWrap:'wrap',gap:8}}>
    {info.mode&&<Tag>{modes[info.mode]}</Tag>}
    <Tag>目标 {info.requested_count} 项</Tag><Tag>实际 {info.actual_count} 项</Tag>
    {info.boundary_ties_retained&&<Tag>保留边界并列</Tag>}
   </div>
   {info.pair_count!==null&&<p>本批固定范围：{info.compound_count}个成分，{info.actual_count}个受体，共{info.pair_count}个组合。</p>}
   <Table aria-label="本批系统最终受体名单" size="small" rowKey="target_id" pagination={false}
    scroll={{x:680}} dataSource={info.selected} columns={[
     {title:'顺序',dataIndex:'selection_order',width:65},
     {title:'受体',dataIndex:'symbol',width:120},
     {title:'HGNC编号',dataIndex:'target_id',width:130},
     {title:'组别',dataIndex:'candidate_grade',width:70,render:v=>v??'未分组'},
     {title:'Degree',dataIndex:'degree',width:80},
     {title:'BC',dataIndex:'bc',width:100,render:v=>v==null?'—':<span title={String(v)}>{Number(v).toPrecision(5)}</span>},
     {title:'CC',dataIndex:'cc',width:100,render:v=>v==null?'—':<span title={String(v)}>{Number(v).toPrecision(5)}</span>},
    ]} locale={{emptyText:'本批实际筛选结果为空，原规则和范围保留。'}}/>
  </>}
  <p className="small muted" style={{margin:0}}>{info.scope_note_zh}</p>
  <Button href={hrefFor({page:'system-pipeline',studyId})}>查看统一执行进度</Button>
 </section>;
}
