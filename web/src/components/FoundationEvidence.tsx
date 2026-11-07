// 文件用途：只读展示同批准备依据及经核验的Top-1构象，不提交确认、计算或复核。
import { Alert, Collapse, Table } from 'antd';
import type { FoundationEvidence as Evidence } from '../api/types';

/** 保留未记录与已核查空清单的区别，原始坐标残基代码保持不猜译。 */
function RecordedList({ label, items }: { label:string; items:string[]|null }) {
  return <div><strong>{label}：</strong>{items===null?'未记录或未完成核查':items.length===0?'原核查范围内未列出':
    <ul style={{margin:'4px 0',paddingLeft:20}}>{items.map((s,i)=><li key={i}>{s||'原件条目未提供可读标识'}</li>)}</ul>}</div>;
}

/** 搜索盒仅格式化服务端原值，不推算位点、大小或质控通过。 */
function Box({ box }: { box:{center:number[];size:number[]}|null }) {
  return <div><strong>本次搜索盒：</strong>{box?<>中心 {box.center.join('，')} Å；尺寸 {box.size.join(' × ')} Å</>:'原记录未提供'}</div>;
}

/** 链接全部采用服务端核验后的同源下载地址。 */
function Downloads({ items }: { items:{label_zh:string;name:string;url:string;sha256:string}[] }) {
  return <div style={{display:'flex',flexWrap:'wrap',gap:'6px 18px'}}>{items.map((item,i)=><a key={i} href={item.url} download title={item.name}>{item.label_zh}</a>)}</div>;
}

/** 正常对象无须逐项确认；异常依据集中展示，失配时不显示构象链接。 */
export default function FoundationEvidence({ data }: { data:Evidence }) {
  if(data.integrity==='failed') return <Alert type="error" showIcon message="准备或构象证据核验未通过" description={<>{data.message_zh}<br/>{data.error_zh}</>}/>;
  return <section className="card" aria-label="准备证据与原始构象">
    <h2 style={{fontSize:17,margin:'0 0 8px'}}>准备证据与原始构象</h2>
    <p className="small muted" style={{margin:'0 0 12px'}}>{data.message_zh}</p>
    <Collapse items={[
      {key:'preparation',label:'查看受体准备依据与异常',children:<Table dataSource={data.preparation}
        rowKey={r=>`${r.target_id}-${r.attempt}`} size="small" scroll={{x:750}}
        pagination={{pageSize:10,showSizeChanger:false}} columns={[
          {title:'受体',dataIndex:'symbol'}, {title:'结构',dataIndex:'structure_id',render:v=>v||'未取得'},
          {title:'尝试',dataIndex:'attempt'}, {title:'当前状态',dataIndex:'state_zh'}, {title:'类别',dataIndex:'quality'},
          {title:'本次尝试依据',dataIndex:'attempt_reason_zh',width:280},
        ]} expandable={{expandedRowRender:row=><div className="stack" style={{gap:8}}>
          <div><strong>原受体结果：</strong>{row.reason_zh}</div>
          <div><strong>蛋白链：</strong>{row.chains?.join('，')||'未记录'}；<strong>UniProt：</strong>{row.uniprot||'未记录'}</div>
          <div><strong>共晶参考配体：</strong>{row.reference?`${row.reference.reference_code} / ${row.reference.reference_chain}链 / ${row.reference.reference_sequence}`:'未记录参考配体'}；<strong>Top-1重对接RMSD：</strong>{row.top1_rmsd===null?'未记录':`${row.top1_rmsd} Å`}</div>
          <div><strong>参考配体接触链：</strong>{row.reference_contacts?<>{row.reference_contacts.chains.join('，')||'原核查未列出'}；{row.reference_contacts.basis_zh}</>:'原记录未核定；不以目标链或配体所在链代替'}</div>
          <div><strong>口袋完整性：</strong>{row.pocket_complete_zh}；<strong>必要环境：</strong>{row.environment_resolved_zh}</div>
          <RecordedList label="口袋缺原子记录" items={row.missing_atoms_zh}/>
          <RecordedList label="邻接未观测残基记录" items={row.unobserved_residues_zh}/>
          <RecordedList label="盒内伴随组分及其他聚合物" items={row.environment_components_zh}/>
          <p className="small muted" style={{margin:0}}>{row.environment_note_zh}</p>
          <Box box={row.box}/><Downloads items={row.downloads}/>
        </div>}}/>},
      ...(data.scores.length?[{key:'scores',label:'查看逐组合Top-1构象与来源',children:<>
        <p className="small muted">评分保持原始精度。只提取已核验的原始MODEL 1；全部模式另列下载，不改选其他姿势。</p>
        <Table dataSource={data.scores} rowKey={r=>`${r.compound_id}-${r.target_id}`} size="small" scroll={{x:850}}
          pagination={{pageSize:10,showSizeChanger:false}} columns={[
            {title:'成分',dataIndex:'compound_name'}, {title:'受体',dataIndex:'symbol'}, {title:'状态',dataIndex:'state_zh'},
            {title:'Vina评分（kcal/mol）',dataIndex:'score',render:v=>v===null?'NA':String(v)}, {title:'类别',dataIndex:'quality'},
            {title:'原始构象',render:(_,row)=>row.top1_download_url?<a href={row.top1_download_url} download>下载Top-1</a>:row.reason_zh||'无可下载构象'},
          ]} expandable={{expandedRowRender:row=><div className="stack" style={{gap:8}}>
            {row.reason_zh&&<div><strong>原始原因：</strong>{row.reason_zh}</div>}
            <Box box={row.box}/>
            {row.context_download_url&&<a href={row.context_download_url} download>下载评分、搜索盒与原件指纹说明</a>}
            <Downloads items={row.downloads}/>
          </div>}}/>
      </>}]:[]),
    ]}/>
  </section>;
}
