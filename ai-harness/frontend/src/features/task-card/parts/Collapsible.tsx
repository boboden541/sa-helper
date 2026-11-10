// Сворачиваемый раздел карточки: владеет хромой .blk + .blk-h — шеврон,
// заголовок, слот действий. Состояние секций — localStorage 'task-ui-sections'
// (карта id→open), переживает закрытие карточки и перезагрузку (паттерн Eve).
// Тело при свёртывании именно НЕ рендерится: блоки с useEffect (ПСИ, чеклисты)
// не должны гонять запросы невидимо.

import { useEffect, useState, type ReactNode } from 'react'

const KEY = 'task-ui-sections'

function loadSections(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {}
  } catch { return {} }
}

export function Collapsible({ id, title, right, badge, children }: {
  id: string
  title: string
  right?: ReactNode
  badge?: ReactNode
  children: ReactNode
}) {
  const [open, setOpen] = useState(() => loadSections()[id] !== false)
  useEffect(() => { setOpen(loadSections()[id] !== false) }, [id])
  const toggle = () => {
    setOpen((v) => {
      const next = !v
      try {
        const map = loadSections()
        map[id] = next
        localStorage.setItem(KEY, JSON.stringify(map))
      } catch { /* приватный режим */ }
      return next
    })
  }
  return (
    <div className="blk coll">
      <div className="blk-h">
        <button className="blk-chev" aria-label={open ? 'Свернуть раздел' : 'Развернуть раздел'}
          aria-expanded={open} onClick={toggle}>{open ? '▾' : '▸'}</button>
        <h3 onClick={toggle} title={open ? 'Свернуть' : 'Развернуть'}>{title}</h3>
        {badge}
        <span className="fill" />
        {right}
      </div>
      {open && children}
    </div>
  )
}
