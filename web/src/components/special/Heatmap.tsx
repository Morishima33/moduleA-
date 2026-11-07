// 文件用途：A06 结合能热图。默认“行=成分、列=受体”，可转置；颜色从最负深红平滑过渡到最不负深蓝；
// 单个缺失格（value 为 null）显示白底“NA”虚线边，不填 0、不填灰；整行/整列无评分的对象由接口列在 omitted 中，图下说明。
import { Button, Space, Switch } from 'antd';
import { useMemo, useState } from 'react';
import type { Heatmap as HeatmapData } from '../../api/types';
import { fmtNum } from '../../lib/format';
import { HEAT_GRADIENT, heatColor, roleColor } from '../../lib/theme';
import { SectionHead } from '../common';

/** 被选中的格子 */
interface Picked { compound: string; receptor: string }

/** A06 热图 */
export default function Heatmap({ data }: { data: HeatmapData }) {
  const [transposed, setTransposed] = useState(false); // 是否转置（行=受体）
  const [picked, setPicked] = useState<Picked | null>(null); // 选中的格子

  // 受体按接口给出的 order 排序
  const receptors = useMemo(() => [...data.receptors].sort((a, b) => a.order - b.order), [data.receptors]);
  // 查表：成分编号 → 受体名 → 数值
  const lookup = useMemo(() => {
    const m = new Map<string, Map<string, number | null>>(); // 二级索引
    for (const r of data.rows) m.set(r.compound_id, new Map(r.cells.map((c) => [c.receptor, c.value])));
    return m;
  }, [data.rows]);
  const compounds = data.rows; // 成分顺序按接口
  const recByName = useMemo(() => new Map(receptors.map((r) => [r.name, r])), [receptors]); // 受体信息索引
  const nameOf = (cid: string) => compounds.find((c) => c.compound_id === cid)?.compound_name || cid; // 成分名
  const receptorName = (key: string) => recByName.get(key)?.display_name || key; // 显示名称不替换稳定查值键

  /** 取某格数值；接口未给出的格子视为 null */
  const valueOf = (cid: string, rec: string): number | null => {
    const v = lookup.get(cid)?.get(rec); // 查表
    return v === undefined ? null : v;
  };

  /** 渲染单个格子 */
  const cell = (cid: string, rec: string) => {
    const v = valueOf(cid, rec); // 该格数值
    const sel = picked?.compound === cid && picked?.receptor === rec; // 是否选中
    const label = `${nameOf(cid)} × ${receptorName(rec)}：${v === null ? '无有效评分（NA）' : `${v.toFixed(3)} ${data.unit}`}`; // 无障碍说明
    if (v === null) {
      // 缺失格：白底 NA，虚线边
      return (
        <button key={cid + rec} className="hm-cell" aria-label={label} title={label} onClick={() => setPicked({ compound: cid, receptor: rec })}
          style={{ background: '#FFFFFF', color: '#3A4651', border: sel ? '2px solid #17212B' : '1px dashed #8C969E' }}>
          NA
        </button>
      );
    }
    const c = heatColor(v, data.min, data.max); // 插值颜色
    return (
      <button key={cid + rec} className="hm-cell" aria-label={label} title={label} onClick={() => setPicked({ compound: cid, receptor: rec })}
        style={{ background: c.bg, color: c.fg, border: sel ? '2px solid #17212B' : '1px solid transparent' }}>
        {v.toFixed(3)}
      </button>
    );
  };

  /** 受体表头：名称 + 角色标签 */
  const recHead = (name: string) => {
    const r = recByName.get(name); // 受体信息
    const rc = roleColor(r?.role_zh || ''); // 角色配色
    return (
      <>
        <span className="mono" style={{ fontWeight: 500 }} title={name}>{receptorName(name)}</span>
        {r?.role_zh && <span className="pill" style={{ background: rc.bg, color: rc.fg, fontSize: 11, padding: '0 6px' }}>{r.role_zh}</span>}
      </>
    );
  };

  // 行与列：默认行=成分，转置后行=受体
  const rowKeys = transposed ? receptors.map((r) => r.name) : compounds.map((c) => c.compound_id);
  const colKeys = transposed ? compounds.map((c) => c.compound_id) : receptors.map((r) => r.name);
  const firstCol = transposed ? 120 : 140; // 行标题宽度（长名称自动换行）
  const gridCols = `${firstCol}px repeat(${colKeys.length}, minmax(58px, 1fr))`; // 网格列定义
  const minWidth = firstCol + colKeys.length * 61; // 最小宽度，超出时横向滚动（只在图内滚动）

  // 选中格子的详情
  const detail = picked && (() => {
    const v = valueOf(picked.compound, picked.receptor); // 数值
    const r = recByName.get(picked.receptor); // 受体
    const rmsd = r?.rmsd === null || r?.rmsd === undefined ? '无数值（见受体限制表）' : `${r.rmsd.toFixed(3)} Å`; // RMSD 显示
    return (
      <div style={{ padding: '14px 16px', border: '1px solid #A9C8EA', background: '#F3F7FC', borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <strong>{nameOf(picked.compound)} × {receptorName(picked.receptor)}</strong>
          <Button size="small" type="text" onClick={() => setPicked(null)}>关闭</Button>
        </div>
        <span>{v === null ? '无有效评分（NA）：按规则不补 0、不改选其他姿势；原因见受体限制表和运行记录。' : `Vina 评分 ${v.toFixed(3)} ${data.unit}`}</span>
        <span style={{ color: '#3A4651' }}>
          受体结构：PDB {r?.pdb || '—'} · 重对接 RMSD {rmsd} · {r?.status_zh || '—'}{r?.role_zh ? ` · ${r.role_zh}受体` : ''}
        </span>
        <span className="small muted">只表示本次统一 Vina 设置下的预测评分，跨受体不直接比较药效。</span>
      </div>
    );
  })();

  return (
    <section className="card">
      <SectionHead title={`结合能矩阵（${data.unit}）`} extra="点击格子查看组合详情" />
      {/* 转置开关 */}
      <Space style={{ marginBottom: 10 }} wrap>
        <Switch checked={transposed} onChange={setTransposed} />
        <span className="small">{transposed ? '行 = 受体，列 = 成分' : '行 = 成分，列 = 受体'}</span>
      </Space>
      {/* 矩阵：只在图内横向滚动 */}
      <div className="hm-scroll">
        <div className="hm-grid" style={{ gridTemplateColumns: gridCols, minWidth }}>
          <span />
          {colKeys.map((k) => (
            // 列头
            <div key={'h' + k} className="hm-head">{transposed ? <span className="mono" style={{ overflowWrap: 'anywhere' }}>{nameOf(k)}</span> : recHead(k)}</div>
          ))}
          {rowKeys.map((rk) => [
            // 行头
            <div key={'r' + rk} className="hm-rowhead">
              {transposed ? recHead(rk) : <span className="mono" style={{ fontWeight: 500 }}>{nameOf(rk)}</span>}
            </div>,
            // 该行的格子
            ...colKeys.map((ck) => (transposed ? cell(ck, rk) : cell(rk, ck))),
          ])}
        </div>
      </div>
      {/* 图例 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, fontSize: 12, color: '#3A4651', margin: '12px 0' }}>
        <span>{fmtNum(data.min)} 更负</span>
        <span style={{ flex: '0 1 240px', minWidth: 120, height: 10, borderRadius: 3, background: HEAT_GRADIENT }} />
        <span>{fmtNum(data.max)} 较不负</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 26, height: 14, border: '1px dashed #8C969E', borderRadius: 2, fontSize: 10, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>NA</span>
          无有效评分
        </span>
      </div>
      {detail}
      {/* 图下说明：未展示的行/列与配色规则 */}
      <div className="small muted" style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.omitted.length > 0 && (
          <div>
            图中未展示（整行或整列没有有效评分）：
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {data.omitted.map((o) => (
                <li key={o.kind + o.name}>{o.kind === 'receptor' ? '受体' : o.kind === 'compound' ? '成分' : o.kind} {o.name}：{o.reason_zh}</li>
              ))}
            </ul>
          </div>
        )}
        <div>配色：{data.color_rule_zh}。</div>
      </div>
    </section>
  );
}
