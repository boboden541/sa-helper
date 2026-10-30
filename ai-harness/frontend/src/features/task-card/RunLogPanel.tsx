// Живые логи прогона агента (решение владельца 26.10.2026): SSE-поток с
// фолбэком на поллинг; строки — промт (свёрнут), размышления (целиком),
// вызовы инструментов, результаты, отчёт; кнопка «Прервать» (ФТ-ah-32).

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { fmtTokens } from '../../shared/live'
import { toast } from '../../shared/toast'

interface RunInfo {
  id: string
  attempt: number
  running: boolean
  stale: boolean
  outcome: string | null
  agent: string
  startedAt: string
  heartbeatAt: string | null
  finishedAt: string | null
  statusKey: string
  input: number
  output: number
  cache: number
  tokens: number
}

interface LogLine { seq: number; kind: string; text: string | null; data?: { [k: string]: unknown } | null; at: string }

const KIND_LABEL: Record<string, string> = {
  prompt: 'промт', thinking: 'агент', tool: 'инструмент', tool_result: 'результат',
  system: 'система', report: 'отчёт',
}
const KIND_COLOR: Record<string, string> = {
  prompt: '#c07d1e', thinking: '#3d63d2', tool: '#7d4fd1',
  tool_result: '#8792a3', system: '#8792a3', report: '#25935b',
}

function Line({ l }: { l: LogLine }) {
  const color = KIND_COLOR[l.kind] ?? '#8792a3'
  if (l.kind === 'prompt') {
    return (
      <details className="rl-row">
        <summary style={{ color }}><b>промт</b> · скилл и контекст задачи ({(l.text ?? '').length} симв.)</summary>
        <pre>{l.text}</pre>
      </details>
    )
  }
  if (l.kind === 'tool') {
    const inp = l.data?.input ? JSON.stringify(l.data.input, null, 1) : ''
    return (
      <div className="rl-row">
        <span className="rl-kind" style={{ color }}>{KIND_LABEL[l.kind]}</span>
        <code className="rl-tool">{l.text}</code>
        {inp && <details><summary>аргументы</summary><pre>{inp}</pre></details>}
      </div>
    )
  }
  return (
    <div className="rl-row">
      <span className="rl-kind" style={{ color }}>{KIND_LABEL[l.kind] ?? l.kind}</span>
      <span className="rl-text">{l.text}</span>
    </div>
  )
}

export function RunLogPanel({ code }: { code: string }) {
  const [runs, setRuns] = useState<RunInfo[]>([])
  const [lines, setLines] = useState<LogLine[]>([])
  const [viewRun, setViewRun] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [nudge, setNudge] = useState(0)  // клик по активному прогону переподключает поток
  const boxRef = useRef<HTMLDivElement>(null)
  const pinBottom = useRef(true)

  const active = runs.find((r) => r.running) ?? null

  const reloadRuns = () => {
    void api.runs(code).then((r) => {
      setRuns(r)
      // по умолчанию показываем лог последнего прогона
      setViewRun((cur) => cur ?? r[0]?.id ?? null)
    }).catch(() => {})
  }
  useEffect(reloadRuns, [code])
  useEffect(() => {
    const t = setInterval(reloadRuns, 5000)
    return () => clearInterval(t)
  }, [code])

  // активный прогон: SSE; ошибка/закрытие → поллинг раз в 2 с
  useEffect(() => {
    if (!active?.id) { setLive(false); return }
    setViewRun(active.id)
    setLines([])
    pinBottom.current = true
    let last = 0
    let poll: ReturnType<typeof setInterval> | null = null
    const append = (items: LogLine[]) => {
      if (!items.length) return
      setLines((cur) => [...cur, ...items.filter((x) => x.seq > (cur[cur.length - 1]?.seq ?? 0))])
    }
    const startPolling = () => {
      if (poll) return
      setLive(false)
      poll = setInterval(() => {
        void api.runLog(active.id, last).then((r: { items: LogLine[]; last: number }) => {
          last = r.last
          append(r.items)
        }).catch(() => {})
      }, 2000)
    }
    const es = new EventSource(`/api/v1/tasks/${code}/run-log/stream`)
    es.onopen = () => setLive(true)
    es.onmessage = (e) => {
      try {
        const item = JSON.parse(e.data) as LogLine
        last = Math.max(last, item.seq)
        append([item])
      } catch { /* keep-alive или мусор — игнорируем */ }
    }
    es.onerror = () => { es.close(); startPolling() }
    return () => {
      es.close()
      if (poll) clearInterval(poll)
    }
  }, [active?.id, code, nudge])

  // завершение прогона — добираем хвост поллингом
  useEffect(() => {
    if (active?.id || !viewRun) return
    void api.runLog(viewRun, 0).then((r: { items: LogLine[] }) => setLines(r.items)).catch(() => {})
  }, [active?.id, viewRun])

  // автопрокрутка, если зритель у низа
  useEffect(() => {
    const box = boxRef.current
    if (box && pinBottom.current) box.scrollTop = box.scrollHeight
  }, [lines])

  const openHistory = (runId: string) => {
    setViewRun(runId)
    void api.runLog(runId, 0).then((r: { items: LogLine[] }) => setLines(r.items)).catch(() => {})
  }

  const interrupt = () => {
    const reason = window.prompt('Причина перехвата (обязательно)')
    if (!reason?.trim()) return
    void api.interrupt(code, reason.trim())
      .then(() => toast(`Прогон прерван: агент будет остановлен на тике демона`, 'ok'))
      .catch((err: Error) => toast(err.message, 'bad'))
  }

  return (
    <div className="rl-panel">
      <div className="rl-runs">
        {runs.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Прогонов ещё не было — задача ждёт своей очереди или исполняется человеком.</div>}
        {runs.map((r) => (
          <button key={r.id} className={`rl-run ${viewRun === r.id ? 'sel' : ''}`}
            onClick={() => { if (!r.running) openHistory(r.id); else setNudge((n) => n + 1) }}
            title={r.running ? 'Показать живой лог этого прогона' : 'Показать лог прогона'}>
            <span className="num">#{r.attempt}</span>
            <span>{r.agent}</span>
            {r.running
              ? <span className="mini-chip mc-accent">{r.stale ? 'пульс потерян' : `работает · пульс ${hbAgo(r.heartbeatAt)}`}</span>
              : <span className={`mini-chip ${r.outcome === 'success' ? 'mc-green' : 'mc-red'}`}>{r.outcome ?? '—'}</span>}
            {r.tokens
              ? <span className="mini-chip" title={`${r.input} вход + ${r.output} ответ + ${r.cache} кэш`}>{fmtTokens(r.tokens)}</span>
              : null}
            <span className="muted" style={{ fontSize: 11 }}>{new Date(r.startedAt).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
          </button>
        ))}
      </div>
      {active && (
        <div className="rl-live">
          <span className={`dot ${live ? 'pulse' : ''}`} style={{ background: live ? '#25935b' : '#c2601a' }} />
          {live ? 'живой поток' : 'поток недоступен — поллинг 2 с'}
          <span className="fill" />
          <button className="btn danger small" onClick={interrupt}>✕ Прервать</button>
        </div>
      )}
      <div className="rl-box" ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget
          pinBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}>
        {lines.length === 0 && viewRun && <div className="muted" style={{ fontSize: 12 }}>Лог пуст.</div>}
        {lines.map((l) => <Line key={l.seq} l={l} />)}
      </div>
    </div>
  )
}

function hbAgo(hb: string | null): string {
  if (!hb) return '?'
  return `${Math.max(0, Math.round((Date.now() - new Date(hb).getTime()) / 1000))} с назад`
}
