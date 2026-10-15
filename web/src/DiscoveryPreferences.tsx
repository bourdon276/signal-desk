export type AcquisitionProfile = {
  feedback_count: number;
  signals: { kind: string; label: string; weight: number }[];
  source_signals?: { domain: string; weight: number }[];
  effective_focus?: string;
  effective_focus_label?: string;
  search_domains?: string[];
  avoided_sources?: string[];
  source_fallback?: boolean;
}

export const focusLabels: Record<string, string> = {
  recent: '近期综合新闻', interview: '采访', roster: '阵容与转会', financial: '财报与业绩',
  macro_data: '经济数据发布', policy: '美联储与政策发言', gold_opinion: '机构观点',
  macro: '宏观经济', market: '指数与市场动态', gold_market: '黄金市场',
}
export const filteredNewsKinds = ['interview', 'roster', 'financial', 'macro', 'market', 'gold_market', 'macro_data', 'policy', 'gold_opinion']

function Profile({ name, profile }: { name: string; profile: AcquisitionProfile }) {
  return <div className="discovery-profile"><strong>{name}</strong>
    <p>下一次兴趣搜索优先：{profile.effective_focus_label || '近期综合新闻'}</p>
    {profile.signals.length > 0 && <p className="preference-signals">{profile.signals.map(signal => <span key={signal.kind}>{signal.weight > 0 ? '多看' : '少看'}{signal.label}</span>)}</p>}
    {!!profile.avoided_sources?.length && <p>兴趣搜索避开：{profile.avoided_sources.join('、')}</p>}
    {profile.source_fallback && <p>剩余搜索来源不足，保留综合搜索；不喜欢的来源仍会减少推荐。</p>}
    <small>{profile.feedback_count ? `已记录 ${profile.feedback_count} 次兴趣反馈` : '尚无兴趣反馈，先收集综合新闻'}</small>
    {!!profile.search_domains?.length && <details><summary>查看本次计划的搜索来源</summary><p>{profile.search_domains.join(' · ')}</p></details>}
  </div>
}

export function DiscoveryPreferences({ profiles, names, watchId }: {
  profiles: Record<string, AcquisitionProfile>; names: Record<string, string>; watchId: string;
}) {
  const ids = (watchId === 'all' ? Object.keys(profiles) : profiles[watchId] ? [watchId] : [])
    .filter(id => profiles[id].search_domains === undefined || !!profiles[id].search_domains?.length)
  if (!ids.length) return null
  const content = <><div className="discovery-profile-grid">{ids.map(id => <Profile key={id} name={names[id] || id} profile={profiles[id]} />)}</div>
    <p className="preference-explanation">类型反馈会改变今日精选的优先级和兴趣搜索方向；近期列表仍按时间排序。“少看这个来源”会避开对应网站。“只隐藏这一条”只隐藏已读过的文章。撤销反馈会重新计算偏好。公共RSS和综合采集继续更新，避免遗漏重要消息；定向搜索受采集间隔和额度限制，反馈后不会立刻保证出现新文章。其他用户的反馈不会改变你的计划。</p>
  </>
  return watchId === 'all'
    ? <details className="discovery-preferences"><summary>我的采集偏好 · {ids.length} 个关注</summary>{content}</details>
    : <section className="discovery-preferences" aria-label="我的采集偏好"><h2>我的采集偏好</h2>{content}</section>
}
