// 文件用途：显示正式评分闸门状态；只读，不提供启动按钮。
import { Alert, Tag } from 'antd';
import type { ScoringReadinessInfo } from '../api/types';

/** 评分能否启动只显示服务端结果，前端不重新判断。 */
export default function ScoringReadiness({ info }: { info: ScoringReadinessInfo }) {
  if (!info.supported) return null;
  return <section className="card" id="a06-scoring-readiness">
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <h2 style={{ margin: 0, fontSize: 17 }}>正式评分闸门</h2>
      <Tag color={info.scoring_allowed ? 'green' : 'orange'}>{info.scoring_allowed ? '允许启动' : '暂不允许'}</Tag>
    </div>
    <Alert type={info.scoring_allowed ? 'success' : 'warning'} showIcon message={info.reason_zh}
      description="本卡片只读显示资格，不会创建评分任务或改变人工复核状态。" />
    {!!info.blockers.length && <ul style={{ margin: '10px 0 0', paddingLeft: 22 }}>{info.blockers.map(item => <li key={item}>{item}</li>)}</ul>}
  </section>;
}
