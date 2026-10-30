// Вкладка «Очередь автомата» — q-row: в работе / ожидают / заблокированы.
// Перенесено из монолита Settings.tsx разметка 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'

export function Queue() {
  const [snap, setSnap] = useState<Awaited<ReturnType<typeof api.queue>> | null>(null)
  useEffect(() => { void api.queue().then(setSnap) }, [])
  if (!snap) return <div className="empty"><b>Загрузка…</b></div>
  return (
    <div className="set-body">
      <div className="q-sec">В работе у агентов</div>
      {snap.working.map((w) => (
        <div key={w.code} className="q-row" onClick={() => { window.location.hash = `#${w.code}` }}>
          <span className="code">{w.code}</span><span className="q-t">{w.agent}</span>
          <span className="muted">{w.minutes ?? 0} мин</span>
        </div>
      ))}
      <div className="q-sec">Ожидают</div>
      {snap.waiting.map((w) => (
        <div key={w.code} className="q-row" onClick={() => { window.location.hash = `#${w.code}` }}>
          <span className="code">{w.code}</span><span className="q-t">{w.status}</span>
          <span className="muted">попыток {w.attempts}</span>
        </div>
      ))}
      <div className="q-sec">Заблокированы</div>
      {snap.blocked.map((b) => (
        <div key={b.code} className="q-row" onClick={() => { window.location.hash = `#${b.code}` }}>
          <span className="code">{b.code}</span><span className="q-t">{b.reason}</span>
        </div>
      ))}
    </div>
  )
}
