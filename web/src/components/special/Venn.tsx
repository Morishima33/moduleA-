// 文件用途：A03 交集韦恩图（SVG 两圆）。数字直接取自接口 special.venn，不在前端计算。
import { useId } from 'react';
import type { Venn as VennData } from '../../api/types';
import { SectionHead } from '../common';

/** A03 韦恩图 */
export default function Venn({ data }: { data: VennData }) {
  const clipId = useId(); // 多个图实例各有独立裁剪编号。
  const separate = data.layout && data.layout !== 'overlap'; // 布局由后端归档数量决定。
  return (
    <section className="card">
      <SectionHead title="方剂靶点与疾病靶点的交集" />
      {/* 两个相交的圆：左为方剂靶点，右为疾病靶点 */}
      {separate ? <svg viewBox="0 0 520 250" style={{width: '100%', maxWidth: 560, display: 'block', margin: '0 auto'}} role="img"
        aria-label={`方剂靶点 ${data.formula_total}，疾病靶点 ${data.disease_total}，交集 ${data.both}`}>
        {/* 空集用虚线框，两个非空但无交集的集合用分离圆，避免画出不存在的重叠。 */}
        {data.layout === 'empty_formula' || data.layout === 'empty_both' ? <rect x="25" y="40" width="175" height="150" rx="12" fill="#F6F8F9" stroke="#9AA7B0" strokeDasharray="6 4"/> : <circle cx="112" cy="115" r="87" fill="#D9E7EA" stroke="#0F5E6E" strokeWidth="2"/>}
        {data.layout === 'empty_disease' || data.layout === 'empty_both' ? <rect x="320" y="40" width="175" height="150" rx="12" fill="#F6F8F9" stroke="#9AA7B0" strokeDasharray="6 4"/> : <circle cx="408" cy="115" r="87" fill="#F7E9D7" stroke="#C76E00" strokeWidth="2"/>}
        <text x="112" y="100" textAnchor="middle" fontSize="16">方剂靶点</text><text x="112" y="137" textAnchor="middle" fontSize="28" fontWeight="700">{data.formula_total}</text>
        <text x="408" y="100" textAnchor="middle" fontSize="16">{data.layout === 'empty_disease' || data.layout === 'empty_both' ? '疾病集合为空' : '疾病靶点'}</text><text x="408" y="137" textAnchor="middle" fontSize="28" fontWeight="700">{data.disease_total}</text>
        <text x="260" y="100" textAnchor="middle" fontSize="16">交集</text><text x="260" y="137" textAnchor="middle" fontSize="28" fontWeight="700">{data.both}</text>
        <text x="260" y="230" textAnchor="middle" fontSize="13">无重叠部分，具体原因见上方输入核对</text>
      </svg> : <svg viewBox="0 0 520 250" style={{ width: '100%', maxWidth: 560, display: 'block', margin: '0 auto' }} role="img"
        aria-label={`仅方剂 ${data.formula_only}，交集 ${data.both}，仅疾病 ${data.disease_only}`}>
        {/* 交集单独着色；圆形面积仅用于展示，不按靶点数量比例绘制。 */}
        <defs><clipPath id={clipId}><circle cx="318.790" cy="110" r="100" /></clipPath></defs>
        <circle cx="201.210" cy="110" r="100" fill="#D9E7EA" />
        <circle cx="318.790" cy="110" r="100" fill="#F7E9D7" />
        <circle cx="201.210" cy="110" r="100" fill="#E6A9B5" clipPath={`url(#${clipId})`} />
        <circle cx="201.210" cy="110" r="100" fill="none" stroke="#0F5E6E" strokeWidth="2" />
        <circle cx="318.790" cy="110" r="100" fill="none" stroke="#C76E00" strokeWidth="2" />
        {/* 左侧：仅方剂 */}
        <text x="148" y="98" textAnchor="middle" fontSize="13" fill="#0A4350">仅方剂</text>
        <text x="148" y="124" textAnchor="middle" fontSize="22" fontWeight="700" fill="#17212B">{data.formula_only}</text>
        {/* 中间：交集 */}
        <text x="260" y="98" textAnchor="middle" fontSize="13" fill="#71364A">交集 I</text>
        <text x="260" y="128" textAnchor="middle" fontSize="28" fontWeight="700" fill="#5D293B">{data.both}</text>
        {/* 右侧：仅疾病 */}
        <text x="372" y="98" textAnchor="middle" fontSize="13" fill="#7A4100">仅疾病</text>
        <text x="372" y="124" textAnchor="middle" fontSize="22" fontWeight="700" fill="#17212B">{data.disease_only}</text>
        {/* 圆外标注两侧总数 */}
        <text x="120" y="240" textAnchor="middle" fontSize="13" fill="#0A4350">方剂靶点 T = {data.formula_total}</text>
        <text x="400" y="240" textAnchor="middle" fontSize="13" fill="#7A4100">疾病靶点 D = {data.disease_total}</text>
      </svg>}
      <p className="small muted" style={{ margin: '8px 0 0' }}>
        图形面积仅示意，不代表数量比例。数字为标准化后的不同人类基因数。交集 {data.both} 是 PPI 和富集的共同输入。
      </p>
    </section>
  );
}
