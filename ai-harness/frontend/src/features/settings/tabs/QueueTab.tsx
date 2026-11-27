// Вкладка «Очередь автомата» — q-row: в работе / ожидают / заблокированы.
// Перенесено из монолита Settings.tsx разметка 1:1.
// 26.11.2026: + окно хранения сырых строк живого лога (runlog.retention_days).

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { toast } from '../../../shared/toast'

export function Queue() {
  const [snap, setSnap] = useState<Awaited<ReturnType<typeof api.queue>> | null>(null)
  const [failed, setFailed] = useState(false)
  const [retention, setRetention] = useState<number | null>(null)
  useEffect(() => {
    void api.queue().then((d) => { setFailed(false); setSnap(d) }).catch(() => setFailed(true))
    void api.runlogRetention().then((r) => setRetention(r.days)).catch(() => {})
  }, [])
  const saveRetention = () => {
    const days = retention ?? 0
    if (!Number.isInteger(days) || days < 1) {
      toast('Окно хранения — целое число дней, не меньше 1', 'bad')
      return
    }
    void api.runlogRetentionSet(days)
      .then(() => toast(`Сырые строки логов хранятся ${days} дн.`, 'ok'))
      .catch((err: Error) => toast(err.message, 'bad'))
  }
  if (failed) return <div className="empty"><b>Очередь недоступна — обновите страницу</b></div>
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
      <div className="q-sec">Хранение логов прогонов</div>
      <div className="q-row" style={{ cursor: 'default', alignItems: 'end' }}>
        <div className="f-field" style={{ margin: 0, flex: 1 }}>
          <label>Сырые строки живого лога хранятся (дней)</label>
          <input type="number" min={1} value={retention ?? ''} style={{ width: 120 }}
            onChange={(e) => setRetention(e.target.value === '' ? null : Number(e.target.value))} />
        </div>
        <button className="btn small" onClick={saveRetention} disabled={retention === null}>Сохранить</button>
      </div>
      <div className="muted" style={{ fontSize: 12, padding: '0 12px' }}>
        Прогоны старше окна показывают «лог удалён хранением»; итоги прогонов остаются в хронике.
      </div>
    </div>
  )
}
