// Colmap-панель: назначение статусов колонке (ФТ-ah-67, §14 макета)

import { useEffect, useState } from 'react'
import { STATUS_COLORS } from './dndColors'

interface Column { id: string; label: string; color: string; position: number }

export function ColmapPanel({ columnLabel, columns, onClose, onAssigned }: {
  columnLabel: string
  columns: Column[]
  onClose: () => void
  onAssigned: () => void
}) {
  const [allStatuses, setAllStatuses] = useState<{ type: string; typeLabel: string; statuses: { key: string; label: string; aliasColumnId: string }[] }[]>([])
  const col = columns.find((c) => c.label === columnLabel)
  const colId = col?.id ?? ''

  useEffect(() => {
    void fetch('/api/v1/all-statuses').then((r) => r.json()).then((d) => setAllStatuses(Array.isArray(d) ? d : [])).catch(() => setAllStatuses([]))
  }, [])

  const assign = async (type: string, statusKey: string) => {
    const t = allStatuses.find((x) => x.type === type)
    const st = t?.statuses.find((x) => x.key === statusKey)
    const newAlias = st?.aliasColumnId === colId ? '' : colId
    await fetch(`/api/v1/flows/${type}/status-alias`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ statusKey, aliasColumnId: newAlias }),
    })
    onAssigned()
    void fetch('/api/v1/all-statuses').then((r) => r.json()).then((d) => setAllStatuses(Array.isArray(d) ? d : [])).catch(() => setAllStatuses([]))
  }

  return (
    <aside className="colmap-panel" aria-label="Статусы колонки">
      <div className="blk-h"><h3>Колонка «{columnLabel}»</h3><span className="fill" />
        <button className="icon-btn" onClick={onClose} style={{ width: 22, height: 22 }}>✕</button></div>
      <div className="muted" style={{ fontSize: 12 }}>
        Отметьте, какие статусы сводятся в эту колонку. Статус живёт ровно в одной колонке.</div>
      {allStatuses.map((t) => (
        <div key={t.type} className="cm-type">
          <div className="q-sec">{t.typeLabel}</div>
          <div className="cm-sts">
            {t.statuses.map((s) => {
              const mine = s.aliasColumnId === colId
              const other = !mine && s.aliasColumnId
              const otherColId = other ? s.aliasColumnId : ''
              const otherCol = columns.find((c) => c.id === otherColId)
              return (
                <button key={s.key} className={`cm-st ${mine ? 'mine' : ''}`}
                  onClick={() => void assign(t.type, s.key)}>
                  <span className="st-dot" style={{ background: STATUS_COLORS[s.key] ?? '#8792a3' }} />
                  <span className="cm-l">{s.label}</span>
                  {otherCol && otherCol.label !== columnLabel && <span className="mini-chip">→ {otherCol.label}</span>}
                  {mine && <span className="cm-check">✓</span>}
                </button>
              )
            })}
          </div>
        </div>
      ))}
      <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
        Статус без колонки не виден на доске — валидация напомнит при публикации.</div>
    </aside>
  )
}
