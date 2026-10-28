// 文件用途：显示本研究建档时固定的方案和资料快照，与后续草稿区分。
import { Alert, Button, Collapse, Descriptions } from 'antd';
import { api } from '../api/client';
import type { CreationPlanInfo } from '../api/types';
import CreationMaterials from './CreationMaterials';

/** 读取服务端方案与原预检；本组件不写方案、不提交复核或计算。 */
export default function CreationPlan({studyId,info}:{studyId:string;info:CreationPlanInfo}) {
  return <section className="card stack" id="creation-plan-summary">
    <h2 style={{fontSize:17}}>本研究的初始方案与资料预检</h2>
    <Alert type="info" showIcon message={info.reason_zh}/>
    <Descriptions size="small" column={1} items={[
      {key:'mode',label:'初始建档模式',children:info.initial_plan.mode==='standard'?'标准版':'个性化版'},
      {key:'target',label:'初始目标范围',children:`${info.initial_plan.parameters['a06.component_count']} × ${info.initial_plan.parameters['a06.receptor_count']}`},
      {key:'plan',label:'初始方案编号',children:<span style={{overflowWrap:'anywhere'}}>{info.initial_plan_id}</span>},
      {key:'hash',label:'初始方案指纹',children:<span className="mono" style={{overflowWrap:'anywhere'}}>{info.initial_plan.parameter_hash}</span>},
      {key:'current',label:'当前A00绑定的草稿',children:info.current_plan_id?<span style={{overflowWrap:'anywhere'}}>{info.current_plan_id}</span>:'当前登记已变化，原方案留作历史；请重新核对草稿'},
    ]}/>
    <Button href={api.creationPlanExport(studyId)}>下载本研究方案与建档预检 JSON</Button>
    <Collapse items={[
      {key:'materials',label:'创建时资料快照（后续上传不改写该历史）',children:<CreationMaterials value={info.materials_at_creation}/>},
      {key:'parameters',label:'初始完整参数（只读）',children:<Descriptions column={1} size="small" items={Object.entries(info.initial_plan.parameters).map(([key,value])=>({key,label:key,children:String(value)}))}/>},
    ]}/>
  </section>;
}
