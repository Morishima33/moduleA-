// 各模块操作导航：只显示后端建议并定位已有区域，不提交计算或复核。
import {Alert, Button, Space, Tooltip, message} from 'antd';
import {useEffect, useRef} from 'react';
import type {ModuleView} from '../api/types';
import {hrefFor} from '../lib/route';

/** 沿用A02导航样式，保留每个模块独立的步骤及人工关口。 */
export default function ModuleOperationGuide({studyId, moduleId, info, pending = false, onLocate}: {
  studyId: string; moduleId: string; info: NonNullable<ModuleView['operation_guide']>; pending?: boolean; onLocate?: (target: string) => void;
}) {
  const navigationEpoch = useRef(0);
  useEffect(() => () => { navigationEpoch.current += 1; }, [studyId, moduleId]);
  const index = pending ? Math.max(0, info.steps.findIndex(step => step.key === 'scope')) : info.current_step - 1;
  const current = info.steps[index];
  /** 跳转只用于阅读；缺失区域明确提示，避免按钮无反馈。 */
  function locate(step: typeof current) {
    const epoch = ++navigationEpoch.current;
    if (step.href || step.module_id) {
      window.location.hash = step.href || hrefFor({page: 'study', studyId, moduleId: step.module_id!});
      return;
    }
    onLocate?.(step.target);
    const element = document.getElementById(step.target) || (step.target === 'a05-ranked-pathway-maps' ? document.getElementById('module-results') : null);
    if (!element) {message.info('页面内容已更新，请重新查看当前模块。'); return;}
    if (step.target !== 'a05-ranked-pathway-maps') {
      element.scrollIntoView({behavior: 'smooth', block: 'center'});
      return;
    }
    // 通路图上方有大型科研图片；首次解码会改变高度，先定位标题再在图片就绪后校正。
    element.scrollIntoView({behavior: 'smooth', block: 'start'});
    const controller = new AbortController();
    const cancel = () => { navigationEpoch.current += 1; controller.abort(); };
    for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) window.addEventListener(event, cancel, {once: true, passive: true, signal: controller.signal});
    const precedingImages = Array.from(document.images).filter(img => element.contains(img) || !!(img.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING));
    let timer: ReturnType<typeof setTimeout>;
    const deadline = new Promise<void>(resolve => { timer = setTimeout(resolve, 8000); });
    void Promise.race([Promise.allSettled(precedingImages.map(img => img.decode())), deadline]).then(() => {
      if (navigationEpoch.current === epoch && element.isConnected) {
        requestAnimationFrame(() => {
          if (navigationEpoch.current === epoch && element.isConnected) element.scrollIntoView({behavior: 'instant', block: 'start'});
        });
      }
    }).finally(() => { clearTimeout(timer); controller.abort(); });
  }
  return <section className="card" id="module-operation-guide" aria-label={`${moduleId}操作顺序`}>
    <h2 style={{marginTop: 0}}>{moduleId}操作顺序</h2>
    <Space wrap style={{marginBottom: 12}}>{info.steps.map((step, i) => <Tooltip key={step.key} title={step.detail_zh}>
      <Button style={{height: 'auto', minHeight: 36, whiteSpace: 'normal', textAlign: 'left'}} type={i === index ? 'primary' : 'default'} onClick={() => locate(step)}>{i + 1}. {step.label_zh}</Button>
    </Tooltip>)}</Space>
    <Alert showIcon type={pending ? 'warning' : 'info'} message={pending ? '展示选择尚未保存或正在应用，请先完成范围确认' : `建议：第${index + 1}步 · ${current.label_zh}`} description={<>
      <p style={{margin: 0}}>{pending ? '未保存选择不会改变已归档范围。确认清单并等待应用后，再查看图表及确认版式。' : info.note_zh}</p>
      {(pending || current.detail_zh !== info.note_zh) && <p style={{margin: '6px 0 0'}}>{current.detail_zh}</p>}
      <Button style={{marginTop: 10, height: 'auto', minHeight: 32, whiteSpace: 'normal'}} onClick={() => locate(current)}>前往{current.label_zh}</Button>
    </>}/>
  </section>;
}
