// 文件用途：真实显示创建前资料核对，不用用户自填勾选把缺件标成齐备。
import { Alert, Collapse, Tag } from 'antd';
import type { CreationMaterials as Materials } from '../api/types';

/** 初次预检和研究页共用资料清单，历史快照由调用方明确标注。 */
export default function CreationMaterials({value}:{value:Materials}) {
  return <div className="stack" id="creation-materials">
    <Alert type={value.references_verified?'info':'warning'} showIcon message={value.reason_zh}/>
    <Collapse defaultActiveKey={['references']} items={[
      {key:'references',label:'本机共享资料实际核验',children:<div className="stack">{value.references.map(row=><div key={row.id}>
        <strong>{row.label_zh}</strong> <Tag color={row.status==='verified'?'green':'orange'}>{row.status==='verified'?'指纹一致':row.status==='missing'?'缺少资料':'核验未通过'}</Tag>
        <div className="small muted" style={{overflowWrap:'anywhere'}}>{row.detail_zh}</div>
      </div>)}</div>},
      {key:'sources',label:'本研究专属来源（建档后按研究绑定）',children:<div className="stack">{value.research_sources.map(row=><div key={row.database}>
        <strong>{row.database}</strong> <Tag>尚未提供</Tag><div className="small muted">{row.reason_zh}</div>
      </div>)}</div>},
    ]}/>
  </div>;
}
