// 文件用途：新建模式的完整参数控件，默认值、范围、保护项都来自统一服务端目录。
import { Collapse, InputNumber, Select, Switch, Tag } from 'antd';
import type { AnalysisParameterCatalog, PlanValue } from '../api/types';

/** 只在个性化模式编辑值；服务端负责最终类型、范围和交叉约束校验。 */
export default function PlanCreationFields({catalog,mode,values,disabled,onChange}:{
  catalog:AnalysisParameterCatalog;mode:'standard'|'personalized';values:Record<string,PlanValue>;
  disabled:boolean;onChange:(key:string,value:PlanValue)=>void;
}) {
  /** 控件跟随原目录类型，整数数量使用1—25数值输入而非固定选项。 */
  function field(key:string) {
    const definition=catalog.parameters[key]; const detail=catalog.preview.details[key];
    const inactive=!!definition.active_when&&Object.entries(definition.active_when).some(([k,v])=>values[k]!==v);
    const locked=disabled||mode==='standard'||inactive;
    const value=values[key];
    return <div key={key} className={'plan-field'+(inactive?' inactive':'')} data-parameter={key}>
      <label>{definition.label}{inactive&&<span className="small muted">（仅A/B模式）</span>}</label>
      {definition.type==='boolean'?<Switch aria-label={definition.label} checked={Boolean(value)} disabled={locked}
        checkedChildren="纳入" unCheckedChildren="不纳入" onChange={v=>onChange(key,v)}/>:definition.choices?
        <Select aria-label={definition.label} style={{width:'100%'}} value={value as string|number} disabled={locked}
          options={definition.choices.map(v=>({value:v,label:detail?.choices_zh?.[String(v)]||String(v)}))} onChange={v=>onChange(key,v)}/>:
        <InputNumber aria-label={definition.label} style={{width:'100%'}} disabled={locked} value={typeof value==='number'?value:null}
          min={definition.min??definition.min_exclusive} max={definition.max} precision={definition.type==='integer'?0:undefined}
          step={definition.type==='integer'?1:definition.resolution||.01} addonAfter={definition.unit||undefined}
          onChange={v=>onChange(key,v===null?'':v)}/>}
      <div className="small muted plan-field-help">{detail?.help_zh}</div>
    </div>;
  }
  return <div className="stack">
    <Collapse defaultActiveKey={['a06']} items={catalog.preview.groups.map(group=>({key:group.key,
      label:<span>{group.title_zh} <Tag>{group.status_zh}</Tag></span>, children:<>
        <p className="small muted">{group.description_zh}</p><div className="plan-field-grid">{group.fields.map(field)}</div>
        {!!group.advanced_fields.length&&<Collapse style={{marginTop:12}} items={[{key:'advanced',label:'更多参数与方法设置',
          children:<div className="plan-field-grid">{group.advanced_fields.map(field)}</div>}]}/>}
      </>}))}/>
    <Collapse items={[{key:'fixed',label:'固定研究规则（只读）',children:<ul>{catalog.preview.fixed_rules_zh.map(rule=><li key={rule}>{rule}</li>)}</ul>}]}/>
  </div>;
}
