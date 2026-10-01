import { FormEvent, useCallback, useEffect, useState } from 'react'

type WatchOption = { id: string; name: string }
type FeedItem = {
  id: string; watch_id: string; title: string; summary: string; url: string;
  source_name: string; source_type: string; ingestion_mode: string;
  published_at: string | null; score: number; reason: string
}
type Feedback = { id: string; item_id: string; action: string; created_at: string; undone_at: string | null }
type Answer = { answer: string; citations: { title: string; url: string }[]; run_id: string }
type Source = { id: string; label: string; status: string; last_success_at: string | null; last_error: string | null }

const watchNames: Record<string, string> = {
  'stock:002491': '通鼎互联', 'stock:002296': '辉煌科技', 'gold:london': '伦敦金宏观',
  'esports:lol': '英雄联盟', 'esports:cs2': 'CS2', 'esports:valorant': '无畏契约',
}

async function request<T>(path: string, token?: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    signal: AbortSignal.timeout(30000),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options?.headers },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `请求失败（${response.status}）`)
  return body as T
}

function prettyTime(value: string | null) {
  if (!value) return '发布时间未知'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('signal-token') || '')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [registering, setRegistering] = useState(false)
  const [watches, setWatches] = useState<string[]>([])
  const [catalog, setCatalog] = useState<WatchOption[]>([])
  const [items, setItems] = useState<FeedItem[]>([])
  const [feedback, setFeedback] = useState<Feedback[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [filter, setFilter] = useState('all')
  const [question, setQuestion] = useState('我关注的对象最近有什么消息？')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const [watchData, feedData, feedbackData] = await Promise.all([
        request<{ watch_ids: string[] }>('/watches', token),
        request<{ items: FeedItem[] }>('/feed', token),
        request<{ events: Feedback[] }>('/feedback', token),
      ])
      setWatches(watchData.watch_ids)
      setItems(feedData.items)
      setFeedback(feedbackData.events)
    } catch (cause) { setError((cause as Error).message) }
  }, [token])

  useEffect(() => { request<{ watches: WatchOption[] }>('/catalog').then(data => setCatalog(data.watches)).catch(() => setCatalog(Object.entries(watchNames).map(([id, name]) => ({ id, name })))) }, [])
  useEffect(() => { request<{ sources: Source[] }>('/sources').then(data => setSources(data.sources)).catch(() => setSources([])) }, [])
  useEffect(() => { void refresh() }, [refresh])

  async function authenticate(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true)
    try {
      const data = await request<{ token: string }>(registering ? '/register' : '/login', undefined, {
        method: 'POST', body: JSON.stringify({ email, password, invite_code: inviteCode }),
      })
      localStorage.setItem('signal-token', data.token)
      setToken(data.token)
      setPassword('')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function toggleWatch(id: string) {
    if (saving) return
    setSaving(true)
    setError('')
    try {
      await request('/watches', token, { method: 'PUT', body: JSON.stringify({ watch_id: id, enabled: !watches.includes(id) }) })
      await refresh()
    } catch (cause) { setError((cause as Error).message) } finally { setSaving(false) }
  }

  async function react(item: FeedItem, action: string) {
    if (saving) return
    setSaving(true)
    setError('')
    try {
      await request('/feedback', token, { method: 'POST', body: JSON.stringify({ item_id: item.id, action }) })
      await refresh()
    } catch (cause) { setError((cause as Error).message) } finally { setSaving(false) }
  }

  async function undo(id: string) {
    if (saving) return
    setSaving(true)
    try { await request(`/feedback/${id}/undo`, token, { method: 'POST' }); await refresh() }
    catch (cause) { setError((cause as Error).message) } finally { setSaving(false) }
  }

  async function ask(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setAnswer(null)
    try { setAnswer(await request<Answer>('/ask', token, { method: 'POST', body: JSON.stringify({ question }) })) }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  const visible = filter === 'all' ? items : items.filter(item => item.watch_id === filter)

  if (!token) return <main className="auth-shell">
    <div className="auth-brand"><div className="brand-mark">S</div><span>SIGNAL DESK</span></div>
    <section className="auth-panel">
      <div className="eyebrow">YOUR PERSONAL INTELLIGENCE FEED</div>
      <h1>让重要消息<br /><em>自己浮上来。</em></h1>
      <p>股票、黄金宏观与电竞资讯集中在一处。每次反馈都会改变下一次看到的内容，所有卡片都能回到原文。</p>
      <form onSubmit={authenticate} className="auth-form">
        <label>邮箱<input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" /></label>
        <label>密码<input type="password" minLength={10} required value={password} onChange={e => setPassword(e.target.value)} placeholder="至少 10 位" /></label>
        {registering && <label>邀请码（公开试用时填写）<input value={inviteCode} onChange={e => setInviteCode(e.target.value)} placeholder="本地开发可留空" /></label>}
        <button className="primary" disabled={busy}>{busy ? '请稍候…' : registering ? '创建账号' : '进入工作台'}</button>
      </form>
      <button className="text-button" onClick={() => setRegistering(!registering)}>{registering ? '已有账号？登录' : '第一次使用？创建账号'}</button>
      {error && <p className="error">{error}</p>}
    </section>
    <div className="auth-foot">真实来源 · 可撤销反馈 · 原文可追溯</div>
  </main>

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="logo"><div className="brand-mark">S</div><span>SIGNAL<br />DESK</span></div>
      <div className="nav-label">工作台</div>
      <button className={`nav-item ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}><span>◫</span> 全部资讯 <b>{items.length}</b></button>
      <div className="nav-label topics-label">我的关注</div>
      {catalog.map(watch => <button key={watch.id} className={`nav-item ${filter === watch.id ? 'active' : ''}`} onClick={() => setFilter(watch.id)}><span className="topic-dot" />{watch.name}<b>{items.filter(item => item.watch_id === watch.id).length}</b></button>)}
      <div className="sidebar-bottom"><span className="status-dot" />{sources[0]?.status === 'success' ? `RSS 上次成功：${prettyTime(sources[0].last_success_at)}` : sources[0]?.status === 'failure' ? 'RSS 同步失败；保留已有消息' : 'RSS 尚未同步'}</div>
    </aside>
    <main className="content">
      <header className="topbar"><span>个人资讯雷达 <small>/ 今日工作台</small></span><button onClick={() => { localStorage.removeItem('signal-token'); setToken(''); setItems([]) }}>退出登录 ↗</button></header>
      <div className="content-inner">
        <section className="hero"><div><div className="eyebrow">INFORMATION, WITH CONTEXT</div><h1>你的信息，<em>经过筛选。</em></h1><p>从真实来源开始，用每一次反馈调整排序。未经证实的内容不会被写成事实。</p></div><div className="hero-stat"><strong>{items.length}</strong><span>条当前可见资讯</span></div></section>
        {error && <div className="error-banner">{error}<button onClick={() => setError('')}>关闭</button></div>}
        <section className="watch-panel"><div className="section-heading"><div><span className="eyebrow">01 / YOUR SIGNALS</span><h2>关注清单</h2></div><p>选择你想持续追踪的对象</p></div><div className="watch-grid">{catalog.map(watch => <button key={watch.id} className={`watch-chip ${watches.includes(watch.id) ? 'selected' : ''}`} onClick={() => toggleWatch(watch.id)}><span>{watch.name}</span><b>{watches.includes(watch.id) ? '✓ 已关注' : '+ 关注'}</b></button>)}</div><p className="coverage-note">自动来源：美联储货币政策 RSS（伦敦金宏观候选），{sources[0]?.status === 'success' ? `上次成功 ${prettyTime(sources[0].last_success_at)}` : sources[0]?.status === 'failure' ? '最近同步失败，显示已有内容' : '尚未同步'}。股票与电竞当前仅有手动收录链接，尚无自动覆盖。</p></section>
        <div className="columns"><section className="feed-section"><div className="section-heading"><div><span className="eyebrow">02 / CURATED FEED</span><h2>{filter === 'all' ? '为你筛选' : watchNames[filter]}</h2></div><button className="refresh" onClick={refresh}>↻ 刷新</button></div>{!watches.length ? <div className="empty"><strong>先选择关注对象</strong><p>上方点选股票、黄金或电竞主题，资讯会出现在这里。</p></div> : !visible.length ? <div className="empty"><strong>这里暂时没有可展示的消息</strong><p>可能是来源尚未接入，或该对象还没有收录内容。系统不会补造消息。</p></div> : <div className="feed-list">{visible.map(item => <article className="item-card" key={item.id}><div className="item-meta"><span className="category">{watchNames[item.watch_id]}</span><span>{item.source_type === 'official' ? '官方' : item.source_type === 'community' ? '社区' : '媒体'}</span><span>{item.ingestion_mode === 'rss' ? 'RSS 自动同步' : '手动收录'}</span></div><h3><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title} ↗</a></h3>{item.summary && <p className="summary">{item.summary}</p>}<div className="item-bottom"><span>{item.source_name} · {prettyTime(item.published_at)}</span><span className="reason">{item.reason}</span></div><div className="item-actions"><button onClick={() => react(item, 'interested')}>＋ 感兴趣</button><button onClick={() => react(item, 'not_interested')}>－ 没兴趣</button><button onClick={() => react(item, 'duplicate')}>⊘ 重复</button><a href={item.url} target="_blank" rel="noopener noreferrer">查看原文 →</a></div></article>)}</div>}</section>
          <aside className="right-column"><section className="assistant-card"><div className="eyebrow">03 / ASK YOUR FEED</div><div className="assistant-icon">✳</div><h2>问问你的资讯</h2><p>只从你关注且已入库的消息中回答，找不到依据就明确说不知道。</p><form onSubmit={ask}><textarea maxLength={300} value={question} onChange={e => setQuestion(e.target.value)} /><button className="primary" disabled={busy || !question.trim()}>{busy ? '检索中…' : '提出问题 →'}</button></form>{answer && <div className="answer"><strong>回答</strong><p>{answer.answer}</p>{answer.citations.map(c => <a key={c.url} href={c.url} target="_blank" rel="noopener noreferrer">↗ {c.title}</a>)}<small>运行 ID：{answer.run_id}</small></div>}</section><section className="memory-card"><div className="eyebrow">04 / YOUR MEMORY</div><h2>最近反馈</h2>{feedback.filter(e => !e.undone_at).slice(0, 5).length ? feedback.filter(e => !e.undone_at).slice(0, 5).map(e => <div className="memory-row" key={e.id}><span>{e.action === 'interested' ? '感兴趣' : e.action === 'duplicate' ? '重复' : '没兴趣'}</span><button onClick={() => undo(e.id)}>撤销</button></div>) : <p>你的反馈会留在这里，随时可以撤销。</p>}</section></aside></div>
      </div>
    </main>
  </div>
}
