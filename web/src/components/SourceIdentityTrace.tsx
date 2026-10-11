// 原始身份冲突与已归档的逐行映射供核查；没有重新计算或批准入口。
import {Collapse,Table} from 'antd';
import type {SourceIdentityTrace as TraceInfo} from '../api/types';

export default function SourceIdentityTrace({name,info}:{name:string;info:TraceInfo}){
 const identities=[{source:'HERB批量表',cid:info.bulk.PubChem_id,formula:info.bulk.Molecular_formula,key:info.bulk.InChIKey,cas:info.bulk.CAS_id},{source:'HERB原始详情',cid:info.detail['PubChem id'],formula:info.detail['Molecule formula'],key:'详情未提供完整结构键',cas:info.detail['CAS id']},...info.official.map(r=>({source:'PubChem官方属性',cid:r.cid,formula:r.properties.MolecularFormula,key:r.properties.InChIKey,cas:'—'}))];
 return <Collapse size="small" items={[{key:'identity-source',label:`${name}：查看身份冲突与${info.raw_rows}条靶点追溯`,children:<>
 <p>原始关系 {info.raw_rows} 条 → 归档标准关系 {info.normalized_rows} 条、不同靶点 {info.unique_targets} 个 → 当前交集 {info.intersection_targets} 个；其余 {info.outside_intersection} 个不在交集。这个数量能追溯，化学身份与靶点归属仍待补。</p>
 <Table rowKey={(_,i)=>String(i)} size="small" pagination={false} dataSource={identities} scroll={{x:700}} columns={[{title:'身份视图',dataIndex:'source'},{title:'CID',dataIndex:'cid'},{title:'分子式',dataIndex:'formula'},{title:'完整结构键',dataIndex:'key'},{title:'CAS（归档）',dataIndex:'cas'}]}/>
 {info.live_confirmation?.same_as_archived&&<p className="small">本次官方HERB详情与原归档响应一致，冲突仍存在；官方CAS查询对应CID {info.live_confirmation.cas_query_cid}。保留待补，不直接改编号或重新归属靶点。</p>}
 <Collapse size="small" items={[{key:'target-trace',label:'逐行查看靶点来源与交集归属',children:<Table rowKey="source_row" size="small" pagination={{pageSize:25,showSizeChanger:false}} dataSource={info.trace} scroll={{x:800,y:400}} columns={[{title:'来源行',dataIndex:'source_row',width:70},{title:'原始靶点',dataIndex:'raw_target_id',width:150},{title:'原始基因',dataIndex:'raw_symbol',width:100},{title:'HGNC',dataIndex:'target_id',width:130},{title:'标准基因',dataIndex:'symbol',width:100},{title:'当前交集',dataIndex:'in_current_intersection',width:90,render:(v:boolean)=>v?'在交集':'不在交集'},{title:'来源数据库条目',dataIndex:'database_source_titles',render:(v:string[])=>v.join('；')}]}/>}]}/>
 </>}]}/>;
}
