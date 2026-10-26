// 研究级只读追溯与导出入口。默认不加载完整追溯，避免进入研究页时增加大文件读取。
import { Alert, Button, Card, Spin, Tag } from 'antd';
import { useState } from 'react';
import { api, apiUrl, errorText } from '../api/client';
import type { TraceSummary } from '../api/types';

export default function TraceExportPanel({ studyId }: { studyId: string }) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<TraceSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function load() {
    setBusy(true); setError('');
    try { setTrace(await api.studyTrace(studyId)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !trace) void load();
  }

  return (
    <Card size="small" title="追溯与数据导出" extra={<Button size="small" onClick={toggle}>{open ? '收起' : '展开查看'}</Button>}>
      <p className="small muted" style={{ margin: 0 }}>保留原始输入、参数版本、运行关系、结果表和文件指纹；本入口只读，不会启动任务或修改复核。</p>
      {open && <div className="stack" style={{ marginTop: 12 }}>
        {error && <Alert type="error" showIcon message="追溯摘要读取失败" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
        <Spin spinning={busy}>
          {trace && <div className="stack" style={{ gap: 10 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <Tag color="blue">只读</Tag>
              <span className="small">版本 {trace.trace_version}</span>
              <span className="small">当前归档文件 {trace.file_count} 个</span>
              <Button size="small" onClick={() => void load()}>刷新摘要</Button>
            </div>
            <div className="small">{trace.message_zh}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <Button size="small" href={apiUrl(trace.export_json_url)} target="_blank" rel="noreferrer">下载完整追溯 JSON</Button>
              <Button size="small" href={apiUrl(trace.export_csv_url)} target="_blank" rel="noreferrer">下载结果 CSV</Button>
            </div>
            <div className="stack" style={{ gap: 6 }}>
              {trace.modules.map((row) => (
                <div key={row.module_id} style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px', alignItems: 'baseline', borderTop: '1px solid #EEF1F3', paddingTop: 6 }}>
                  <strong>{row.module_id} {row.label_zh}</strong>
                  <span className="small muted">{row.state}{row.run_id ? ` · ${row.run_id}` : ''}</span>
                  {row.table_names.length > 0 && <span className="small muted">结果表 {row.table_names.length} 张</span>}
                </div>
              ))}
            </div>
          </div>}
        </Spin>
      </div>}
    </Card>
  );
}
