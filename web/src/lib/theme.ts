// 文件用途：界面配色。状态配色取自原型《模块状态样式一览》；只决定“长什么样”，状态本身一律由接口给出。
import type { StateCode } from '../api/types';

/** 全局基础色 */
export const C = {
  bg: '#F2F4F5', // 页面背景
  card: '#FFFFFF', // 卡片背景
  line: '#DCE1E5', // 卡片边框
  lineSoft: '#ECEFF1', // 浅分隔线
  text: '#17212B', // 正文
  text2: '#3A4651', // 次要正文
  muted: '#56636F', // 说明文字
  primary: '#0F5E6E', // 主色（按钮、选中）
  primaryDark: '#0A4350', // 主色加深
  primarySoft: '#E6EEF0', // 主色浅底
  warnBg: '#FFF0D6', // 警示浅底
  warnLine: '#E9B872', // 警示边框
  warnText: '#5E3200', // 警示文字
  accent: '#C76E00', // 待办强调色
  danger: '#8E1B12', // 减少/错误文字
};

/** 单个状态的样式 */
export interface StateStyle {
  bg: string; // 胶囊背景
  fg: string; // 胶囊文字
  border: string; // 胶囊边框
  boxBg: string; // 说明框背景
  boxLine: string; // 说明框边框
  dot: string; // 导航圆点 / 进度条颜色
}

// 原型中的十种状态配色，另补充接口新增的 ready / incomplete / unavailable / history
const P: Record<string, StateStyle> = {
  idle: { bg: '#ECEFF1', fg: '#3A4651', border: '1px solid #ECEFF1', boxBg: '#F6F8F9', boxLine: '#ECEFF1', dot: '#8C969E' },
  ready: { bg: '#E6EEF0', fg: '#0A4350', border: '1px solid #9DC0C8', boxBg: '#F3F7F8', boxLine: '#C9DBE0', dot: '#0F5E6E' },
  running: { bg: '#E4EEFB', fg: '#174A8F', border: '1px solid #E4EEFB', boxBg: '#F3F7FC', boxLine: '#C9DCF3', dot: '#1D5FB8' },
  incomplete: { bg: '#FFFFFF', fg: '#8E1B12', border: '1px dashed #B42318', boxBg: '#FEF4F3', boxLine: '#F4C2BC', dot: '#B42318' },
  failed: { bg: '#FDE8E6', fg: '#8E1B12', border: '1px solid #FDE8E6', boxBg: '#FEF4F3', boxLine: '#F4C2BC', dot: '#B42318' },
  waiting: { bg: '#EFEAF8', fg: '#4E3780', border: '1px solid #EFEAF8', boxBg: '#F7F4FC', boxLine: '#D9CEEE', dot: '#6B4FA0' },
  empty: { bg: '#E6EEF0', fg: '#0A4350', border: '1px solid #E6EEF0', boxBg: '#F3F7F8', boxLine: '#C9DBE0', dot: '#0F5E6E' },
  review: { bg: '#FFF0D6', fg: '#7A4100', border: '1px solid #FFF0D6', boxBg: '#FBF8F2', boxLine: '#F0D9AE', dot: '#C76E00' },
  returned: { bg: '#FFFFFF', fg: '#7A4100', border: '1px solid #C76E00', boxBg: '#FBF8F2', boxLine: '#F0D9AE', dot: '#C76E00' },
  approved: { bg: '#E3F2EA', fg: '#17633F', border: '1px solid #E3F2EA', boxBg: '#F3FAF6', boxLine: '#C6E4D3', dot: '#1F7A4D' },
  stale: { bg: 'repeating-linear-gradient(135deg, #ECEFF1 0 6px, #DCE1E5 6px 12px)', fg: '#26323C', border: '1px solid #A9B5BF', boxBg: '#F6F8F9', boxLine: '#DCE1E5', dot: '#8C969E' },
  published: { bg: '#1F7A4D', fg: '#FFFFFF', border: '1px solid #1F7A4D', boxBg: '#F3FAF6', boxLine: '#C6E4D3', dot: '#1F7A4D' },
  unavailable: { bg: '#FFFFFF', fg: '#56636F', border: '1px dashed #A9B5BF', boxBg: '#F6F8F9', boxLine: '#DCE1E5', dot: '#C3CBD1' },
  history: { bg: '#ECEFF1', fg: '#26323C', border: '1px solid #A9B5BF', boxBg: '#F6F8F9', boxLine: '#DCE1E5', dot: '#8C969E' },
};
P.hold = P.review; // “暂存待定”与“待你复核”同色
P.scope_confirmed = P.approved; // 仅复用完成配色，标签与正式批准分别显示。
P.prepared = P.ready; // 技术归档不使用科研批准语义。
P.execution_confirmed = P.running;

