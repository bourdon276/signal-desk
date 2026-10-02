import { FormEvent, useCallback, useEffect, useState } from 'react'

type Topic = { id: string; name: string; keywords?: string[]; stock_code?: string | null; team_name?: string | null; team_watch_id?: string | null }
type Item = { id: string; watch_id: string; matched_watch_ids: string[]; title: string; url: string; source_name: string; ingestion_mode: string; published_at: string | null; overview: { text: string; kind: string }; is_read: boolean; reason: string }
type Feedback = { id: string; item_id: string; action: string; undone_at: string | null }
type Source = { id: string; label: string; status: string; automatic: boolean; description: string; last_success_at: string | null; last_attempt_at: string | null; last_error: string | null }
type Coverage = { watch_id: string; automatic: boolean; status: string; last_success_at: string | null; latest_item_at: string | null; description: string; matched_count: number }
type Answer = { answer: string; citations: { title: string; url: string }[]; run_id: string }

async function api<T>(path: string, token = '', options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, signal: AbortSignal.timeout(30000), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求未完成（${response.status}），请稍后重试`)
  return data
}
function sourceLabel(status: string) { return ({ success: '已同步', failure: '采集失败', running: '同步中', stale: '更新延迟', not_run: '等待首次同步', not_configured: '暂无自动更新', library_filter: '匹配来源库' } as Record<string, string>)[status] || status }
function updateTime(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value)) : '尚无记录' }
function date(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(value)) : '日期未知' }

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('signal-token') || '')
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [invite, setInvite] = useState('')
  const [catalog, setCatalog] = useState<Topic[]>([]), [topics, setTopics] = useState<Topic[]>([])
  const [watches, setWatches] = useState<string[]>([]), [items, setItems] = useState<Item[]>([]), [feedback, setFeedback] = useState<Feedback[]>([])
  const [sources, setSources] = useState<Source[]>([]), [coverages, setCoverages] = useState<Coverage[]>([])
  const [topicKind, setTopicKind] = useState('stock'), [stockCode, setStockCode] = useState('')
  const [filter, setFilter] = useState('all'), [unread, setUnread] = useState(false)
  const [quickRead, setQuickRead] = useState(false)
  const [editing, setEditing] = useState(false), [topicName, setTopicName] = useState('')
  const [question, setQuestion] = useState('我关注的对象最近有什么消息？'), [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const options = [...catalog, ...topics]
  const nameOf = (id: string) => options.find(t => t.id === id)?.name || options.find(t => (t.stock_code && `stock:${t.stock_code}` === id) || t.team_watch_id === id)?.name || id

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const [w, f, h, t, s, c] = await Promise.all([
        api<{ watch_ids: string[] }>('/watches', token), api<{ items: Item[] }>('/feed?limit=100', token),
        api<{ events: Feedback[] }>('/feedback', token), api<{ topics: Topic[] }>('/topics', token), api<{ sources: Source[] }>('/sources'), api<{ coverage: Coverage[] }>('/coverage', token),
      ])
      setWatches(w.watch_ids); setItems(f.items); setFeedback(h.events); setTopics(t.topics); setSources(s.sources); setCoverages(c.coverage)
    } catch (cause) { setError((cause as Error).message) }
  }, [token])
  useEffect(() => { api<{ watches: Topic[] }>('/catalog').then(r => setCatalog(r.watches)).catch(() => setError('关注清单加载失败，请刷新页面')) }, [])
  useEffect(() => { void refresh() }, [refresh])

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
  async function ask(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try { setAnswer(await api<Answer>('/ask', token, { method: 'POST', body: JSON.stringify({ question }) })) }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  function logout() { localStorage.removeItem('signal-token'); setToken(''); setItems([]); setFeedback([]); setTopics([]); setWatches([]); setAnswer(null); setError(''); setNotice(''); setFilter('all'); setCoverages([]); setSources([]); setUnread(false); setQuickRead(false) }

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
  const unreadCount = items.filter(i => !i.is_read).length
  const currentTopic = options.find(t => t.id === filter)
  const currentCoverage = coverages.find(c => c.watch_id === filter)
  return <div className="layout"><aside className="sidebar"><a className="brand" href="#">阅讯<span>个人资讯阅读台</span></a>
    <button className={filter === 'all' ? 'nav active' : 'nav'} onClick={() => setFilter('all')}>全部关注 <span>{items.length}</span></button>
    <div className="side-heading">我的关注<button onClick={() => setEditing(!editing)}>管理</button></div>
    {selected.map(t => <button className={filter === t.id ? 'nav active' : 'nav'} key={t.id} onClick={() => setFilter(t.id)}>{t.name}<span>{items.filter(i => i.matched_watch_ids.includes(t.id)).length}</span></button>)}
    <button className="add-shortcut" onClick={() => setEditing(true)}>＋ 添加关注</button>
    <div className="source-note"><strong>来源更新</strong>{sources.filter(s => s.automatic).map(s => <p key={s.id}>{s.label} · {sourceLabel(s.status)}<br />{updateTime(s.last_success_at)}</p>)}<p>{sources.find(s => s.id === 'stock_announcements')?.automatic ? '股票公告接口已配置。' : '股票自动公告待巨潮授权。'}<br />CS2战队赛程需配置PandaScore Token；游戏公告低优先。</p><a href="/privacy.html" target="_blank" rel="noopener noreferrer">数据与来源说明 ↗</a></div></aside>
    <main className="main"><header className="topbar"><span>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())}</span><div><button onClick={() => setEditing(!editing)}>管理关注</button><button onClick={logout}>退出</button></div></header>
    <div className="workspace"><section className="heading"><div><h1>{filter === 'all' ? '我的阅读台' : currentTopic?.name}</h1><p>{unreadCount ? `还有 ${unreadCount} 条未读。先看概况，再决定是否打开原文。` : '当前消息已读完。下次来源更新后再来看看。'}</p></div><button onClick={() => void refresh()} disabled={busy}>刷新</button></section>
    {error && <div className="message error" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}{notice && <div className="message">{notice}</div>}
    {editing && <section className="settings"><div className="section-title"><h2>管理关注</h2><button onClick={() => setEditing(false)}>收起</button></div><p>添加后会按证券代码或战队对象匹配内容。</p><div className="topic-grid">{options.map(t => <button disabled={busy} key={t.id} className={watches.includes(t.id) ? 'topic selected' : 'topic'} onClick={() => void mutate('/watches', 'PUT', { watch_id: t.id, enabled: !watches.includes(t.id) })}>{t.name}<span>{watches.includes(t.id) ? '已关注' : '关注'}</span></button>)}</div>
      <div className="topic-kind"><button type="button" className={topicKind === 'stock' ? 'chosen' : ''} onClick={() => setTopicKind('stock')}>A 股代码</button><button type="button" className={topicKind === 'team' ? 'chosen' : ''} onClick={() => setTopicKind('team')}>CS2 战队</button></div><form className="topic-form" onSubmit={addTopic}>{topicKind === 'stock' ? <><label>六位证券代码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="例如 002491" value={stockCode} onChange={e => setStockCode(e.target.value)} /></label><label>显示名称（可选）<input maxLength={60} placeholder="留空时显示股票代码" value={topicName} onChange={e => setTopicName(e.target.value)} /></label></> : <label>CS2 战队名称<input required minLength={2} maxLength={60} placeholder="例如：绿龙 / Team Spirit" value={topicName} onChange={e => setTopicName(e.target.value)} /></label>}<button className="primary" disabled={busy}>添加并关注</button></form><p className="hint">股票自动公告使用巨潮资讯接口，需要在服务端配置账号和展示许可；此功能不提供实时行情。CS2 战队连接 PandaScore 公开赛程与比分，绿龙已映射为 Team Spirit；需配置免费的 API Token。它不覆盖战队官宣、采访或全部媒体新闻。Valve 游戏更新只保留历史收录，不再持续采集。</p></section>}
    <details className="sources-detail"><summary>来源与更新状态</summary><div className="sources-grid">{sources.map(s => <div key={s.id}><strong>{s.label}</strong><span className={s.status === 'failure' || s.status === 'stale' ? 'source-warning' : ''}>{sourceLabel(s.status)}</span><p>{s.description}</p>{s.automatic && <small>上次成功：{updateTime(s.last_success_at)}（北京时间）</small>}{s.id === 'cs2_team_fixtures' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/team-source-setup.md" target="_blank" rel="noopener noreferrer">Token 配置指南 ↗</a>}{s.id === 'stock_announcements' && <a href="https://github.com/bourdon276/signal-desk/blob/main/docs/stock-api-setup.md" target="_blank" rel="noopener noreferrer">股票来源配置说明 ↗</a>}{s.last_error && <p>{s.last_error}</p>}</div>)}</div></details>
    {currentCoverage && <div className="coverage-note"><strong>{sourceLabel(currentCoverage.status)}</strong><p>{currentCoverage.description}</p><small>最新收录消息：{date(currentCoverage.latest_item_at)}{currentCoverage.last_success_at ? ` · 上次同步 ${updateTime(currentCoverage.last_success_at)}` : ''}</small></div>}
    <div className="mobile-topics"><select aria-label="筛选关注" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部关注</option>{selected.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select><button onClick={() => setEditing(true)}>＋ 添加关注</button></div>
    <div className="reading-layout"><section><div className="feed-toolbar"><div className="tabs"><button className={!unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(false); setQuickRead(false) }}>全部</button><button className={unread && !quickRead ? 'chosen' : ''} onClick={() => { setUnread(true); setQuickRead(false) }}>未读 {unreadCount}</button><button className={quickRead ? 'chosen' : ''} onClick={() => setQuickRead(true)}>先读三条</button></div><span>{visible.length} 条消息</span></div>
      {quickRead && <p className="filter-note">每次显示排序最靠前的三条未读。标为已读后，下一条会补上。</p>}
      {currentTopic?.stock_code && <p className="filter-note">证券代码：{currentTopic.stock_code} · 对象级匹配</p>}{currentTopic?.team_name && <p className="filter-note">CS2 战队：{currentTopic.team_name} · 对象级匹配</p>}
      {!visible.length ? <div className="empty"><h2>{!watches.length ? '从添加关注开始' : unread || quickRead ? '没有未读消息' : '当前来源暂未覆盖这个关注'}</h2><p>{!watches.length ? '添加一个 A 股代码或 CS2 战队名称。' : unread || quickRead ? '切回全部，仍可查看已经读过的记录。' : '已保存这个对象关注。请查看来源状态；如果来源未配置，当前还不会有自动消息。'}</p><button onClick={() => setEditing(true)}>管理关注</button></div> : visible.map(item => <article className={`card ${item.is_read ? 'read' : ''}`} key={item.id}><div className="card-meta"><span>{nameOf(item.watch_id)}</span><span>{item.source_name}</span><time>{date(item.published_at)}</time><span className="ingestion">{['rss', 'api'].includes(item.ingestion_mode) ? '自动同步' : '手动收录'}</span></div><h2>{item.title}</h2><div className="overview"><span>{item.overview.kind}</span><p>{item.overview.text}</p></div>
        <div className="card-footer"><span className="ranking-reason">{item.reason}</span><button className="read-toggle" disabled={busy} onClick={() => void mutate('/reading', 'PUT', { item_id: item.id, read: !item.is_read })}>{item.is_read ? '已读 · 改为未读' : '标为已读'}</button></div>
        <div className="actions"><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'interested' })}>感兴趣</button><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'not_interested' })}>少看这类</button><button disabled={busy} onClick={() => void mutate('/feedback', 'POST', { item_id: item.id, action: 'duplicate' })}>重复消息</button><a href={item.url} target="_blank" rel="noopener noreferrer">查看原文 ↗</a></div></article>)}
    </section><aside className="secondary"><section className="panel"><h2>本次阅读</h2><div className="reading-count"><strong>{unreadCount}</strong><span>未读 / 共 {items.length} 条</span></div><p>已读记录按账号保存，换设备后仍能接着读。点击“标为已读”确认，不凭打开链接推断阅读。</p><button onClick={() => setUnread(true)}>只看未读</button></section>
      <section className="panel"><h2>查一查消息</h2><p>支持关注名称或股票代码。当前只检索已收录记录。</p><form onSubmit={ask}><textarea aria-label="资讯问题" minLength={3} maxLength={300} value={question} onChange={e => setQuestion(e.target.value)} /><button className="primary" disabled={busy || question.trim().length < 3}>查找</button></form>{answer && <div className="answer"><p>{answer.answer}</p>{answer.citations.map(c => <a key={c.url} href={c.url} target="_blank" rel="noopener noreferrer">{c.title} ↗</a>)}<details><summary>查询记录</summary><small>{answer.run_id}</small></details></div>}</section>
      <section className="panel"><h2>最近反馈</h2>{feedback.filter(e => !e.undone_at).slice(0, 5).map(e => <div className="feedback" key={e.id}><div><strong>{e.action === 'interested' ? '感兴趣' : e.action === 'duplicate' ? '重复消息' : '少看这类'}</strong><p>{items.find(i => i.id === e.item_id)?.title || '已隐藏的消息'}</p></div><button disabled={busy} onClick={() => void mutate(`/feedback/${e.id}/undo`, 'POST')}>撤销</button></div>)}{!feedback.some(e => !e.undone_at) && <p>还没有反馈。选“少看这类”会隐藏该条并下调相关主题；可以随时撤销。</p>}</section>
    </aside></div></div></main></div>
}
