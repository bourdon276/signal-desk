import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { needsChineseTranslation } from './contentLanguage'

type FeedDiagnostics = { collapsed_sources?: number; kind_excluded: number; quality_excluded: number; hiding_feedback: { id: string; action: string; title: string }[]; candidates: number; hidden_not_interested: number; hidden_duplicate: number; eligible_count: number; unread_count: number; returned_count: number; candidate_limit_reached: boolean; omitted_by_limit: number }

type PersonalRun = { id: string; kind: string; status: string; started_at: string; finished_at: string | null; duration_ms: number | null; trace: { model_calls?: number; estimated_cost_cny?: number; tools?: unknown[]; [key: string]: unknown } }

type Translation = { title: string; summary: string; cache_hit: boolean; estimated_cost_cny: number | null; run_id?: string }

type FeedView = 'news' | 'matches' | 'all'
type RejectedSearchResult = { title: string; url: string | null; reason: string; published_at: string | null }
type SearchReport = { watchId: string; focus: string; text: string; pending: boolean; failed: boolean; rejected?: RejectedSearchResult[]; label?: string }

type Topic = { id: string; name: string; keywords?: string[]; index_code?: string | null; stock_code?: string | null; team_name?: string | null; team_watch_id?: string | null }
type Item = { event_group_basis?: string; source_count?: number; related_sources?: { id: string; title: string; url: string | null; source_name: string; published_at: string | null }[]; id: string; watch_id: string; matched_watch_ids: string[]; title: string; url: string | null; source_name: string; ingestion_mode: string; published_at: string | null; overview: { text: string; kind: string }; is_read: boolean; reason: string; content_kind: string; content_kind_label: string }
type Feedback = { id: string; item_id: string; action: string; reason: string | null; undone_at: string | null }
type SourceResult = { entries?: number; teams?: number; resolved_teams?: number; unresolved_teams?: number; matches?: number; matched?: number; created?: number; updated?: number; skipped?: number; full_pages?: number; dropped?: Record<string, number> }
type Source = { id: string; label: string; status: string; automatic: boolean; description: string; last_success_at: string | null; last_attempt_at: string | null; last_error: string | null; last_result?: SourceResult | null }
type Coverage = { watch_id: string; automatic: boolean; status: string; last_success_at: string | null; latest_item_at: string | null; latest_news_at: string | null; latest_match_at: string | null; description: string; matched_count: number; news_count: number; match_count: number; quality_excluded_count: number; last_result?: SourceResult | null }
type Answer = { answer: string; citations: { title: string; url: string | null; source_name?: string }[]; run_id: string; mode?: string; model_run_id?: string; notice?: string }

