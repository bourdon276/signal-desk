import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'

type FeedDiagnostics = { hiding_feedback: { id: string; action: string; title: string }[]; candidates: number; hidden_not_interested: number; hidden_duplicate: number; eligible_count: number; unread_count: number; returned_count: number; candidate_limit_reached: boolean; omitted_by_limit: number }

type FeedView = 'news' | 'matches' | 'all'

type Topic = { id: string; name: string; keywords?: string[]; stock_code?: string | null; team_name?: string | null; team_watch_id?: string | null }
type Item = { id: string; watch_id: string; matched_watch_ids: string[]; title: string; url: string | null; source_name: string; ingestion_mode: string; published_at: string | null; overview: { text: string; kind: string }; is_read: boolean; reason: string; content_kind: string; content_kind_label: string }
type Feedback = { id: string; item_id: string; action: string; reason: string | null; undone_at: string | null }
type SourceResult = { entries?: number; teams?: number; resolved_teams?: number; unresolved_teams?: number; matches?: number; matched?: number; created?: number; updated?: number; skipped?: number; full_pages?: number; dropped?: Record<string, number> }
type Source = { id: string; label: string; status: string; automatic: boolean; description: string; last_success_at: string | null; last_attempt_at: string | null; last_error: string | null; last_result?: SourceResult | null }
type Coverage = { watch_id: string; automatic: boolean; status: string; last_success_at: string | null; latest_item_at: string | null; latest_news_at: string | null; latest_match_at: string | null; description: string; matched_count: number; news_count: number; match_count: number; last_result?: SourceResult | null }
type Answer = { answer: string; citations: { title: string; url: string | null; source_name?: string }[]; run_id: string; mode?: string; model_run_id?: string; notice?: string }

