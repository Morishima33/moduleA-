// 文件用途：显示当前研究的实际保存位置及目录用途，路径由后端配置生成。
import { App as AntApp, Button } from 'antd';
import type { ProjectStorage as StorageInfo } from '../api/types';

/** 默认折叠目录清单，保持研究页简洁；用户可复制项目路径自行打开。 */
export default function ProjectStorage({ studyId, storage }: { studyId: string; storage?: StorageInfo }) {
  const { message } = AntApp.useApp();
  if (!storage) return null;
  const copyPath = async () => {
    try { await navigator.clipboard.writeText(storage.directory); message.success('项目路径已复制'); }
    catch { message.info('请选中下方路径并复制'); }
  };
  return (
    <details className="card" style={{ padding: '12px 14px' }}>
      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>项目文件夹</summary>
      <div className="small" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
        <span className="mono" style={{ overflowWrap: 'anywhere' }}>{studyId}</span>
        <div style={{ overflowWrap: 'anywhere', userSelect: 'text' }}>{storage.directory}</div>
        <Button size="small" style={{ alignSelf: 'flex-start' }} onClick={copyPath}>复制项目路径</Button>
        {storage.folders.map((row) => <span key={row.name}><span className="mono">{row.name}/</span>　{row.label_zh}</span>)}
        <span className="muted">本项目所有版本保留在此，其他研究使用各自独立目录。</span>
      </div>
    </details>
  );
}
