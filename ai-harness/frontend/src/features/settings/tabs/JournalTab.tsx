// Вкладка «Журнал настроек» — jr-row: кто, что и какие поля поменял.
// Перенесено из монолита Settings.tsx разметка 1:1.

import { useEffect, useState } from 'react'

export function Journal() {
  const [rows, setRows] = useState<{ who: string; entity: string; summary: string; diff: { field: string; old: string; new: string }[]; at: string }[]>([])
  useEffect(() => { void fetch('/api/v1/settings-journal').then((r) => r.json()).then(setRows) }, [])
  return (
    <div className="set-body">
      {rows.map((r, i) => (
        <div key={i} className="jr-row">
          <time>{r.at.slice(0, 16).replace('T', ' ')}</time>
          <div className="jr-b">
            <b>{r.who}</b> · {r.summary}
            <div className="jr-diff">
              {(r.diff ?? []).map((d, j) => (
                <span key={j} className={j % 2 ? 'new' : 'old'}>{d.field}: {String(d.old ?? '—')} → {String(d.new ?? '—')}</span>
              ))}
            </div>
          </div>
        </div>
      ))}
      {rows.length === 0 && <div className="empty"><b>Журнал пуст</b>правки настроек появятся здесь</div>}
    </div>
  )
}
