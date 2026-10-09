// 文件用途：极简哈希路由。地址形如 #/、#/studies/<研究编号>/<模块编号>?run_id=<运行编号>，刷新页面后仍能回到原位置。
import { useEffect, useState } from 'react';

/** 当前路由 */
export interface Route {
  page: 'home' | 'study'; // 首页或研究页
  studyId?: string; // 研究编号
  moduleId?: string; // 模块编号
  runId?: string; // 历史版本运行编号
}

/** 解析 location.hash */
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, ''); // 去掉 #
  const [path, query = ''] = raw.split('?'); // 拆出路径和查询串
  const parts = path.split('/').filter(Boolean); // 路径分段
  const params = new URLSearchParams(query); // 查询参数
  if (parts[0] === 'studies' && parts[1]) {
    // 研究页
    return { page: 'study', studyId: parts[1], moduleId: parts[2], runId: params.get('run_id') || undefined };
  }
  return { page: 'home' }; // 其他一律回首页
}

/** 生成哈希地址 */
export function hrefFor(r: Route): string {
  if (r.page === 'home' || !r.studyId) return '#/'; // 首页
  let h = `#/studies/${r.studyId}`; // 研究页
  if (r.moduleId) h += `/${r.moduleId}`; // 附带模块
  if (r.runId) h += `?run_id=${encodeURIComponent(r.runId)}`; // 附带历史版本
  return h;
}

/** 跳转 */
export function navigate(r: Route): void {
  window.location.hash = hrefFor(r); // 改变哈希即触发 hashchange
}

/** 订阅哈希变化的 Hook */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash)); // 初始路由
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash)); // 哈希变化时更新
    window.addEventListener('hashchange', on); // 监听
    return () => window.removeEventListener('hashchange', on); // 卸载时移除监听
  }, []);
  return route;
}
