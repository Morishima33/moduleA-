// A02操作顺序导航：当前步骤与说明使用后端事实，点击只定位，不提交科研操作。
import { Alert, Button, Space } from 'antd';
import type { ModuleView } from '../api/types';
import { hrefFor } from '../lib/route';

/** 固定操作顺序；未保存范围修改属于本地表单提示，不改变后端模块状态。 */
export default function DiseaseWorkflowGuide({ studyId, info, scopeDirty }: {studyId: string; info: NonNullable<ModuleView['disease_workflow']>; scopeDirty: boolean}) {
  const steps = [
    ['检查五库资料', 'disease-source-inputs'], ['确认疾病范围', 'disease-scope-review'],
    ['程序核查身份', 'normalization-review'], ['确认处理并生成结果', 'normalization-confirmation'],
    ['整体复核', 'module-review-panel'], ['查看A03交集', 'A03'],
  ];
  function locate(target: string) {
    if (target === 'A03') { window.location.hash = hrefFor({page: 'study', studyId, moduleId: 'A03'}); return; }
    const element = document.getElementById(target) || (target === 'normalization-confirmation' ? document.getElementById('normalization-review') : null);
    element?.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
  return <section className="card" id="disease-workflow-guide">
    <h2 style={{marginTop: 0}}>A02操作顺序</h2>
    <Space wrap style={{marginBottom: 12}}>{steps.map(([label, target], index) => <Button key={target} type={(scopeDirty ? 2 : info.current_step) === index + 1 ? 'primary' : 'default'} onClick={() => locate(target)}>{index + 1}. {label}</Button>)}</Space>
    <Alert showIcon type={scopeDirty ? 'warning' : 'info'} message={scopeDirty ? '范围修改尚未保存，请先保存第2步' : `当前：第${info.current_step}步 · ${steps[info.current_step - 1][0]}`} description={<>
      <p style={{margin: 0}}>{scopeDirty ? '当前身份预览对应已保存的范围。保存修改后，再重新核查身份。' : info.note_zh}</p>
      <Button style={{marginTop: 10}} onClick={() => locate(scopeDirty ? 'disease-scope-review' : info.next_target)}>{scopeDirty ? '前往保存范围' : info.next_label_zh}</Button>
    </>} />
  </section>;
}
