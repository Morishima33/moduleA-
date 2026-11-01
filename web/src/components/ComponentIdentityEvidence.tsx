// 本版待核证据按原字段展示；明确载入只读清单，不触发补查、排除或复核。
import {Alert,Button,Collapse,Descriptions,Input,Space,Table} from 'antd';
import {useState} from 'react';
import {api,errorText} from '../api/client';
import type {ComponentIdentityEvidence as Evidence} from '../api/types';

const KINDS:Record<string,string>={protein_query:'TCMSP原蛋白查询',source_without_target:'原表缺靶点字段',source_identity:'来源身份待核'};
const STATES:Record<string,string>={archived_success:'原成功响应已归档',not_archived:'未登记本查询原文',not_applicable:'本记录不适用蛋白查询'};

/** 清单只来自服务器当前版本；页面加载不执行任务或自动确认。 */
export default function ComponentIdentityEvidence({studyId}:{studyId:string}){
 const [value,setValue]=useState<Evidence|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[query,setQuery]=useState('');
 async function load(){setLoading(true);setError('');setValue(null);try{setValue(await api.componentIdentityEvidence(studyId));}catch(e){setError(errorText(e));}finally{setLoading(false);}}
 const rows=value?.units.filter(row=>!query||[row.database,row.raw_name,...row.raw_target_ids].join(' ').toLowerCase().includes(query.toLowerCase()))||[];
 return <section className="card" id="component-identity-evidence">
  <h2>待核原件与官方响应</h2>
  <p>按本版原记录归并重复查询，保留每条问题及来源。这里只查看与下载，原有待核和复核状态保持。</p>
  <Button onClick={load} loading={loading}>载入本版只读核对清单</Button>
  {error&&<Alert type="error" showIcon message={error} style={{marginTop:12}}/>}
  {value&&<div className="stack" style={{gap:12,marginTop:12}}>
   <Alert type="info" showIcon message={value.message_zh}/>
   {value.supported&&value.stats&&<>
    <Descriptions size="small" column={{xs:1,md:2}} items={[
     {key:'rows',label:'原待核记录',children:value.stats.source_rows},
     {key:'groups',label:'核对组',children:value.stats.display_groups},
     {key:'queries',label:'不同原蛋白查询',children:value.stats.protein_query_groups},
     {key:'missing',label:'原表缺靶点字段记录',children:value.stats.source_without_target_rows},
    ]}/>
    <Space wrap><Button href={value.export_json_url}>下载完整核对JSON</Button><Button href={value.export_csv_url}>下载逐记录CSV</Button></Space>
    <Input aria-label="搜索待核原始名称或编号" placeholder="按来源库、原名称或原编号筛选" value={query} onChange={e=>setQuery(e.target.value)}/>
    <Table rowKey="unit_id" size="small" dataSource={rows} scroll={{x:760}} pagination={{pageSize:10,showSizeChanger:false}}
     columns={[{title:'来源与类别',render:(_,row)=><>{row.database}<br/>{KINDS[row.kind]||row.kind}</>},
      {title:'原名称／编号',render:(_,row)=><span style={{overflowWrap:'anywhere'}}>{row.raw_name||'原表未提供'}<br/>{row.raw_target_ids.join('、')}</span>},
      {title:'原记录数',dataIndex:'record_count'},
      {title:'原处理原因',dataIndex:'original_reason_zh'},
      {title:'原响应条目数',render:(_,row)=>row.response_records??'不适用或未归档'}]}
     expandable={{expandedRowRender:row=><div className="stack" style={{gap:10}}>
      <Alert type="warning" message="原响应条目数和下列候选均不是已采用身份；不能按第一条或仅凭名称相近确认。"/>
      <p>{STATES[row.response_state]||row.response_state}</p>
      <Space wrap>{row.file_indices.map(index=>{const file=value.files[index];return <Button key={index} href={file?.url}>{file?.label_zh}</Button>;})}</Space>
      {row.query&&<p style={{overflowWrap:'anywhere'}}>原查询：{row.query}</p>}
      <Collapse items={[
       {key:'source',label:`查看全部 ${row.record_count} 条原问题字段`,children:<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:320,overflow:'auto'}}>{JSON.stringify(row.records,null,2)}</pre>},
       ...(row.protein_candidates.length?[{key:'candidates',label:'查看原官方响应中的候选字段（未采用）',children:<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:320,overflow:'auto'}}>{JSON.stringify(row.protein_candidates,null,2)}</pre>}]:[]),
      ]}/>
     </div>}}/>
   </>}
  </div>}
 </section>;
}
