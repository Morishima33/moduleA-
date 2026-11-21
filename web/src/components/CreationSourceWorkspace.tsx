// 文件用途：新建研究原页的方剂与疾病资料工作区，复用已有获取和原件上传入口。
import { Alert, Button, Tabs } from 'antd';
import { useApp } from '../lib/appContext';
import { hrefFor, navigate } from '../lib/route';
import SystemAcquisitionPanel from './SystemAcquisitionPanel';
import SystemDiseaseSourcesPanel from './SystemDiseaseSourcesPanel';

export type CreationSourceTarget = 'formula' | 'disease';

/** 已有独立研究编号后显示真实表单，切换资料类别时保留已填写的表单。 */
export default function CreationSourceWorkspace({studyId, initialTarget}: {
  studyId: string;
  initialTarget: CreationSourceTarget;
}) {
  const app = useApp();
  return <main className="home plan-preview-page" id="creation-source-workspace">
    <section className="card stack">
      <h1>研究已建档 · 补充本研究资料</h1>
      <p>方剂、疾病和初始方案已保存。现在可在本页获取原件或上传疾病资料，后台任务完成后会刷新实际状态。</p>
      <div style={{display:'flex', flexWrap:'wrap', gap:8}}>
        <Button href={hrefFor({page:'study', studyId, moduleId:'A00'})}>查看本研究登记</Button>
        {app.session?.capabilities.system_pipeline &&
          <Button type="primary" href={hrefFor({page:'system-pipeline', studyId})}>打开计算工作台</Button>}
      </div>
    </section>
    <Tabs activeKey={initialTarget} onChange={value=>navigate({
      page:'creation-sources', studyId, sourceSection:value==='formula'?'formula':'disease',
    })} items={[
      {key:'formula', label:'方剂资料', children:
        app.session?.capabilities.system_acquisition
          ? <SystemAcquisitionPanel studyId={studyId}/>
          : <Alert type="warning" showIcon message="当前服务未提供方剂原件获取入口，请查看本研究登记中的资料状态。"/>},
      {key:'disease', label:'疾病资料与原件上传', children:
        app.session?.capabilities.system_disease_acquisition
          ? <SystemDiseaseSourcesPanel studyId={studyId}/>
          : <Alert type="warning" showIcon message="当前服务未提供疾病原件入口，请查看本研究登记中的资料状态。"/>},
    ]}/>
  </main>;
}
