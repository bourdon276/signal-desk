type Options = {
  refresh: () => void
  blocked: () => boolean
  lastRefresh: () => number
  markAttempt: (now: number) => void
}
type Environment = {
  window: Pick<Window, 'addEventListener' | 'removeEventListener'>
  document: Pick<Document, 'addEventListener' | 'removeEventListener' | 'visibilityState'>
  now: () => number
  everyMinute: (callback: () => void) => () => void
}

export function startBackgroundRefresh(options: Options, environment: Environment = {
  window, document, now: Date.now,
  everyMinute: callback => {
    const timer = setInterval(callback, 60_000)
    return () => clearInterval(timer)
  },
}) {
  function updateIfStale() {
    const now = environment.now()
    if (environment.document.visibilityState !== 'visible' || options.blocked()
        || now - options.lastRefresh() < 5 * 60_000) return
    options.markAttempt(now)
    options.refresh()
  }
  const cancelTimer = environment.everyMinute(updateIfStale)
  environment.window.addEventListener('focus', updateIfStale)
  environment.document.addEventListener('visibilitychange', updateIfStale)
  return () => {
    cancelTimer()
    environment.window.removeEventListener('focus', updateIfStale)
    environment.document.removeEventListener('visibilitychange', updateIfStale)
  }
}