async function api<T>(path: string, token = '', options?: RequestInit): Promise<T> {
  let response: Response
  try {
    const timeout = !options?.method || options.method === 'GET' ? 90000 : 45000
    response = await fetch(`/api${path}`, { ...options, signal: AbortSignal.timeout(timeout), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  } catch (cause) {
    const name = (cause as Error).name
    throw new Error(name === 'TimeoutError' || name === 'AbortError'
      ? '服务响应超时，可能仍在启动，请稍后点击刷新。'
      : '暂时无法连接服务，请检查网络后重试。')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求未完成（${response.status}），请稍后重试`)
  return data
}
function searchDropLabel(reason: string) { return ({ generic_page_title: '网页通用标题，无法确认文章身份', focus_mismatch: '不属于所选新闻类型', prediction_or_betting: '预测或赔率内容', entity_mismatch: '与战队或股票不匹配', missing_cs2_context: '无法确认属于CS2', missing_date: '缺少可用日期', outside_30_days: '不在近30天', missing_or_outside_date: '日期缺失或超时', not_news_article: '非新闻页面', unapproved_url: '不在允许来源', url_owned_by_other_entity: '已归入其他对象' } as Record<string, string>)[reason] || '格式不完整' }
function sourceLabel(status: string) { return ({ success: '同步完成', partial: '部分同步', failure: '采集失败', running: '同步中', stale: '更新延迟', not_run: '等待首次同步', not_configured: '暂无自动更新', library_filter: '匹配来源库' } as Record<string, string>)[status] || status }
function updateTime(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value)) : '尚无记录' }
function date(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', timeZone: 'Asia/Shanghai' }).format(new Date(value)) : '日期未知' }
function pandascoreRun(result?: SourceResult | null) {
  if (!result) return ''
  const resolved = result.resolved_teams ?? 0, teams = result.teams ?? 0
  const dropped = Object.values(result.dropped || {}).reduce((sum, count) => sum + count, 0)
  return `最近一轮：已解析 ${resolved}/${teams} 个战队 · 收到 ${result.matches ?? 0} 场 · 可展示 ${result.matched ?? 0} 场 · 新增 ${result.created ?? 0} 条 · 更新 ${result.updated ?? 0} 条${dropped ? ` · 丢弃 ${dropped} 场（超出时间窗口、字段不完整或状态不支持）` : ''}${result.full_pages ? ` · ${result.full_pages} 个列表达到100条上限，结果可能不完整` : ''}`
}

export default function App() {
  const [agentStatus, setAgentStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [agent, setAgent] = useState<{ configured: boolean; model: string | null; search_configured?: boolean }>({ configured: false, model: null })
  const [useModel, setUseModel] = useState(false)
  const [useSearch, setUseSearch] = useState(false)
  const [searchFocus, setSearchFocus] = useState('auto')
  const [showRuns, setShowRuns] = useState(false)
  const [personalRuns, setPersonalRuns] = useState<PersonalRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const runsVersion = useRef(0)
  const [translations, setTranslations] = useState<Record<string, Translation>>({})
  const [translatingId, setTranslatingId] = useState<string | null>(null)
  const translationVersion = useRef(0)
  const [sharedUrl, setSharedUrl] = useState('')
  const [searchReport, setSearchReport] = useState<SearchReport | null>(null)
  const searchResultRef = useRef<HTMLDivElement>(null)
  const searchVersion = useRef(0)
  const [runTrace, setRunTrace] = useState('')
  const [token, setToken] = useState(() => localStorage.getItem('signal-token') || '')
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [invite, setInvite] = useState('')
  const [catalog, setCatalog] = useState<Topic[]>([]), [topics, setTopics] = useState<Topic[]>([])
  const [watches, setWatches] = useState<string[]>([]), [items, setItems] = useState<Item[]>([]), [feedback, setFeedback] = useState<Feedback[]>([])
  const [sources, setSources] = useState<Source[]>([]), [coverages, setCoverages] = useState<Coverage[]>([])
  const [topicKind, setTopicKind] = useState('stock'), [stockCode, setStockCode] = useState('')
  const [assetType, setAssetType] = useState('stock')
  const [preferences, setPreferences] = useState<Record<string, { feedback_count: number; signals: { kind: string; label: string; weight: number }[] }>>({})
  const [filter, setFilter] = useState('all'), [unread, setUnread] = useState(false)
  const [quickRead, setQuickRead] = useState(false)
  const [feedView, setFeedView] = useState<FeedView>('news')
  const refreshVersion = useRef(0)
  const [feedLoading, setFeedLoading] = useState(false)
  const [feedError, setFeedError] = useState(false)
  const [feedDiagnostics, setFeedDiagnostics] = useState<FeedDiagnostics | null>(null)
  const [feedbackItem, setFeedbackItem] = useState<string | null>(null)
  const [editing, setEditing] = useState(false), [topicName, setTopicName] = useState('')
  const [question, setQuestion] = useState(''), [answer, setAnswer] = useState<Answer | null>(null)
  const [asking, setAsking] = useState(false), [askError, setAskError] = useState('')
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const options = [...catalog, ...topics]
  const nameOf = (id: string) => options.find(t => t.id === id)?.name || options.find(t => (t.stock_code && `stock:${t.stock_code}` === id) || t.team_watch_id === id)?.name || id

  const refresh = useCallback(async (view: FeedView = feedView) => {
    if (!token) return
    const version = ++refreshVersion.current
    setFeedLoading(true); setFeedError(false); setError(''); setItems([]); setFeedDiagnostics(null)
    setAgentStatus('loading')
    void api<{ configured: boolean; model: string | null; search_configured?: boolean }>('/agent/status')
      .then(result => { if (version === refreshVersion.current) { setAgent(result); setAgentStatus('ready') } })
      .catch(() => { if (version === refreshVersion.current) setAgentStatus('error') })
    try {
      const { watches: w, feed: f, feedback: h, topics: t, catalog: cat, preferences: pref } = await api<{
        watches: { watch_ids: string[] }; feed: { items: Item[]; diagnostics: FeedDiagnostics };
        feedback: { events: Feedback[] }; topics: { topics: Topic[] }; catalog: { watches: Topic[] };
        preferences: { watches: typeof preferences };
      }>(`/desk?view=${view}&news_kind=${view === 'news' && ['interview', 'roster', 'financial'].includes(searchFocus) ? searchFocus : 'all'}${filter === 'all' ? '' : `&watch_id=${encodeURIComponent(filter)}`}`, token)
      if (version !== refreshVersion.current) return
      setWatches(w.watch_ids); setItems(f.items); setFeedDiagnostics(f.diagnostics); setFeedback(h.events); setTopics(t.topics); setCatalog(cat.watches); setPreferences(pref.watches)
      void api<{ sources: Source[] }>('/sources').then(r => { if (version === refreshVersion.current) setSources(r.sources) }).catch(() => {})
      void api<{ coverage: Coverage[] }>('/coverage', token).then(r => { if (version === refreshVersion.current) setCoverages(r.coverage) }).catch(() => {})
    } catch (cause) { if (version === refreshVersion.current) { setFeedError(true); setError((cause as Error).message) } }
    finally { if (version === refreshVersion.current) setFeedLoading(false) }
  }, [token, feedView, filter, searchFocus])
  useEffect(() => { setSearchFocus('auto'); setSearchReport(null); setSharedUrl('') }, [filter])
  useEffect(() => {
    if (searchReport?.watchId === filter && searchReport.focus === searchFocus) searchResultRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [searchReport, filter, searchFocus])
  useEffect(() => { void refresh() }, [refresh])

  async function auth(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const r = await api<{ token: string }>(registering ? '/register' : '/login', '', { method: 'POST', body: JSON.stringify({ email, password, invite_code: invite }) })
      localStorage.setItem('signal-token', r.token); setCatalog([]); setTopics([]); setWatches([]); setItems([]); setPreferences({}); setFilter('all'); setEmail(''); setPassword(''); setInvite(''); setToken(r.token)
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
      ? { name: topicName.trim(), stock_code: stockCode.trim(), asset_type: assetType }
      : { name: topicName.trim(), team_name: topicName.trim() }
    if (await mutate('/topics', 'POST', body)) {
      setEditing(false); setTopicName(''); setStockCode('')
      setNotice(topicKind === 'stock'
        ? '已加入你的个人关注。后台会搜索近期新闻；可选择此对象查看进度或主动搜索。'
        : '战队已加入你的个人关注。后台会采集近期媒体新闻与比赛；可主动搜索采访或转会。')
    }
  }
  async function searchNews() {
    if (busy || filter === 'all') return
    if (feedView !== 'news') { ++refreshVersion.current; setItems([]); setFeedView('news') }
    const version = ++searchVersion.current
    const report = { watchId: filter, focus: searchFocus }
    setBusy(true); setError(''); setNotice('')
    setSearchReport({ ...report, text: '正在搜索这个关注的新消息…', pending: true, failed: false })
    try {
      const r = await api<{ status: string; results: unknown[]; cache_hit?: boolean; search_credits: number; entries?: number; matched?: number; eligible_count?: number; not_visible_count?: number; dropped?: Record<string, number>; rejected?: RejectedSearchResult[]; effective_focus?: string }>('/search', token, { method: 'POST', body: JSON.stringify({ watch_id: filter, focus: searchFocus }) })
      if (version !== searchVersion.current) return
      setUnread(false); setQuickRead(false)
      await refresh('news')
      if (version !== searchVersion.current) return
      const labels: Record<string, string> = { not_configured: '搜索服务尚未配置，已有消息仍可阅读。', budget_exhausted: '搜索额度已达上限，稍后再试。', busy: '该对象正在搜索，请稍后刷新。', failure: '搜索未完成，已有消息仍可阅读。', outside_supported_scope: '当前仅支持已关注的 A 股或 CS2 战队。' }
      const dropped = Object.entries(r.dropped || {}).map(([reason, count]) => `${searchDropLabel(reason)} ${count} 条`).join('；')
      const detail = `搜索返回 ${r.entries ?? 0} 条，匹配入库 ${r.matched ?? 0} 条，当前可展示 ${r.eligible_count ?? r.results.length} 条。${dropped ? `过滤：${dropped}。` : ''}${r.not_visible_count ? `另有 ${r.not_visible_count} 条因当前范围、时间或个人反馈未展示。` : ''}`
      setSearchReport({ ...report, rejected: r.rejected, pending: false, failed: r.status !== 'success', text: r.status === 'success' ? `${r.cache_hit ? '复用缓存' : '搜索完成'}。${searchFocus === 'auto' ? `本次按你的偏好搜索${({ interview: '采访', roster: '阵容与转会', financial: '财报与业绩', recent: '近期新闻' } as Record<string, string>)[r.effective_focus || 'recent']}。` : ''}${detail}摘录未核验全文。已切到新闻栏目，展示全部阅读状态。` : labels[r.status] || '搜索未完成。' })
    } catch (cause) {
      if (version === searchVersion.current) setSearchReport({ ...report, text: (cause as Error).message, pending: false, failed: true })
    } finally { if (version === searchVersion.current) setBusy(false) }
  }
  async function importSharedNews(e: FormEvent) {
    e.preventDefault()
    if (busy || filter === 'all' || !sharedUrl.trim()) return
    if (feedView !== 'news') { ++refreshVersion.current; setItems([]); setFeedView('news') }
    const version = ++searchVersion.current
    const report = { watchId: filter, focus: searchFocus, label: '分享链接入库' }
    setBusy(true); setError(''); setNotice('')
    setSearchReport({ ...report, text: '正在读取完美世界电竞文章…', pending: true, failed: false })
    try {
      const r = await api<{ title: string; created: boolean; run_id: string }>('/shared-news', token, { method: 'POST', body: JSON.stringify({ watch_id: filter, url: sharedUrl.trim() }) })
      if (version !== searchVersion.current) return
      setSharedUrl(''); setUnread(false); setQuickRead(false)
      await refresh('news')
      if (version !== searchVersion.current) return
      setSearchReport({ ...report, text: `${r.created ? '已加入' : '已收录，无需重复加入'}：${r.title}。已切到新闻栏目；列表仍按所选新闻类型和个人反馈筛选。`, pending: false, failed: false })
    } catch (cause) {
      if (version === searchVersion.current) setSearchReport({ ...report, text: (cause as Error).message, pending: false, failed: true })
    } finally { if (version === searchVersion.current) setBusy(false) }
  }
  async function loadRuns() {
    const version = ++runsVersion.current
    setShowRuns(true); setRunsLoading(true); setError('')
    try {
      const result = await api<{ runs: PersonalRun[] }>('/runs?limit=50', token)
      if (version === runsVersion.current) setPersonalRuns(result.runs)
    } catch (cause) { if (version === runsVersion.current) { setPersonalRuns([]); setError((cause as Error).message) } }
    finally { if (version === runsVersion.current) setRunsLoading(false) }
  }
  function exportRuns() {
    const file = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), scope: 'own_latest_50_runs', runs: personalRuns }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(file)
    const link = document.createElement('a'); link.href = url; link.download = `signal-runs-${new Date().toISOString().slice(0, 10)}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function translateArticle(item: Item) {
    if (translatingId || translations[item.id] || !needsChineseTranslation(item.title, item.overview.text)) return
    const version = ++translationVersion.current
    setTranslatingId(item.id); setError('')
    try {
      const result = await api<Translation>(`/items/${encodeURIComponent(item.id)}/translate`, token, { method: 'POST' })
      if (version === translationVersion.current) setTranslations(previous => ({ ...previous, [item.id]: result }))
    } catch (cause) { if (version === translationVersion.current) setError((cause as Error).message) }
    finally { if (version === translationVersion.current) setTranslatingId(null) }
  }
  async function ask(e: FormEvent) {
    e.preventDefault(); if (busy || question.trim().length < 3) return; setBusy(true); setAsking(true); setAskError(''); setAnswer(null); setError(''); setRunTrace('')
    try { setAnswer(await api<Answer>('/ask', token, { method: 'POST', body: JSON.stringify({ question, use_model: useModel, use_search: useSearch }) })) }
    catch (cause) { const message = (cause as Error).message; setAskError(message); setError(message) } finally { setAsking(false); setBusy(false) }
  }
  function logout() { ++runsVersion.current; setShowRuns(false); setPersonalRuns([]); setRunsLoading(false); ++translationVersion.current; setTranslations({}); setTranslatingId(null); setSharedUrl(''); ++searchVersion.current; setSearchReport(null); setBusy(false); ++refreshVersion.current; setFeedLoading(false); setFeedError(false); setFeedDiagnostics(null); setFeedbackItem(null); setUseSearch(false); localStorage.removeItem('signal-token'); setToken(''); setEmail(''); setPassword(''); setInvite(''); setCatalog([]); setPreferences({}); setQuestion(''); setEditing(false); setItems([]); setFeedback([]); setTopics([]); setWatches([]); setAnswer(null); setAsking(false); setAskError(''); setError(''); setNotice(''); setFilter('all'); setCoverages([]); setSources([]); setUnread(false); setQuickRead(false) }

  if (!token) return <main className="login-page"><div className="login-title">阅讯<span>个人资讯阅读台</span></div><section className="login-box"><h1>{registering ? '创建账号' : '欢迎回来'}</h1><p>关注你关心的事，把消息集中在这里读。</p><form key={registering ? 'register' : 'login'} autoComplete={registering ? 'off' : 'on'} onSubmit={auth}>
    <label>邮箱<input name={registering ? 'signup-email' : 'login-email'} type="email" autoComplete={registering ? 'off' : 'username'} required value={email} onChange={e => setEmail(e.target.value)} /></label>
    <label>密码<input type="password" autoComplete={registering ? 'new-password' : 'current-password'} minLength={10} required value={password} onChange={e => setPassword(e.target.value)} placeholder="至少 10 位" /></label>
    {registering && <label>邀请码<input value={invite} onChange={e => setInvite(e.target.value)} placeholder="由邀请你的朋友提供" /></label>}
    <button className="primary" disabled={busy}>{busy ? (registering ? '正在创建账号…' : '正在登录…') : registering ? '创建账号' : '登录'}</button></form>
    <button className="link-button" disabled={busy} onClick={() => { setEmail(''); setPassword(''); setInvite(''); setRegistering(!registering); setError('') }}>{registering ? '已有账号，去登录' : '第一次使用？创建账号'}</button>{error && <p role="alert" className="error">{error}</p>}
    <footer>当前覆盖：股票公告、黄金宏观、电竞赛程。添加股票代码或 CS2 战队名称，查看各自来源状态。<br /><a href="/privacy.html" target="_blank" rel="noopener noreferrer">数据与来源说明 ↗</a></footer></section></main>

  const selected = options.filter(t => watches.includes(t.id))
  const matchedItems = items.filter(i => (filter === 'all' || i.matched_watch_ids.includes(filter)) && (!(unread || quickRead) || !i.is_read))
  const visible = quickRead ? matchedItems.slice(0, 3) : matchedItems
  const unreadCount = feedDiagnostics?.unread_count ?? items.filter(i => (filter === 'all' || i.matched_watch_ids.includes(filter)) && !i.is_read).length
  const hiddenCount = (feedDiagnostics?.hidden_not_interested ?? 0) + (feedDiagnostics?.hidden_duplicate ?? 0)
  const currentTopic = options.find(t => t.id === filter)
  const currentCoverage = coverages.find(c => c.watch_id === filter)
  const currentSearchReport = searchReport?.watchId === filter && searchReport.focus === searchFocus ? searchReport : null
  return <div className="layout"><aside className="sidebar"><a className="brand" href="#">阅讯<span>个人资讯阅读台</span></a>
    <button className={filter === 'all' ? 'nav active' : 'nav'} disabled={busy} onClick={() => setFilter('all')}>全部关注 {filter === 'all' && <span>{feedDiagnostics?.eligible_count ?? items.length}</span>}</button>
    <div className="side-heading">我的关注<button onClick={() => setEditing(!editing)}>管理</button></div>
    {selected.map(t => <button className={filter === t.id ? 'nav active' : 'nav'} key={t.id} disabled={busy} onClick={() => setFilter(t.id)}>{t.name}{filter === t.id && <span>{feedDiagnostics?.eligible_count ?? 0}</span>}</button>)}
    <button className="add-shortcut" onClick={() => setEditing(true)}>＋ 添加关注</button>
    <div className="source-note"><strong>来源更新</strong>{sources.filter(s => s.automatic).map(s => <p key={s.id}>{s.label} · {sourceLabel(s.status)}<br />{updateTime(s.last_success_at)}</p>)}<p>{sources.find(s => s.id === 'stock_announcements')?.automatic ? '股票公告接口已配置。' : '股票自动公告待巨潮授权。'}<br />比赛记录来自 PandaScore；战队新闻由媒体 RSS 与公开新闻搜索补充。</p><a href="/privacy.html" target="_blank" rel="noopener noreferrer">数据与来源说明 ↗</a></div></aside>
    <main className="main"><header className="topbar"><span>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())}</span><div><button disabled={runsLoading} onClick={() => void loadRuns()}>运行记录</button><button onClick={() => setEditing(!editing)}>管理关注</button><button onClick={logout}>退出</button></div></header>
    <div className="workspace"><section className="heading"><div><h1>{filter === 'all' ? '我的阅读台' : currentTopic?.name}</h1><p>{feedLoading ? '正在加载你的关注和消息…' : feedError ? '消息未加载完成，请重试。' : unreadCount ? `还有 ${unreadCount} 条未读。先看概况，再决定是否打开原文。` : '当前消息已读完。下次来源更新后再来看看。'}</p></div><button onClick={() => void refresh()} disabled={busy}>刷新</button></section>
    {error && <div className="message error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}{notice && <div className="message">{notice}</div>}
    {showRuns && <section className="settings run-history"><div className="section-title"><h2>我的运行记录</h2><button onClick={() => setShowRuns(false)}>收起</button></div><p>最近50条已记录操作；执行成功不代表回答准确。费用是按配置报价估算，缓存命中不一定产生新记录。</p><div className="run-actions"><button disabled={runsLoading} onClick={() => void loadRuns()}>刷新记录</button><button disabled={runsLoading || !personalRuns.length} onClick={exportRuns}>导出JSON</button></div>{runsLoading ? <p role="status">正在读取记录…</p> : !personalRuns.length ? <p>暂无已记录操作。完成一次模型问答或翻译后，刷新记录查看。</p> : personalRuns.map(run => <details key={run.id}><summary><span>{({ model_agent: '模型问答', evidence_answer: '库存检索', article_translation: '中文翻译', web_news_search_sync: '联网搜索', policy_denial: '权限拒绝', perfect_world_share_import: '分享导入', eastmoney_share_import: '文章导入' } as Record<string, string>)[run.kind] || run.kind} · {({ success: '完成', failure: '失败', running: '进行中' } as Record<string, string>)[run.status] || run.status}</span><small>{updateTime(run.started_at)} · {run.duration_ms === null ? '耗时待记录' : `${(run.duration_ms / 1000).toFixed(1)}秒`} · {typeof run.trace.estimated_cost_cny === 'number' ? `估算¥${run.trace.estimated_cost_cny.toFixed(5)}` : '费用未记录'}</small></summary><p>{run.id}</p><pre>{JSON.stringify(run.trace, null, 2)}</pre></details>)}</section>}
    {editing && <section className="settings"><div className="section-title"><h2>管理关注</h2><button onClick={() => setEditing(false)}>收起</button></div><p>这里只列出你自己的关注。添加股票、指数或战队后，后台采集近30天新闻。</p><button disabled={busy} onClick={() => void mutate('/watches', 'PUT', { watch_id: 'gold:london', enabled: true })}>＋ 关注伦敦金</button><div className="topic-grid">{options.map(t => <button disabled={busy} key={t.id} className={watches.includes(t.id) ? 'topic selected' : 'topic'} onClick={() => void mutate('/watches', 'PUT', { watch_id: t.id, enabled: !watches.includes(t.id) })}>{t.name}<span>{watches.includes(t.id) ? '已关注' : '关注'}</span></button>)}</div>{topics.filter(t => t.stock_code === '000001').map(t => <p key={t.id} className="hint">{t.name} 当前按平安银行匹配。若你要看上证指数：<button disabled={busy} onClick={() => void mutate(`/topics/${t.id}/as-index`, 'POST')}>改为上证指数</button></p>)}
      <div className="topic-kind"><button type="button" className={topicKind === 'stock' ? 'chosen' : ''} onClick={() => setTopicKind('stock')}>A 股代码</button><button type="button" className={topicKind === 'team' ? 'chosen' : ''} onClick={() => setTopicKind('team')}>CS2 战队</button></div><form className="topic-form" onSubmit={addTopic}>{topicKind === 'stock' ? <><label>关注对象<select value={assetType} onChange={e => setAssetType(e.target.value)}><option value="stock">A股公司（000001为平安银行）</option><option value="index">指数（000001为上证指数）</option></select></label><label>六位证券代码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="例如 002491" value={stockCode} onChange={e => setStockCode(e.target.value)} /></label><label>显示名称（可选）<input maxLength={60} placeholder="留空时显示股票代码" value={topicName} onChange={e => setTopicName(e.target.value)} /></label></> : <label>CS2 战队名称<input required minLength={2} maxLength={60} placeholder="例如：绿龙 / Team Spirit" value={topicName} onChange={e => setTopicName(e.target.value)} /></label>}<button className="primary" disabled={busy}>添加并关注</button></form><p className="hint">股票与指数收集近期媒体新闻；战队收集采访、转会和赛事报道，比分单独放在“比赛”。每条保留来源和日期。点“感兴趣”会提高同类内容优先级，并指导后续采集；“少看这类”会降低同类内容优先级。搜索受每日额度限制，来源状态可在下方查看。</p></section>}
    <details className="sources-detail"><summary>来源与更新状态</summary><div className="sources-grid">{sources.map(s => <div key={s.id}><strong>{s.label}</strong><span className={s.status === 'failure' || s.status === 'stale' || s.status === 'partial' ? 'source-warning' : ''}>{sourceLabel(s.status)}</span><p>{s.description}</p>{s.automatic && <small>上次成功：{updateTime(s.last_success_at)}（北京时间）</small>}{s.id === 'cs2_team_fixtures' && s.last_result && <small className="run-summary">{pandascoreRun(s.last_result)}</small>}{s.id === 'web_news_search' && s.last_result && <small className="run-summary">最近一次搜索：返回 {s.last_result.entries ?? 0} 条 · 匹配 {s.last_result.matched ?? 0} 条 · 新增 {s.last_result.created ?? 0} 条{(s.last_result.matched ?? 0) === 0 ? ' · 覆盖不足' : ''}</small>}{['cs2_team_news', 'dust2_br_news', 'perfect_world_share'].includes(s.id) && s.last_result && <small className="run-summary">最近一轮：读取 {s.last_result.entries ?? 0} 篇 · 相关 {s.last_result.matched ?? 0} 篇 · 新增 {s.last_result.created ?? 0} 篇{(s.last_result.matched ?? 0) === 0 ? " · 本轮未匹配到关注战队的新闻" : ""}</small>}{s.id === 'cs2_team_fixtures' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/team-source-setup.md" target="_blank" rel="noopener noreferrer">Token 配置指南 ↗</a>}{s.id === 'stock_announcements' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/stock-api-setup.md" target="_blank" rel="noopener noreferrer">股票来源配置说明 ↗</a>}{s.last_error && <p>{s.last_error}</p>}</div>)}</div></details>
    {filter !== 'all' && <div className="search-discovery"><label>新闻类型与搜索方向 <select aria-label="新闻类型与搜索方向" disabled={busy} value={searchFocus} onChange={e => setSearchFocus(e.target.value)}><option value="auto">按我的兴趣搜索</option><option value="recent">近期新闻（综合）</option>{currentTopic?.team_name ? <><option value="roster">阵容与转会</option><option value="interview">战队采访</option></> : !currentTopic?.index_code && <option value="financial">财报与业绩</option>}</select></label><button disabled={busy || !agent.search_configured} onClick={() => void searchNews()}>{currentSearchReport?.pending ? '搜索中…' : '搜索这个关注的新消息'}</button><small>{agent.search_configured ? '仅搜索公开对象名称；结果按对象共享缓存。' : '公开新闻搜索尚未配置，已有来源仍可使用。'}</small></div>}
    {filter !== 'all' && preferences[filter] && <div className="coverage-note"><strong>我的采集偏好</strong><p>{preferences[filter].signals.length ? preferences[filter].signals.map(signal => `${signal.weight > 0 ? '优先看' : '减少推荐'}${signal.label}`).join('；') : '还没有明确的内容类型偏好，先搜索综合新闻。'}</p><small>已记录 {preferences[filter].feedback_count} 次兴趣反馈。正向类型反馈会增加对应采集方向；负向反馈降低排序，已点“不感兴趣”的文章隐藏。“只隐藏这一条”不会改变采集方向，可在最近反馈撤销。</small></div>}
    {(currentTopic?.team_name || currentTopic?.stock_code || currentTopic?.index_code) && <form className="share-news-form" onSubmit={importSharedNews}><label htmlFor="shared-news-url">{currentTopic?.team_name ? '从完美世界电竞加入文章' : '从东方财富加入文章'}<input id="shared-news-url" type="url" required maxLength={500} disabled={busy} value={sharedUrl} onChange={e => setSharedUrl(e.target.value)} placeholder={currentTopic?.team_name ? '粘贴完美世界电竞的新闻分享链接' : '粘贴东方财富的财经或股票文章链接'} /></label><button disabled={busy || !sharedUrl.trim()} type="submit">加入这篇新闻</button><small>仅加入近30天、与当前关注对象相关的文章。保留原文链接，每人每天最多读取5次。</small></form>}
    {currentCoverage && <div className="coverage-note"><p>已收录：近30天新闻 {currentCoverage.news_count ?? 0} 条 · 比赛记录 {currentCoverage.match_count ?? 0} 条（含未来7天赛程）{currentCoverage.quality_excluded_count ? ` · 质量过滤 ${currentCoverage.quality_excluded_count} 条` : ''}</p>{feedView !== 'news' && <strong className={currentCoverage.status === 'failure' || currentCoverage.status === 'stale' || currentCoverage.status === 'partial' ? 'source-warning' : ''}>比赛来源：{sourceLabel(currentCoverage.status)}</strong>}<p>{currentCoverage.description}</p>{feedView !== 'news' && currentCoverage.last_result && <small className="run-summary">{pandascoreRun(currentCoverage.last_result)}</small>}<small>最新新闻：{date(currentCoverage.latest_news_at)} · 最新比赛记录：{date(currentCoverage.latest_match_at)}（可含待赛）。收录数未扣除个人反馈隐藏的内容。</small></div>}
    <div className="mobile-topics"><select aria-label="筛选关注" disabled={busy} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部关注</option>{selected.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select><button onClick={() => setEditing(true)}>＋ 添加关注</button></div>
    <div className="reading-layout"><section><div className="feed-toolbar"><div className="tabs" aria-label="消息类型">{([['news', '新闻'], ['matches', '比赛'], ['all', '新闻和比赛']] as const).map(([value, label]) => <button key={value} className={feedView === value ? 'chosen' : ''} disabled={busy} onClick={() => { if (feedView !== value) { ++refreshVersion.current; setItems([]); setFeedView(value) } }}>{label}</button>)}</div></div><p className="filter-note">{feedView === 'news' ? '仅展示近30天新闻；战队预测与赔率内容不展示，比分见「比赛」。' : feedView === 'matches' ? '近30天比赛记录与未来7天赛程；PandaScore 赛事数据不代表战队新闻。' : '近30天新闻与比赛记录，以及未来7天赛程。'}</p><div className="feed-toolbar"><div className="tabs"><button className={!unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(false); setQuickRead(false) }}>全部</button><button className={unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(true); setQuickRead(false) }}>未读 {unreadCount}</button><button className={quickRead ? 'chosen' : ''} onClick={() => setQuickRead(true)}>先读三条</button></div><span>{visible.length} 条消息</span></div>
      {feedView === 'news' && ['interview', 'roster', 'financial'].includes(searchFocus) && <p className="filter-note">仅展示：{({ interview: '战队采访', roster: '阵容与转会', financial: '财报与业绩' } as Record<string, string>)[searchFocus]}。切换类型只筛选已收录内容；点击搜索按钮才会联网搜索。</p>}
      {feedDiagnostics && <p className="filter-note">当前关注 · 当前栏目：候选 {feedDiagnostics.candidates} 条 · 类型过滤 {feedDiagnostics.kind_excluded ?? 0} 条 · 质量过滤 {feedDiagnostics.quality_excluded ?? 0} 条 · 反馈隐藏 {hiddenCount} 条 · 合并转载/同题 {feedDiagnostics.collapsed_sources ?? 0} 条 · 可展示 {feedDiagnostics.eligible_count} 条{feedDiagnostics.omitted_by_limit ? ` · 本页仅显示前 ${feedDiagnostics.returned_count} 条` : ''}{feedDiagnostics.candidate_limit_reached ? ' · 已达到500条候选上限' : ''}</p>}
      {!!feedDiagnostics?.hiding_feedback?.length && <details className="coverage-note" open={!visible.length}><summary>查看导致当前消息隐藏的反馈（最多20条）</summary>{feedDiagnostics.hiding_feedback.map(event => <div className="feedback" key={event.id}><div><strong>{event.action === 'duplicate' ? '重复消息' : '少看这类'}</strong><p>{event.title}</p></div><button disabled={busy} onClick={() => void mutate(`/feedback/${event.id}/undo`, 'POST')}>撤销这条反馈</button></div>)}</details>}
      {quickRead && <p className="filter-note">每次显示排序最靠前的三条未读。标为已读后，下一条会补上。</p>}
      {currentTopic?.stock_code && <p className="filter-note">证券代码：{currentTopic.stock_code} · 对象级匹配</p>}{currentTopic?.team_name && <p className="filter-note">CS2 战队：{currentTopic.team_name} · 对象级匹配</p>}
      {currentSearchReport && <div ref={searchResultRef} className={`message search-result${currentSearchReport.failed ? ' error' : ''}`} role={currentSearchReport.failed ? 'alert' : 'status'} aria-live="polite"><strong>{currentSearchReport.label || (currentSearchReport.pending ? '搜索进行中' : currentSearchReport.failed ? '搜索未完成' : '本次搜索结果')}</strong><div>{currentSearchReport.text}</div>{!!currentSearchReport.rejected?.length && <details><summary>查看被过滤的结果（{currentSearchReport.rejected.length}条）</summary><ul>{currentSearchReport.rejected.map((row, index) => <li key={index}>{row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.title} ↗</a> : row.title}<div><small>{searchDropLabel(row.reason)} · {date(row.published_at)}</small></div></li>)}</ul></details>}</div>}
      {feedLoading ? <div className="empty" role="status">正在加载近期消息…首次打开可能需要等待服务启动。</div> : feedError ? <div className="empty" role="alert"><h2>资讯未加载完成</h2><p>暂时无法确认你的关注和消息，请刷新重试。</p><button disabled={busy} onClick={() => void refresh()}>重新加载</button></div> : !visible.length ? <div className="empty"><h2>{!watches.length ? '从添加关注开始' : unread || quickRead ? '没有未读消息' : hiddenCount ? '近期消息已被你的反馈隐藏' : feedView === 'news' && ['interview', 'roster', 'financial'].includes(searchFocus) ? `近30天暂无可展示的${({ interview: '采访', roster: '阵容与转会报道', financial: '财报与业绩资讯' } as Record<string, string>)[searchFocus] || '所选类型新闻'}` : feedDiagnostics?.quality_excluded ? '当前收录仅有预测或赔率内容，已过滤' : feedView === 'news' ? '近30天暂无相关新闻' : '当前时间范围暂无比赛记录'}</h2><p>{!watches.length ? '添加一个 A 股代码或 CS2 战队名称。' : unread || quickRead ? '切回全部，仍可查看已经读过的记录。' : hiddenCount ? `近30天候选 ${feedDiagnostics?.candidates ?? 0} 条：${feedDiagnostics?.hidden_not_interested ?? 0} 条被「少看这类」隐藏，${feedDiagnostics?.hidden_duplicate ?? 0} 条被「重复消息」隐藏。可在「最近反馈」撤销对应记录。` : feedView === 'news' && ['interview', 'roster', 'financial'].includes(searchFocus) ? `当前只展示所选类型；${feedDiagnostics?.kind_excluded ?? 0} 条其他类型新闻已排除。搜索未找到匹配内容时保持为空，不以综合新闻填充。可选择「近期新闻」查看全部类型。` : feedDiagnostics?.quality_excluded ? `已过滤 ${feedDiagnostics.quality_excluded} 条预测或赔率内容。可以选择上方「阵容与转会」或「战队采访」方向搜索；已有反馈仍保留。` : feedView === 'news' ? '当前关注近30天没有可展示的新闻候选，不使用旧赛果填充。可以搜索这个关注的新消息。' : '只展示近30天赛果与未来7天赛程，较早比赛已隐藏。'}</p>{filter !== 'all' && agent.search_configured && feedView === 'news' && <button disabled={busy} onClick={() => void searchNews()}>{busy ? '搜索中…' : '搜索这个关注的新消息'}</button>}<button onClick={() => setEditing(true)}>管理关注</button></div> : visible.map(item => <article className={`card ${item.is_read ? 'read' : ''}`} key={item.id}><div className="card-meta"><span>{nameOf(item.watch_id)}</span><span>{item.source_name}</span><span>{item.content_kind_label}</span><time>{date(item.published_at)}</time><span className="ingestion">{item.ingestion_mode === 'search' ? '搜索发现 · 日期待核验' : ['rss', 'api'].includes(item.ingestion_mode) ? '自动同步' : '手动收录'}</span></div><h2>{translations[item.id]?.title || item.title}</h2><div className="overview"><span>{translations[item.id] ? '中文机器翻译 · 标题与短摘录，非全文' : item.overview.kind}</span><p>{translations[item.id]?.summary || item.overview.text}</p></div>
      {(item.source_count ?? 1) > 1 && <details className="translation-original"><summary>{item.event_group_basis === 'exact_title_same_day' ? '同题内容' : '同一事件'} · {item.source_count} 个来源</summary><p>仅合并当前列表中可展示的来源；阅读与反馈按各条记录保存。</p>{item.related_sources?.map(source => <p key={source.id}>{source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.source_name} · {source.title} ↗</a> : source.title}</p>)}</details>}
      {translations[item.id] ? <details className="translation-original"><summary>查看原文标题与摘录</summary><strong>{item.title}</strong><p>{item.overview.text}</p><small>{translations[item.id].cache_hit ? '复用已保存译文，本次未调用模型。' : '译文可能有误，请以原文核对数字和名称。'}</small></details> : agent.configured && item.content_kind !== 'match' && needsChineseTranslation(item.title, item.overview.text) && <div className="translation-control"><button disabled={busy || !!translatingId} onClick={() => void translateArticle(item)}>{translatingId === item.id ? '正在翻译…' : '译成中文'}</button><small>标题与短摘录发送给模型服务，费用计入现有模型预算。</small></div>}
        <div className="card-footer"><span className="ranking-reason">{item.reason}</span><button className="read-toggle" disabled={busy} onClick={() => void mutate('/reading', 'PUT', { item_id: item.id, read: !item.is_read })}>{item.is_read ? '已读 · 改为未读' : '标为已读'}</button></div>
        <div className="actions"><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'interested', reason: !item.content_kind || item.content_kind === 'other' ? 'hide_only' : 'content_type' })}>感兴趣</button><button disabled={busy} onClick={() => setFeedbackItem(feedbackItem === item.id ? null : item.id)}>少看这类</button><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'duplicate' })}>重复消息</button>{item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">查看原文 ↗</a> : <span>API 赛事记录 · 无原文网页</span>}</div>{feedbackItem === item.id && <div className="feedback-options"><p>这次想减少什么？</p>{([...(item.content_kind && item.content_kind !== 'other' ? [{ reason: 'content_type', label: `少看${item.content_kind_label}` }] : []), { reason: 'source', label: '少看这个来源' }, { reason: 'hide_only', label: '只隐藏这一条' }]).map(option => <button key={option.reason} disabled={busy} onClick={async () => { if (await mutate('/feedback', 'POST', { item_id: item.id, action: 'not_interested', reason: option.reason })) setFeedbackItem(null) }}>{option.label}</button>)}<button onClick={() => setFeedbackItem(null)}>取消</button><small>仅影响当前关注对象：同类或同来源内容降低排序，这一条会隐藏；可在最近反馈撤销。</small></div>}</article>)}
    </section><aside className="secondary"><section className="panel"><h2>本次阅读</h2><div className="reading-count"><strong>{unreadCount}</strong><span>未读 / 共 {items.length} 条</span></div><p>已读记录按账号保存，换设备后仍能接着读。点击“标为已读”确认，不凭打开链接推断阅读。</p><button onClick={() => setUnread(true)}>只看未读</button></section>
      <section className="panel"><h2>查一查消息</h2><p>支持关注名称或股票代码。默认查询已收录记录，可开启联网补搜。“最近”默认近 30 天，也支持“近 30 天”和“今天”。</p><label className="model-toggle"><input type="checkbox" checked={useModel} disabled={!agent.configured} onChange={e => setUseModel(e.target.checked)} />模型工具问答{agent.configured ? ` · ${agent.model}` : agentStatus === 'ready' ? "（尚未配置）" : agentStatus === 'error' ? "（配置状态获取失败，请刷新）" : "（正在检查配置）"}</label><label className="model-toggle"><input type="checkbox" checked={useSearch} disabled={!useModel || !agent.search_configured} onChange={e => setUseSearch(e.target.checked)} />允许库存不足时联网补搜一次</label><p><small>补搜仅将公开关注对象及固定搜索类别发送给搜索服务；不发送问题原文或个人反馈。开启模型后，本次问题、关注名称及检索到的短证据会发送给配置的模型服务；邮箱、密钥和完整反馈历史不发送。</small></p><form onSubmit={ask}><textarea className="query-input" placeholder="例如：总结绿龙最近的比赛和战队消息，列出依据" aria-label="资讯问题" minLength={3} maxLength={300} value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={e => {
        if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return
        e.preventDefault()
        if (!e.repeat && !busy && question.trim().length >= 3) e.currentTarget.form?.requestSubmit()
      }} /><small className="hint">Enter 提问 · Shift+Enter 换行</small><button className="primary" disabled={busy || question.trim().length < 3}>{asking ? '正在查询…' : '查找'}</button></form>{asking && <p role="status">正在检索与整理证据，请稍候。</p>}{askError && <div className="answer" role="alert"><strong>本次问答未完成</strong><p>{askError}</p><small>若请求超时，请先查看顶部「运行记录」，确认是否已完成，再决定是否重新提交。</small></div>}{answer && <div className="answer"><small>{answer.mode === "permission_denied" ? "权限限制" : answer.mode === "model_agent" ? "模型工具回答" : answer.mode === "model_fallback" ? "模型失败 · 检索回退" : answer.mode === "model_no_evidence" ? "没有可引用证据" : "已入库检索"}</small><p>{answer.notice}</p><p>{answer.answer}</p>{answer.citations.map((c, i) => c.url ? <a key={i} href={c.url} target="_blank" rel="noopener noreferrer">{c.title} ↗</a> : <p key={i}><strong>{c.title}</strong><br /><small>{c.source_name} · API 记录，无原文网页</small></p>)}<details><summary>查询记录</summary><small>{answer.run_id}</small><button type="button" onClick={() => { api<unknown>(`/runs/${answer.model_run_id || answer.run_id}`, token).then(r => setRunTrace(JSON.stringify(r, null, 2))).catch(e => setRunTrace(e.message)) }}>查看工具与费用记录</button><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{runTrace}</pre></details></div>}</section>
      <section className="panel"><h2>最近反馈</h2>{feedback.filter(e => !e.undone_at).slice(0, 5).map(e => <div className="feedback" key={e.id}><div><strong>{e.action === 'interested' ? '感兴趣' : e.action === 'duplicate' ? '重复消息' : '少看这类'}</strong><p>{items.find(i => i.id === e.item_id)?.title || '已反馈的消息'}<br />{e.action === 'duplicate' ? '范围：同一事件' : e.reason === 'content_type' ? '范围：同一关注对象的同类内容' : e.reason === 'source' ? '范围：同一关注对象的同一来源' : e.reason === 'hide_only' ? '范围：仅这一条' : '范围：相关关注对象（旧反馈）'}</p></div><button disabled={busy} onClick={() => void mutate(`/feedback/${e.id}/undo`, 'POST')}>撤销</button></div>)}{!feedback.some(e => !e.undone_at) && <p>还没有反馈。选“少看这类”后，可选择内容类型、来源或只隐藏这一条；可以随时撤销。</p>}</section>
    </aside></div></div></main></div>
}
