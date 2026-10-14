// Exercise actual focus/visibility/timer subscriptions with a fake clock; no browser or network.
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

const { startBackgroundRefresh } = await import(pathToFileURL(process.argv[2]).href)
const win = new EventTarget(), doc = new EventTarget()
doc.visibilityState = 'hidden'
let now = 1_000_000, last = 0, calls = 0, blocked = false, tick, cancelled = false
const stop = startBackgroundRefresh({
  refresh: () => { calls++ }, blocked: () => blocked,
  lastRefresh: () => last, markAttempt: value => { last = value },
}, { window: win, document: doc, now: () => now,
  everyMinute: callback => { tick = callback; return () => { cancelled = true } },
})
tick(); win.dispatchEvent(new Event('focus'))
assert.equal(calls, 0, 'a hidden tab must not request the desk')
doc.visibilityState = 'visible'
doc.dispatchEvent(new Event('visibilitychange')); win.dispatchEvent(new Event('focus')); tick()
assert.equal(calls, 1, 'focus and visibility bursts must create only one request')
now += 6 * 60_000; blocked = true
tick(); win.dispatchEvent(new Event('focus'))
assert.equal(calls, 1, 'reading/submitting/editing must block background changes')
blocked = false; tick()
assert.equal(calls, 2, 'after interaction ends, a stale visible view is refreshed')
stop(); now += 6 * 60_000
win.dispatchEvent(new Event('focus')); doc.dispatchEvent(new Event('visibilitychange'))
assert.equal(calls, 2, 'after logout/unmount, event handlers must be removed')
assert.equal(cancelled, true, 'after logout/unmount, the timer must stop')
console.log('PASS: hidden tab, focus deduplication, interaction guard, resumed refresh, logout cleanup')