/** 取某个状态的样式；未知状态按“未开始”显示 */
export function stateStyle(code: StateCode | string | null | undefined): StateStyle {
  return P[code || 'idle'] || P.idle;
}

/** 导航图例（只做颜色说明） */
export const LEGEND: { code: StateCode; text: string }[] = [
  { code: 'approved', text: '已通过' },
  { code: 'scope_confirmed', text: '准备已核查（扩展）' },
  { code: 'review', text: '待复核' },
  { code: 'running', text: '运行中' },
  { code: 'failed', text: '执行失败' },
  { code: 'waiting', text: '等待资料' },
  { code: 'idle', text: '未开始 / 已失效' },
];

/** 任务状态配色 */
export function taskColor(state: string): { bg: string; fg: string } {
  if (state === 'succeeded') return { bg: '#E3F2EA', fg: '#17633F' }; // 已完成
  if (state === 'running' || state === 'queued') return { bg: '#E4EEFB', fg: '#174A8F' }; // 进行中
  if (state === 'failed' || state === 'interrupted') return { bg: '#FDE8E6', fg: '#8E1B12' }; // 失败/中断
  return { bg: '#ECEFF1', fg: '#3A4651' }; // 已取消等
}

// 结合能热图色带：最负 深红 → 浅红 → 浅蓝 → 最不负 深蓝（无白色中点）
const HEAT_STOPS: [number, [number, number, number]][] = [
  [0, [155, 28, 28]], // 深红
  [0.45, [242, 169, 154]], // 浅红
  [0.55, [169, 200, 234]], // 浅蓝
  [1, [31, 78, 140]], // 深蓝
];

/** 热图色带的 CSS 渐变（图例用） */
export const HEAT_GRADIENT = 'linear-gradient(90deg, #9B1C1C 0%, #F2A99A 45%, #A9C8EA 55%, #1F4E8C 100%)';

/** 根据数值在 [min, max] 中的位置平滑插值出底色；深色格配白字 */
export function heatColor(v: number, min: number, max: number): { bg: string; fg: string } {
  const span = max - min; // 数值范围
  const t = span > 0 ? Math.min(1, Math.max(0, (v - min) / span)) : 0.5; // 归一化位置（0=最负）
  for (let i = 0; i < HEAT_STOPS.length - 1; i++) {
    const [p0, c0] = HEAT_STOPS[i]; // 区间起点
    const [p1, c1] = HEAT_STOPS[i + 1]; // 区间终点
    if (t <= p1) {
      const u = (t - p0) / (p1 - p0); // 区间内位置
      const c = c0.map((x, j) => Math.round(x + (c1[j] - x) * u)); // 逐通道线性插值
      return { bg: `rgb(${c.join(',')})`, fg: t < 0.28 || t > 0.78 ? '#FFFFFF' : '#17212B' };
    }
  }
  return { bg: 'rgb(31,78,140)', fg: '#FFFFFF' }; // 兜底：最深蓝
}

/** 受体角色标签配色 */
export function roleColor(role: string): { bg: string; fg: string } {
  if (role === '主要') return { bg: '#E6EEF0', fg: '#0A4350' }; // 主要受体
  if (role === '扩展') return { bg: '#ECEFF1', fg: '#3A4651' }; // 扩展受体
  return { bg: '#F3EEF9', fg: '#5B3F8C' }; // 探索受体
}
