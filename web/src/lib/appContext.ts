// 文件用途：全局共享状态的上下文（会话信息、任务面板、待办面板、刷新信号）。
import { createContext, useContext } from 'react';
import type { Session, Task } from '../api/types';

/** 全局上下文内容 */
export interface AppContextValue {
  session: Session | null; // 会话（令牌、决定中文名）
  refreshTick: number; // 刷新信号：数值变化时页面重新加载数据
  bumpRefresh: () => void; // 触发一次刷新
  openTasks: (taskId?: string) => void; // 打开任务面板（可指定任务）
  openNewStudy: () => void; // 打开新研究登记，创建本身不启动计算
  openInbox: () => void; // 打开全局待办
  trackTasks: (tasks: (Task | null | undefined)[]) => void; // 登记需要跟踪的活动任务
  setCrumb: (title: string | null) => void; // 设置顶栏位置中的研究名
  currentStudyId: string | null; // 当前所在研究（任务面板默认筛选）
}

/** 上下文对象 */
export const AppContext = createContext<AppContextValue | null>(null);

/** 读取全局上下文 */
export function useApp(): AppContextValue {
  const v = useContext(AppContext); // 取上下文
  if (!v) throw new Error('AppContext 未初始化'); // 必须在 App 内使用
  return v;
}

/** 决定的中文名；末端 A07 的通过文案不再描述下游，其余优先使用接口。 */
export function decisionLabel(session: Session | null, d: string | null | undefined, moduleId?: string): string {
  if (!d) return '—'; // 无决定
  if (moduleId === 'A07' && d === 'approved') return '通过'; // 报告为流程末端
  const fallback: Record<string, string> = { approved: '通过', rejected: '退回修改', pending: '暂存待定' }; // 接口未返回时的兜底
  return (session?.decisions_zh as Record<string, string> | undefined)?.[d] || fallback[d] || d;
}