async function api<T>(path: string, token = '', options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, signal: AbortSignal.timeout(45000), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求未完成（${response.status}），请稍后重试`)
  return data
}
function sourceLabel(status: string) { return ({ success: '同步完成', partial: '部分同步', failure: '采集失败', running: '同步中', stale: '更新延迟', not_run: '等待首次同步', not_configured: '暂无自动更新', library_filter: '匹配来源库' } as Record<string, string>)[status] || status }
function updateTime(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value)) : '尚无记录' }
function date(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(value)) : '日期未知' }
function pandascoreRun(result?: SourceResult | null) {
  if (!result) return ''
  const resolved = result.resolved_teams ?? 0, teams = result.teams ?? 0
  const dropped = Object.values(result.dropped || {}).reduce((sum, count) => sum + count, 0)
  return `最近一轮：已解析 ${resolved}/${teams} 个战队 · 收到 ${result.matches ?? 0} 场 · 可展示 ${result.matched ?? 0} 场 · 新增 ${result.created ?? 0} 条 · 更新 ${result.updated ?? 0} 条${dropped ? ` · 丢弃 ${dropped} 场（超出时间窗口、字段不完整或状态不支持）` : ''}${result.full_pages ? ` · ${result.full_pages} 个列表达到100条上限，结果可能不完整` : ''}`
}

export default function App() {
  const [agent, setAgent] = useState<{ configured: boolean; model: string | null; search_configured?: boolean }>({ configured: false, model: null })
  const [useModel, setUseModel] = useState(false)
  const [useSearch, setUseSearch] = useState(false)
  const [runTrace, setRunTrace] = useState('')
  const [token, setToken] = useState(() => localStorage.getItem('signal-token') || '')
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [invite, setInvite] = useState('')
  const [catalog, setCatalog] = useState<Topic[]>([]), [topics, setTopics] = useState<Topic[]>([])
  const [watches, setWatches] = useState<string[]>([]), [items, setItems] = useState<Item[]>([]), [feedback, setFeedback] = useState<Feedback[]>([])
  const [sources, setSources] = useState<Source[]>([]), [coverages, setCoverages] = useState<Coverage[]>([])
  const [topicKind, setTopicKind] = useState('stock'), [stockCode, setStockCode] = useState('')
  const [filter, setFilter] = useState('all'), [unread, setUnread] = useState(false)
  const [quickRead, setQuickRead] = useState(false)
  const [feedView, setFeedView] = useState<FeedView>('news')
  const refreshVersion = useRef(0)
  const [feedLoading, setFeedLoading] = useState(false)
  const [feedDiagnostics, setFeedDiagnostics] = useState<FeedDiagnostics | null>(null)
  const [feedbackItem, setFeedbackItem] = useState<string | null>(null)
  const [editing, setEditing] = useState(false), [topicName, setTopicName] = useState('')
  const [question, setQuestion] = useState(''), [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const options = [...catalog, ...topics]
  const nameOf = (id: string) => options.find(t => t.id === id)?.name || options.find(t => (t.stock_code && `stock:${t.stock_code}` === id) || t.team_watch_id === id)?.name || id

  const refresh = useCallback(async (view: FeedView = feedView) => {
    if (!token) return
    const version = ++refreshVersion.current
    setFeedLoading(true); setItems([]); setFeedDiagnostics(null)
    try {
      const [w, f, h, t, s, c] = await Promise.all([
        api<{ watch_ids: string[] }>('/watches', token), api<{ items: Item[]; diagnostics: FeedDiagnostics }>(`/feed?limit=100&view=${view}${filter === 'all' ? '' : `&watch_id=${encodeURIComponent(filter)}`}`, token),
        api<{ events: Feedback[] }>('/feedback', token), api<{ topics: Topic[] }>('/topics', token), api<{ sources: Source[] }>('/sources'), api<{ coverage: Coverage[] }>('/coverage', token),
      ])
      if (version !== refreshVersion.current) return
      setWatches(w.watch_ids); setItems(f.items); setFeedDiagnostics(f.diagnostics); setFeedback(h.events); setTopics(t.topics); setSources(s.sources); setCoverages(c.coverage)
    } catch (cause) { if (version === refreshVersion.current) setError((cause as Error).message) }
    finally { if (version === refreshVersion.current) setFeedLoading(false) }
  }, [token, feedView, filter])
  useEffect(() => { api<{ watches: Topic[] }>('/catalog').then(r => setCatalog(r.watches)).catch(() => setError('关注清单加载失败，请刷新页面')) }, [])
  useEffect(() => { void refresh(); api<{ configured: boolean; model: string | null }>('/agent/status').then(setAgent).catch(() => {}) }, [refresh])

  async function auth(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const r = await api<{ token: string }>(registering ? '/register' : '/login', '', { method: 'POST', body: JSON.stringify({ email, password, invite_code: invite }) })
      localStorage.setItem('signal-token', r.token); setToken(r.token); setPassword(''); setInvite('')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  async function mutate(path: string, method: string, body?: unknown) {
    if (busy) return false
    setBusy(true); setError(''); setNotice('')
    try { await api(path, token, { method, ...(body ? { body: JSON.stringify(body) } : {}) }); await refresh(); return true }
    catch (cause) { setError((cause as Error).message); return false } finally { setBusy(false) }
  }
  async function addTopic(e: FormEvent) {
    e.preventDefault()
    const body = topicKind === 'stock'
      ? { name: topicName.trim(), stock_code: stockCode.trim() }
      : { name: topicName.trim(), team_name: topicName.trim() }
    if (await mutate('/topics', 'POST', body)) {
      setEditing(false); setTopicName(''); setStockCode('')
      setNotice(topicKind === 'stock'
        ? '股票代码已加入个人关注。自动公告需要在服务端配置巨潮账号与展示许可；请查看来源状态。'
        : '战队关注已加入。绿龙会匹配 Team Spirit 的 CS2 赛程与比分；自动同步需要服务端配置 PandaScore Token。')
    }
  }
  async function searchNews() {
    if (busy || filter === 'all') return
    if (feedView !== 'news') { ++refreshVersion.current; setItems([]); setFeedView('news') }
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await api<{ status: string; results: unknown[]; cache_hit?: boolean; search_credits: number; entries?: number; matched?: number; eligible_count?: number; not_visible_count?: number; dropped?: Record<string, number> }>('/search', token, { method: 'POST', body: JSON.stringify({ watch_id: filter, focus: 'recent' }) })
      setUnread(false); setQuickRead(false)
      await refresh('news')
      const labels: Record<string, string> = { not_configured: '搜索服务尚未配置，已有消息仍可阅读。', budget_exhausted: '搜索额度已达上限，稍后再试。', busy: '该对象正在搜索，请稍后刷新。', failure: '搜索未完成，已有消息仍可阅读。', outside_supported_scope: '当前仅支持已关注的 A 股或 CS2 战队。' }
      const dropLabels: Record<string, string> = { entity_mismatch: '与战队或股票不匹配', missing_cs2_context: '无法确认属于CS2', missing_date: '缺少可用日期', outside_30_days: '不在近30天', missing_or_outside_date: '日期缺失或超时', not_news_article: '非新闻页面', unapproved_url: '不在允许来源', url_owned_by_other_entity: '已归入其他对象' }
      const dropped = Object.entries(r.dropped || {}).map(([reason, count]) => `${dropLabels[reason] || '格式不完整'} ${count} 条`).join('；')
      const detail = `搜索返回 ${r.entries ?? 0} 条，匹配入库 ${r.matched ?? 0} 条，当前可展示 ${r.eligible_count ?? r.results.length} 条。${dropped ? `过滤：${dropped}。` : ''}${r.not_visible_count ? `另有 ${r.not_visible_count} 条因当前范围、时间或个人反馈未展示。` : ''}`
      setNotice(r.status === 'success' ? `${r.cache_hit ? '复用缓存' : '搜索完成'}。${detail}摘录未核验全文。已切到新闻栏目，展示全部阅读状态。` : labels[r.status] || '搜索未完成。')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  async function ask(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setRunTrace('')
    try { setAnswer(await api<Answer>('/ask', token, { method: 'POST', body: JSON.stringify({ question, use_model: useModel, use_search: useSearch }) })) }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  function logout() { ++refreshVersion.current; setFeedLoading(false); setFeedDiagnostics(null); setFeedbackItem(null); setUseSearch(false); localStorage.removeItem('signal-token'); setToken(''); setItems([]); setFeedback([]); setTopics([]); setWatches([]); setAnswer(null); setError(''); setNotice(''); setFilter('all'); setCoverages([]); setSources([]); setUnread(false); setQuickRead(false) }

  if (!token) return <main className="login-page"><div className="login-title">阅讯<span>个人资讯阅读台</span></div><section className="login-box"><h1>{registering ? '创建账号' : '欢迎回来'}</h1><p>关注你关心的事，把消息集中在这里读。</p><form onSubmit={auth}>
    <label>邮箱<input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>
    <label>密码<input type="password" autoComplete={registering ? 'new-password' : 'current-password'} minLength={10} required value={password} onChange={e => setPassword(e.target.value)} placeholder="至少 10 位" /></label>
    {registering && <label>邀请码<input value={invite} onChange={e => setInvite(e.target.value)} placeholder="由邀请你的朋友提供" /></label>}
    <button className="primary" disabled={busy}>{busy ? '处理中…' : registering ? '创建账号' : '登录'}</button></form>
    <button className="link-button" onClick={() => { setRegistering(!registering); setError('') }}>{registering ? '已有账号，去登录' : '第一次使用？创建账号'}</button>{error && <p role="alert" className="error">{error}</p>}
    <footer>当前覆盖：股票公告、黄金宏观、电竞赛程。添加股票代码或 CS2 战队名称，查看各自来源状态。<br /><a href="/privacy.html" target="_blank" rel="noopener noreferrer">数据与来源说明 ↗</a></footer></section></main>

  const selected = options.filter(t => watches.includes(t.id))
  const matchedItems = items.filter(i => (filter === 'all' || i.matched_watch_ids.includes(filter)) && (!(unread || quickRead) || !i.is_read))
  const visible = quickRead ? matchedItems.slice(0, 3) : matchedItems
  const unreadCount = feedDiagnostics?.unread_count ?? items.filter(i => (filter === 'all' || i.matched_watch_ids.includes(filter)) && !i.is_read).length
  const hiddenCount = (feedDiagnostics?.hidden_not_interested ?? 0) + (feedDiagnostics?.hidden_duplicate ?? 0)
  const currentTopic = options.find(t => t.id === filter)
  const currentCoverage = coverages.find(c => c.watch_id === filter)
  return <div className="layout"><aside className="sidebar"><a className="brand" href="#">阅讯<span>个人资讯阅读台</span></a>
    <button className={filter === 'all' ? 'nav active' : 'nav'} disabled={busy} onClick={() => setFilter('all')}>全部关注 {filter === 'all' && <span>{feedDiagnostics?.eligible_count ?? items.length}</span>}</button>
    <div className="side-heading">我的关注<button onClick={() => setEditing(!editing)}>管理</button></div>
    {selected.map(t => <button className={filter === t.id ? 'nav active' : 'nav'} key={t.id} disabled={busy} onClick={() => setFilter(t.id)}>{t.name}{filter === t.id && <span>{feedDiagnostics?.eligible_count ?? 0}</span>}</button>)}
    <button className="add-shortcut" onClick={() => setEditing(true)}>＋ 添加关注</button>
    <div className="source-note"><strong>来源更新</strong>{sources.filter(s => s.automatic).map(s => <p key={s.id}>{s.label} · {sourceLabel(s.status)}<br />{updateTime(s.last_success_at)}</p>)}<p>{sources.find(s => s.id === 'stock_announcements')?.automatic ? '股票公告接口已配置。' : '股票自动公告待巨潮授权。'}<br />比赛记录来自 PandaScore；战队新闻由媒体 RSS 与公开新闻搜索补充。</p><a href="/privacy.html" target="_blank" rel="noopener noreferrer">数据与来源说明 ↗</a></div></aside>
    <main className="main"><header className="topbar"><span>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())}</span><div><button onClick={() => setEditing(!editing)}>管理关注</button><button onClick={logout}>退出</button></div></header>
    <div className="workspace"><section className="heading"><div><h1>{filter === 'all' ? '我的阅读台' : currentTopic?.name}</h1><p>{unreadCount ? `还有 ${unreadCount} 条未读。先看概况，再决定是否打开原文。` : '当前消息已读完。下次来源更新后再来看看。'}</p></div><button onClick={() => void refresh()} disabled={busy}>刷新</button></section>
    {error && <div className="message error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}{notice && <div className="message">{notice}</div>}
    {editing && <section className="settings"><div className="section-title"><h2>管理关注</h2><button onClick={() => setEditing(false)}>收起</button></div><p>添加后会按证券代码或战队对象匹配内容。</p><div className="topic-grid">{options.map(t => <button disabled={busy} key={t.id} className={watches.includes(t.id) ? 'topic selected' : 'topic'} onClick={() => void mutate('/watches', 'PUT', { watch_id: t.id, enabled: !watches.includes(t.id) })}>{t.name}<span>{watches.includes(t.id) ? '已关注' : '关注'}</span></button>)}</div>
      <div className="topic-kind"><button type="button" className={topicKind === 'stock' ? 'chosen' : ''} onClick={() => setTopicKind('stock')}>A 股代码</button><button type="button" className={topicKind === 'team' ? 'chosen' : ''} onClick={() => setTopicKind('team')}>CS2 战队</button></div><form className="topic-form" onSubmit={addTopic}>{topicKind === 'stock' ? <><label>六位证券代码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="例如 002491" value={stockCode} onChange={e => setStockCode(e.target.value)} /></label><label>显示名称（可选）<input maxLength={60} placeholder="留空时显示股票代码" value={topicName} onChange={e => setTopicName(e.target.value)} /></label></> : <label>CS2 战队名称<input required minLength={2} maxLength={60} placeholder="例如：绿龙 / Team Spirit" value={topicName} onChange={e => setTopicName(e.target.value)} /></label>}<button className="primary" disabled={busy}>添加并关注</button></form><p className="hint">股票自动公告使用巨潮资讯接口，需要在服务端配置账号和展示许可；此功能不提供实时行情。CS2 战队连接 PandaScore 公开赛程与比分，绿龙已映射为 Team Spirit；需配置免费的 API Token。它不覆盖战队官宣、采访或全部媒体新闻。Valve 游戏更新只保留历史收录，不再持续采集。</p></section>}
    <details className="sources-detail"><summary>来源与更新状态</summary><div className="sources-grid">{sources.map(s => <div key={s.id}><strong>{s.label}</strong><span className={s.status === 'failure' || s.status === 'stale' || s.status === 'partial' ? 'source-warning' : ''}>{sourceLabel(s.status)}</span><p>{s.description}</p>{s.automatic && <small>上次成功：{updateTime(s.last_success_at)}（北京时间）</small>}{s.id === 'cs2_team_fixtures' && s.last_result && <small className="run-summary">{pandascoreRun(s.last_result)}</small>}{s.id === 'web_news_search' && s.last_result && <small className="run-summary">最近一次搜索：返回 {s.last_result.entries ?? 0} 条 · 匹配 {s.last_result.matched ?? 0} 条 · 新增 {s.last_result.created ?? 0} 条{(s.last_result.matched ?? 0) === 0 ? ' · 覆盖不足' : ''}</small>}{s.id === 'cs2_team_news' && s.last_result && <small className="run-summary">最近一轮：读取 {s.last_result.entries ?? 0} 篇 · 相关 {s.last_result.matched ?? 0} 篇 · 新增 {s.last_result.created ?? 0} 篇{(s.last_result.matched ?? 0) === 0 ? " · 本轮未匹配到关注战队的新闻" : ""}</small>}{s.id === 'cs2_team_fixtures' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/team-source-setup.md" target="_blank" rel="noopener noreferrer">Token 配置指南 ↗</a>}{s.id === 'stock_announcements' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/stock-api-setup.md" target="_blank" rel="noopener noreferrer">股票来源配置说明 ↗</a>}{s.last_error && <p>{s.last_error}</p>}</div>)}</div></details>
    {filter !== 'all' && <div className="search-discovery"><button disabled={busy || !agent.search_configured} onClick={() => void searchNews()}>搜索这个关注的新消息</button><small>{agent.search_configured ? '仅搜索公开对象名称；结果按对象共享缓存。' : '公开新闻搜索尚未配置，已有来源仍可使用。'}</small></div>}
    {currentCoverage && <div className="coverage-note"><p>已收录：近30天新闻 {currentCoverage.news_count ?? 0} 条 · 比赛记录 {currentCoverage.match_count ?? 0} 条（含未来7天赛程）</p>{feedView !== 'news' && <strong className={currentCoverage.status === 'failure' || currentCoverage.status === 'stale' || currentCoverage.status === 'partial' ? 'source-warning' : ''}>比赛来源：{sourceLabel(currentCoverage.status)}</strong>}<p>{currentCoverage.description}</p>{feedView !== 'news' && currentCoverage.last_result && <small className="run-summary">{pandascoreRun(currentCoverage.last_result)}</small>}<small>最新新闻：{date(currentCoverage.latest_news_at)} · 最新比赛记录：{date(currentCoverage.latest_match_at)}（可含待赛）。收录数未扣除个人反馈隐藏的内容。</small></div>}
    <div className="mobile-topics"><select aria-label="筛选关注" disabled={busy} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部关注</option>{selected.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select><button onClick={() => setEditing(true)}>＋ 添加关注</button></div>
    <div className="reading-layout"><section><div className="feed-toolbar"><div className="tabs" aria-label="消息类型">{([['news', '新闻'], ['matches', '比赛'], ['all', '新闻和比赛']] as const).map(([value, label]) => <button key={value} className={feedView === value ? 'chosen' : ''} disabled={busy} onClick={() => { if (feedView !== value) { ++refreshVersion.current; setItems([]); setFeedView(value) } }}>{label}</button>)}</div></div><p className="filter-note">{feedView === 'news' ? '只展示近30天新闻；PandaScore 比分在「比赛」栏目。' : feedView === 'matches' ? '近30天比赛记录与未来7天赛程；PandaScore 赛事数据不代表战队新闻。' : '近30天新闻与比赛记录，以及未来7天赛程。'}</p><div className="feed-toolbar"><div className="tabs"><button className={!unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(false); setQuickRead(false) }}>全部</button><button className={unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(true); setQuickRead(false) }}>未读 {unreadCount}</button><button className={quickRead ? 'chosen' : ''} onClick={() => setQuickRead(true)}>先读三条</button></div><span>{visible.length} 条消息</span></div>
      {feedDiagnostics && <p className="filter-note">当前关注 · 当前栏目：候选 {feedDiagnostics.candidates} 条 · 反馈隐藏 {hiddenCount} 条 · 可展示 {feedDiagnostics.eligible_count} 条{feedDiagnostics.omitted_by_limit ? ` · 本页仅显示前 ${feedDiagnostics.returned_count} 条` : ''}{feedDiagnostics.candidate_limit_reached ? ' · 已达到500条候选上限' : ''}</p>}
      {!!feedDiagnostics?.hiding_feedback?.length && <details className="coverage-note" open={!visible.length}><summary>查看导致当前消息隐藏的反馈（最多20条）</summary>{feedDiagnostics.hiding_feedback.map(event => <div className="feedback" key={event.id}><div><strong>{event.action === 'duplicate' ? '重复消息' : '少看这类'}</strong><p>{event.title}</p></div><button disabled={busy} onClick={() => void mutate(`/feedback/${event.id}/undo`, 'POST')}>撤销这条反馈</button></div>)}</details>}
      {quickRead && <p className="filter-note">每次显示排序最靠前的三条未读。标为已读后，下一条会补上。</p>}
      {currentTopic?.stock_code && <p className="filter-note">证券代码：{currentTopic.stock_code} · 对象级匹配</p>}{currentTopic?.team_name && <p className="filter-note">CS2 战队：{currentTopic.team_name} · 对象级匹配</p>}
      {feedLoading ? <div className="empty" role="status">正在加载近期消息…</div> : !visible.length ? <div className="empty"><h2>{!watches.length ? '从添加关注开始' : unread || quickRead ? '没有未读消息' : hiddenCount ? '近期消息已被你的反馈隐藏' : feedView === 'news' ? '近30天暂无相关新闻' : '当前时间范围暂无比赛记录'}</h2><p>{!watches.length ? '添加一个 A 股代码或 CS2 战队名称。' : unread || quickRead ? '切回全部，仍可查看已经读过的记录。' : hiddenCount ? `近30天候选 ${feedDiagnostics?.candidates ?? 0} 条：${feedDiagnostics?.hidden_not_interested ?? 0} 条被「少看这类」隐藏，${feedDiagnostics?.hidden_duplicate ?? 0} 条被「重复消息」隐藏。可在「最近反馈」撤销对应记录。` : feedView === 'news' ? '当前关注近30天没有可展示的新闻候选，不使用旧赛果填充。可以搜索这个关注的新消息。' : '只展示近30天赛果与未来7天赛程，较早比赛已隐藏。'}</p>{filter !== 'all' && agent.search_configured && feedView === 'news' && <button disabled={busy} onClick={() => void searchNews()}>{busy ? '搜索中…' : '搜索这个关注的新消息'}</button>}<button onClick={() => setEditing(true)}>管理关注</button></div> : visible.map(item => <article className={`card ${item.is_read ? 'read' : ''}`} key={item.id}><div className="card-meta"><span>{nameOf(item.watch_id)}</span><span>{item.source_name}</span><span>{item.content_kind_label}</span><time>{date(item.published_at)}</time><span className="ingestion">{item.ingestion_mode === 'search' ? '搜索发现 · 日期待核验' : ['rss', 'api'].includes(item.ingestion_mode) ? '自动同步' : '手动收录'}</span></div><h2>{item.title}</h2><div className="overview"><span>{item.overview.kind}</span><p>{item.overview.text}</p></div>
        <div className="card-footer"><span className="ranking-reason">{item.reason}</span><button className="read-toggle" disabled={busy} onClick={() => void mutate('/reading', 'PUT', { item_id: item.id, read: !item.is_read })}>{item.is_read ? '已读 · 改为未读' : '标为已读'}</button></div>
        <div className="actions"><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'interested', reason: !item.content_kind || item.content_kind === 'other' ? 'hide_only' : 'content_type' })}>感兴趣</button><button disabled={busy} onClick={() => setFeedbackItem(feedbackItem === item.id ? null : item.id)}>少看这类</button><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'duplicate' })}>重复消息</button>{item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">查看原文 ↗</a> : <span>API 赛事记录 · 无原文网页</span>}</div>{feedbackItem === item.id && <div className="feedback-options"><p>这次想减少什么？</p>{([...(item.content_kind && item.content_kind !== 'other' ? [{ reason: 'content_type', label: `少看${item.content_kind_label}` }] : []), { reason: 'source', label: '少看这个来源' }, { reason: 'hide_only', label: '只隐藏这一条' }]).map(option => <button key={option.reason} disabled={busy} onClick={async () => { if (await mutate('/feedback', 'POST', { item_id: item.id, action: 'not_interested', reason: option.reason })) setFeedbackItem(null) }}>{option.label}</button>)}<button onClick={() => setFeedbackItem(null)}>取消</button><small>仅影响当前关注对象，可以在最近反馈中撤销。</small></div>}</article>)}
    </section><aside className="secondary"><section className="panel"><h2>本次阅读</h2><div className="reading-count"><strong>{unreadCount}</strong><span>未读 / 共 {items.length} 条</span></div><p>已读记录按账号保存，换设备后仍能接着读。点击“标为已读”确认，不凭打开链接推断阅读。</p><button onClick={() => setUnread(true)}>只看未读</button></section>
      <section className="panel"><h2>查一查消息</h2><p>支持关注名称或股票代码。默认查询已收录记录，可开启联网补搜。“最近”默认近 7 天，也支持“近 30 天”和“今天”。</p><label className="model-toggle"><input type="checkbox" checked={useModel} disabled={!agent.configured} onChange={e => setUseModel(e.target.checked)} />模型工具问答{agent.configured ? ` · ${agent.model}` : "（尚未配置）"}</label><label className="model-toggle"><input type="checkbox" checked={useSearch} disabled={!useModel || !agent.search_configured} onChange={e => setUseSearch(e.target.checked)} />允许库存不足时联网补搜一次</label><p><small>补搜仅将公开关注对象及固定搜索类别发送给搜索服务；不发送问题原文或个人反馈。开启模型后，本次问题、关注名称及检索到的短证据会发送给配置的模型服务；邮箱、密钥和完整反馈历史不发送。</small></p><form onSubmit={ask}><textarea className="query-input" placeholder="例如：总结绿龙最近的比赛和战队消息，列出依据" aria-label="资讯问题" minLength={3} maxLength={300} value={question} onChange={e => setQuestion(e.target.value)} /><button className="primary" disabled={busy || question.trim().length < 3}>查找</button></form>{answer && <div className="answer"><small>{answer.mode === "permission_denied" ? "权限限制" : answer.mode === "model_agent" ? "模型工具回答" : answer.mode === "model_fallback" ? "模型失败 · 检索回退" : answer.mode === "model_no_evidence" ? "没有可引用证据" : "已入库检索"}</small><p>{answer.notice}</p><p>{answer.answer}</p>{answer.citations.map((c, i) => c.url ? <a key={i} href={c.url} target="_blank" rel="noopener noreferrer">{c.title} ↗</a> : <p key={i}><strong>{c.title}</strong><br /><small>{c.source_name} · API 记录，无原文网页</small></p>)}<details><summary>查询记录</summary><small>{answer.run_id}</small><button type="button" onClick={() => { api<unknown>(`/runs/${answer.model_run_id || answer.run_id}`, token).then(r => setRunTrace(JSON.stringify(r, null, 2))).catch(e => setRunTrace(e.message)) }}>查看工具与费用记录</button><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{runTrace}</pre></details></div>}</section>
      <section className="panel"><h2>最近反馈</h2>{feedback.filter(e => !e.undone_at).slice(0, 5).map(e => <div className="feedback" key={e.id}><div><strong>{e.action === 'interested' ? '感兴趣' : e.action === 'duplicate' ? '重复消息' : '少看这类'}</strong><p>{items.find(i => i.id === e.item_id)?.title || '已隐藏的消息'}<br />{e.action === 'duplicate' ? '范围：同一事件' : e.reason === 'content_type' ? '范围：同一关注对象的同类内容' : e.reason === 'source' ? '范围：同一关注对象的同一来源' : e.reason === 'hide_only' ? '范围：仅这一条' : '范围：相关关注对象（旧反馈）'}</p></div><button disabled={busy} onClick={() => void mutate(`/feedback/${e.id}/undo`, 'POST')}>撤销</button></div>)}{!feedback.some(e => !e.undone_at) && <p>还没有反馈。选“少看这类”后，可选择内容类型、来源或只隐藏这一条；可以随时撤销。</p>}</section>
    </aside></div></div></main></div>
}
