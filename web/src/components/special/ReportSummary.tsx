// 文件用途：A07 双报告页的专属内容：①共同结论、②三条研究线索、③限制边界、纳入通路、两份 Word 下载。
import { Button, Tooltip } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { Special } from '../../api/types';
import { fileUrl } from '../../api/client';
import { SectionHead } from '../common';

// 报告角色的中文兜底名：仅在接口 label_zh 未本地化（与 role 相同）时使用
const ROLE_ZH: Record<string, string> = { detailed_report: '专业详细报告', concise_report: '临床简略报告' };

/** 把结论长文按句号后的空白拆成段落（只影响排版） */
function paragraphs(text: string): string[] {
  return text.split(/(?<=。)\s+/).map((p) => p.trim()).filter(Boolean);
}

/** A07 报告专属区块 */
export default function ReportSummary({ special, studyId, downloadsOnly = false }: { special: Special; studyId: string; downloadsOnly?: boolean }) {
  const leads = special.leads || []; // 研究线索
  const limits = special.limits || []; // 限制边界
  const pathways = special.pathway || []; // 纳入通路
  const files = special.report_files || []; // 报告文件
  return (
    <>
      {/* ① 共同结论 */}
      {!downloadsOnly && special.conclusion_zh && (
        <section className="card">
          <SectionHead title="① 共同结论（两份报告共用）" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 14, color: '#26323C' }}>
            {paragraphs(special.conclusion_zh).map((p, i) => <p key={i} style={{ margin: 0 }}>{p}</p>)}
          </div>
        </section>
      )}
      {/* ② 研究线索 */}
      {!downloadsOnly && leads.length > 0 && (
        <section className="card">
          <SectionHead title={`② ${leads.length} 条研究线索`} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {leads.map((l, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '12px 14px', border: '1px solid #DCE1E5', borderRadius: 8 }}>
                <strong style={{ fontSize: 15 }}>{l.title_zh}</strong>
                <span style={{ fontSize: 14 }}><span className="muted">支持事实：</span>{l.fact_zh}</span>
                <span style={{ fontSize: 14 }}><span className="muted">下一步核验：</span>{l.next_zh}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      {/* ③ 限制边界 */}
      {!downloadsOnly && limits.length > 0 && (
        <section className="card">
          <SectionHead title="③ 限制边界" />
          <ul style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 14 }}>
            {limits.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </section>
      )}
      {/* 纳入报告的通路 */}
      {!downloadsOnly && pathways.length > 0 && (
        <section className="card">
          <SectionHead title="纳入报告的通路" />
          {pathways.map((p) => (
            <div key={p.id} style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 20px', alignItems: 'baseline', padding: '12px 14px', background: '#F6F8F9', borderRadius: 8, marginBottom: 8 }}>
              <strong style={{ fontSize: 16 }}>{p.name_zh}</strong>
              <span className="mono small">{p.id}</span>
              <span className="small">命中基因 {p.hits}</span>
              <span className="pill" style={{ background: '#E3F2EA', color: '#17633F' }}>{p.status_zh}</span>
            </div>
          ))}
          <p className="small muted" style={{ margin: 0 }}>通路图只表示输入基因在通路中的位置，不表示通路被激活或抑制。</p>
        </section>
      )}
      {/* 报告下载 */}
      {downloadsOnly && files.length > 0 && (
        <section className="card">
          <SectionHead title="报告下载" />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            {files.map((f) => {
              const label = f.label_zh && f.label_zh !== f.role ? f.label_zh : ROLE_ZH[f.role] || f.label_zh || f.role; // 显示名
              const btn = (
                <Button size="large" icon={<DownloadOutlined />} disabled={!f.key} href={f.key ? fileUrl(studyId, f.key) : undefined}>
                  {label} · Word
                </Button>
              );
              // 没有下载键时置灰并说明
              return f.key ? <span key={f.role}>{btn}</span> : (
                <Tooltip key={f.role} title="该报告文件尚未登记到本次运行的文件索引，暂不能从这里下载">
                  <span>{btn}</span>
                </Tooltip>
              );
            })}
          </div>
          <p className="small muted" style={{ margin: '8px 0 4px' }}>两份报告来自同一份结构化结论。文件位置与指纹：</p>
          {/* 每份报告的归档路径与 SHA-256，供追溯 */}
          <ul className="tiny muted" style={{ margin: 0, paddingLeft: 20 }}>
            {files.map((f) => (
              <li key={'p' + f.role} style={{ overflowWrap: 'anywhere' }}>
                <span className="mono">{f.path}</span> · SHA-256 <span className="mono">{f.sha256}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
