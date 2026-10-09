// 文件用途：显示格式化工具（时间、文件大小、数值、编号缩写）。只改变显示方式，不改变任何科学数值。

/** 把 UTC ISO 时间显示为本地“YYYY-MM-DD HH:mm” */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'; // 没有时间
  const d = new Date(iso); // 解析时间
  if (Number.isNaN(d.getTime())) return String(iso); // 无法解析时原样显示
  const p = (n: number) => String(n).padStart(2, '0'); // 补零
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 只显示日期部分 */
export function fmtDate(iso: string | null | undefined): string {
  return fmtTime(iso).slice(0, 10); // 取前 10 个字符
}

/** 文件大小显示 */
export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'; // 未知大小
  if (n < 1024) return `${n} B`; // 字节
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`; // 千字节
  return `${(n / 1024 / 1024).toFixed(1)} MB`; // 兆字节
}

/** 数值显示：整数原样；极小数用科学计数；其余最多保留 4 位小数（悬停可看原值） */
export function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return String(v); // 非有限数原样
  if (Number.isInteger(v)) return String(v); // 整数原样
  if (v !== 0 && Math.abs(v) < 1e-3) return v.toExponential(2); // 极小值用科学计数
  return String(Number(v.toFixed(4))); // 普通小数最多 4 位
}

/** p.adjust 显示：小于 0.001 用“a×10⁻ᵇ”形式 */
export function fmtP(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'; // 缺失
  if (v >= 1e-3) return v.toPrecision(3); // 较大值直接显示 3 位有效数字
  const [m, e] = v.toExponential(2).split('e'); // 拆分尾数与指数
  const sup: Record<string, string> = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
  const exp = String(Number(e)).split('').map((ch) => sup[ch] ?? ch).join(''); // 指数转上标
  return `${m}×10${exp}`;
}

/** 任意单元格的显示文本 */
export function cellText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'; // 空值
  if (typeof v === 'number') return fmtNum(v); // 数值
  if (typeof v === 'boolean') return v ? '是' : '否'; // 布尔
  if (typeof v === 'object') return JSON.stringify(v); // 对象/数组
  return String(v); // 文本
}

/** 长编号缩写：run_0d6785268bdc… */
export function shortId(id: string | null | undefined, keep = 12): string {
  if (!id) return '—'; // 空编号
  return id.length > keep + 2 ? id.slice(0, keep) + '…' : id; // 超长时截断
}

/** 研究用途的中文短名（只用于标签） */
export function purposeShort(p: string | null | undefined): string {
  if (!p) return ''; // 未登记用途
  if (p === 'workflow_test') return '流程测试';
  if (p === 'formal') return '正式研究';
  return p; // 其他用途原样显示
}

/** 运行结果的中文 */
export function outcomeZh(o: string | null | undefined): string {
  return ({ success: '成功', empty: '有效空结果', failed: '失败', partial: '部分完成' } as Record<string, string>)[o || ''] || '—';
}

/** 参数来源的中文 */
export function originZh(o: string): string {
  return ({ recorded: '运行记录', outline: '大纲', decision: '用户决定', run_config: '运行配置' } as Record<string, string>)[o] || o;
}
