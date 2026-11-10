// Сворачиваемый раздел карточки: владеет хромой .blk + .blk-h — шеврон,
// заголовок, слот действий. Состояние — ПО ЗАДАЧЕ: localStorage
// 'task-ui:<код>' (карта id→open; решение владельца 10.11.2026 после
// инцидента «у задач пропало описание»: глобальная карта свёртывала
// раздел на ВСЕХ задачах сразу и выглядела как пропажа). Свёрнутое
// тело именно НЕ рендерится: блоки с useEffect (ПСИ, чеклисты) не должны
// гонять запросы невидимо.

import { useEffect, useState, type ReactNode } from 'react'

function loadSections(taskId: string): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(`task-ui:${taskId}`)
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {}
  } catch { return {} }
}

export function Collapsible({ id, taskId, title, right, badge, children }: {
  id: string
  taskId: string
  title: string
  right?: ReactNode
  badge?: ReactNode
  children: ReactNode
}) {
  const [open, setOpen] = useState(() => loadSections(taskId)[id] !== false)
  useEffect(() => { setOpen(loadSections(taskId)[id] !== false) }, [id, taskId])
  const toggle = () => {
    setOpen((v) => {
      const next = !v
      try {
        const key = `task-ui:${taskId}`
        const map = loadSections(taskId)
        map[id] = next
        localStorage.setItem(key, JSON.stringify(map))
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
