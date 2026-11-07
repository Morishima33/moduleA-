// 文件用途：逐项展示本批原始来源异常，不推算旧协议缺失的阶段、原因或补算资格。
import { Table } from 'antd';
import type { Special } from '../api/types';

const stages:Record<string,string>={name:'名称定位',identity:'来源身份核验',source_3d:'官方三维下载',
  coordinate_identity:'三维坐标身份核验',preparation:'配体参数化',receptor_source:'受体来源',
  pocket_environment:'口袋与必要环境质控',scoring:'评分执行'};
const objects:Record<string,string>={compound:'成分',receptor:'受体',pair:'对接组合'};

/** 仅显示服务端已归档字段，旧批未登记分类时保留原中文原因。 */
export default function SourceDiagnostics({ rows }: { rows:NonNullable<Special['source_diagnostics']> }) {
  return <section className="card" aria-label="来源异常明细">
    <h2 style={{fontSize:17,margin:'0 0 8px'}}>来源异常明细</h2>
    <p className="small muted">以下为本批归档的阶段、代码和原因。未登记的分类不推测；可重试标记不代表已补算或已通过。</p>
    <Table dataSource={rows} rowKey={(_,i)=>String(i)} size="small" scroll={{x:750}}
      pagination={{pageSize:10,showSizeChanger:false}} columns={[
        {title:'对象类型',dataIndex:'object_type',render:v=>objects[v]||v||'未登记'},
        {title:'对象编号',dataIndex:'object_id',render:v=>v||'未登记'},
        {title:'失败阶段（原登记）',dataIndex:'failure_stage',render:v=>stages[v]||v||'未登记'},
        {title:'原因代码',dataIndex:'failure_code',render:v=>v||'未登记'},
        {title:'可重试',dataIndex:'retryable',render:v=>v===true?'是':v===false?'否':'未登记'},
        {title:'具体原因',dataIndex:'reason_zh',width:320,render:v=>v||'原记录未提供'},
      ]}/>
  </section>;
}
