// 文件用途：A03 交集韦恩图（SVG 两圆）。数字直接取自接口 special.venn，不在前端计算。
import type { Venn as VennData } from '../../api/types';
import { SectionHead } from '../common';

/** A03 韦恩图 */
export default function Venn({ data }: { data: VennData }) {
  return (
    <section className="card">
      <SectionHead title="方剂靶点与疾病靶点的交集" />
      {/* 两个相交的圆：左为方剂靶点，右为疾病靶点 */}
      <svg viewBox="0 0 520 250" style={{ width: '100%', maxWidth: 560, display: 'block', margin: '0 auto' }} role="img"
        aria-label={`仅方剂 ${data.formula_only}，交集 ${data.both}，仅疾病 ${data.disease_only}`}>
        <circle cx="195" cy="110" r="100" fill="rgba(15,94,110,0.16)" stroke="#0F5E6E" strokeWidth="2" />
        <circle cx="325" cy="110" r="100" fill="rgba(199,110,0,0.14)" stroke="#C76E00" strokeWidth="2" />
        {/* 左侧：仅方剂 */}
        <text x="130" y="98" textAnchor="middle" fontSize="13" fill="#0A4350">仅方剂</text>
        <text x="130" y="124" textAnchor="middle" fontSize="22" fontWeight="700" fill="#17212B">{data.formula_only}</text>
        {/* 中间：交集 */}
        <text x="260" y="98" textAnchor="middle" fontSize="13" fill="#17212B">交集 I</text>
        <text x="260" y="128" textAnchor="middle" fontSize="28" fontWeight="700" fill="#17212B">{data.both}</text>
        {/* 右侧：仅疾病 */}
        <text x="390" y="98" textAnchor="middle" fontSize="13" fill="#7A4100">仅疾病</text>
        <text x="390" y="124" textAnchor="middle" fontSize="22" fontWeight="700" fill="#17212B">{data.disease_only}</text>
        {/* 圆外标注两侧总数 */}
        <text x="120" y="240" textAnchor="middle" fontSize="13" fill="#0A4350">方剂靶点 T = {data.formula_total}</text>
        <text x="400" y="240" textAnchor="middle" fontSize="13" fill="#7A4100">疾病靶点 D = {data.disease_total}</text>
      </svg>
      <p className="small muted" style={{ margin: '8px 0 0' }}>
        数字为标准化后的不同人类基因数。交集 {data.both} 是 PPI 和富集的共同输入。
      </p>
    </section>
  );
}
