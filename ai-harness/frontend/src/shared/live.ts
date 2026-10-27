// Живая активность агентов (решение владельца 27.10.2026): один SSE-поток
// /api/v1/activity/stream на всё приложение — доска, список, шапка карточки
// показывают «агент работает» и счётчик токенов (например «1300К»).
// Fallback: поллинг /api/v1/queue, если поток недоступен.

export interface LiveTask {
  code: string
  title: string
  agent: string
  minutes: number
  stale: boolean
  input: number
  output: number
  cache: number
  total: number
}

type Listener = () => void
const listeners = new Set<Listener>()
let snapshot: Record<string, LiveTask> = {}
let connected = false

function apply(tasks: LiveTask[]) {
  const next: Record<string, LiveTask> = {}
  for (const t of tasks) next[t.code] = t
  snapshot = next
  listeners.forEach((fn) => fn())
}

function startPolling() {
  connected = false
  listeners.forEach((fn) => fn())
  const tick = () => {
    void fetch('/api/v1/queue', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((d) => apply((d.working ?? []).map(
        (w: { code: string; agent: string; minutes?: number }) => ({
          code: w.code, title: '', agent: w.agent, minutes: w.minutes ?? 0,
          stale: false, input: 0, output: 0, cache: 0, total: 0,
        }))))
      .catch(() => {})
  }
  tick()
  return setInterval(tick, 5000)
}

let started = false
function start() {
  if (started) return
  started = true
  const connect = () => {
    const es = new EventSource('/api/v1/activity/stream')
    es.onopen = () => { connected = true; listeners.forEach((fn) => fn()) }
    es.onmessage = (e) => {
      try {
        apply((JSON.parse(e.data) as { tasks: LiveTask[] }).tasks)
      } catch { /* keep-alive */ }
    }
    es.onerror = () => {
      es.close()
      if (!pollTimer) pollTimer = startPolling()
      // поток вернётся при следующем переподключении вкладки — пробуем раз в 30 с
      if (!retryTimer) retryTimer = setInterval(() => {
        if (document.visibilityState !== 'visible') return
        es.close()
        clearInterval(retryTimer!); retryTimer = null
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        connect()
      }, 30000)
    }
  }
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let retryTimer: ReturnType<typeof setInterval> | null = null
  connect()
}

export function subscribeLive(fn: Listener): () => void {
  start()
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function currentLive(): Record<string, LiveTask> {
  return snapshot
}

export function liveTask(code: string): LiveTask | null {
  return snapshot[code] ?? null
}

/** «1300К» (1 300 000 токенов) — формат владельца. */
export function fmtTokens(n: number | null | undefined): string {
  if (!n) return ''
  return n >= 1000 ? `${Math.round(n / 1000)}К` : String(n)
}
