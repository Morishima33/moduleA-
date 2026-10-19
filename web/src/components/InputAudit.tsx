// 输入数量溯源：区分成分、关系记录与基因，并解释本运行实际采用的范围及来源。
import {Alert, Button, Collapse, Descriptions, Space} from 'antd';
import type {ModuleView} from '../api/types';
import {hrefFor} from '../lib/route';

/** 只展示后端归档事实，入口只定位或切页，不修改来源和范围。 */
export default function InputAudit({studyId, moduleId, info}: {studyId: string; moduleId: string; info: NonNullable<ModuleView['input_audit']>}) {
  const f = info.formula, d = info.disease;
  /** 本页直接定位已有输入区，跨模块进入同一研究的当前版本。 */
  function inspect(target: string) {
    const anchor = target === 'A01' ? 'module-source-inputs' : 'disease-scope-review';
    if (target === moduleId) document.getElementById(anchor)?.scrollIntoView({behavior: 'smooth', block: 'start'});
    else window.location.hash = hrefFor({page: 'study', studyId, moduleId: target});
  }
  return <section className="card stack" id="module-input-audit" aria-label="输入来源与数量核对">
    <h2 style={{margin: 0}}>输入来源与数量核对</h2>
    {f && <Descriptions size="small" column={{xs: 1, sm: 2}} items={[
      {key: 'compounds', label: f.component_label_zh, children: f.component_count ?? '未记录'},
      {key: 'genes', label: '方剂标准化靶点基因', children: f.target_count ?? '尚未标准化'},
      {key: 'sources', label: '当前实际成分来源', children: f.sources.join('、')},
      {key: 'relations', label: '标准化成分—基因关系', children: f.relationship_count ?? '未记录'},
    ]}/>}
    {f && <p className="small muted" style={{margin: 0}}>成分数、成分—基因关系条数和不同基因数是三个口径；同一基因可对应多个成分或药味，不能相加当作独立基因。</p>}
    {d && <><Descriptions size="small" column={{xs: 1, sm: 2}} items={[
      {key: 'records', label: '疾病原始候选记录', children: d.candidate_count ?? '未记录'},
      {key: 'genes', label: '疾病标准化靶点基因', children: d.target_count ?? '尚未标准化'},
    ]}/><p className="small" style={{margin: 0}}>本运行已保存的范围：{d.scope_counts.map(row => `${row.label_zh} ${row.count}组／${row.records}条记录`).join('；')}。原始记录数不等于标准化后基因数。</p></>}
    {info.checks.map((check, i) => <Alert key={i} showIcon type={check.level} message={check.label_zh} description={<>
      <p style={{margin: 0}}>{check.detail_zh}</p>
      {check.module_id && check.level === 'warning' && <Button style={{marginTop: 8, height: 'auto', whiteSpace: 'normal'}} onClick={() => inspect(check.module_id!)}>{check.module_id === 'A01' ? '前往A01补齐来源并核对数量' : '前往A02核对疾病范围'}</Button>}
    </>}/>)}
    <Collapse size="small" items={[{key: 'versions', label: '查看本运行绑定的输入版本', children: <Space direction="vertical">
      {f && <span className="small" style={{overflowWrap: 'anywhere'}}>A01：{f.run_id} <a href={hrefFor({page: 'study', studyId, moduleId: 'A01', runId: f.run_id})}>查看绑定版本</a></span>}
      {d && <span className="small" style={{overflowWrap: 'anywhere'}}>A02：{d.run_id} <a href={hrefFor({page: 'study', studyId, moduleId: 'A02', runId: d.run_id})}>查看绑定版本</a></span>}
    </Space>}]}/>
  </section>;
}
