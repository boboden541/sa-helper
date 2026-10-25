// Доска: колонки из alias-колонок, DnD с предподсветкой разрешённых,
// пометка «в работе у агента» (СТ §5.2; эталон design_mockup/app.js:743-854).

import { DndContext, PointerSensor, useSensor, useSensors, useDraggable, useDroppable, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { pushUndo } from '../../shared/undo'

const ALIAS_ORDER = ['pending', 'backlog', 'todo', 'progress', 'review', 'testing', 'done', 'canceled', 'blocked']
const ALIAS_LABEL: Record<string, string> = {
  pending: 'На рассмотрении', backlog: 'Бэклог', todo: 'К работе', progress: 'В работе',
  review: 'На ревью', testing: 'На тестировании', done: 'Готово', canceled: 'Отменено', blocked: 'Заблокировано',
}

export function aliasOf(statusKey: string): string {
  if (statusKey.startsWith('review')) return 'review'
  if (statusKey.startsWith('qa_ready') || statusKey.startsWith('in_testing')) return 'testing'
  return { pending: 'pending', backlog: 'backlog', todo: 'todo', in_progress: 'progress',
    done: 'done', canceled: 'canceled', blocked: 'blocked' }[statusKey] ?? 'progress'
}

function DraggableCard({ task, onOpen }: { task: TaskCard; onOpen: (code: string) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: task.code })
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      className={`card prio-${task.priority} ${isDragging ? 'dragging' : ''}`}
      onClick={() => onOpen(task.code)}>
      <div className="card-top">
        <span className="code">{task.code}</span>
        <span className={`prio prio-${task.priority}`} title={task.priority}>
          {task.priority === 'critical' ? '⏫' : task.priority === 'high' ? '⏶' : task.priority === 'low' ? '⏷' : '='}
        </span>
      </div>
      <div className="card-title">{task.title}</div>
      <div className="card-tags">{(task.tags ?? []).map((t) => `#${t}`).join(' ')}</div>
      {task.agent && <div className="card-agent">⟳ в работе у {task.agent.name}</div>}
    </div>
  )
}

export function Board({ tasks, reload }: { tasks: TaskCard[]; reload: () => void }) {
  const [activeCode, setActiveCode] = useState<string | null>(null)
  const [denials, setDenials] = useState<Record<string, string>>({})
  const [hint, setHint] = useState<string | null>(null)
  const sensors = useSensors(useSensor(PointerSensor))

  useEffect(() => {
    if (!activeCode) { setDenials({}); setHint(null); return }
    void api.task(activeCode).then((card) => {
      const d: Record<string, string> = {}
      card.gate?.denied.forEach((x) => { d[aliasOf(x.to)] = x.reason })
      setDenials(d)
      const allowed = card.gate?.allowed.map(aliasOf) ?? []
      const reasons = card.gate?.denied.map((x) => `→ ${ALIAS_LABEL[aliasOf(x.to)]}: ${x.reason}`) ?? []
      setHint(allowed.length ? `Разрешено: ${allowed.map((a) => ALIAS_LABEL[a]).join(', ')}` : reasons.join(' · ') || null)
    }).catch(() => setDenials({}))
  }, [activeCode])

  const onDragStart = (e: DragStartEvent) => setActiveCode(String(e.active.id))
  const onDragEnd = (e: DragEndEvent) => {
    const code = String(e.active.id)
    const alias = String(e.over?.id ?? '')
    setActiveCode(null)
    if (!alias) return
    const target = (tasks.find((t) => t.code === code)?.statusKey ?? '')
    void resolveAliasTransition(code, alias, target, reload)
  }

  return (
    <div className="board-wrap">
      {hint && <div className="draghint">{hint}</div>}
      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
        <div className="board">
          {ALIAS_ORDER.map((alias) => (
            <DndWrapper key={alias} alias={alias} tasks={tasks.filter((t) => aliasOf(t.statusKey) === alias)}
              denials={denials} />
          ))}
        </div>
      </DndContext>
    </div>
  )
}

function DndWrapper({ alias, tasks, denials }: { alias: string; tasks: TaskCard[]; denials: Record<string, string> }) {
  const { setNodeRef, isOver } = useDroppable({ id: alias })
  const denied = alias in denials
  return (
    <div ref={setNodeRef} className={`col ${isOver ? 'over' : ''} ${denied ? 'denied' : ''}`} data-alias={alias}>
      <div className="col-head">{ALIAS_LABEL[alias] ?? alias} <span className="count">{tasks.length}</span></div>
      {tasks.map((t) => <DraggableCard key={t.code} task={t} onOpen={(code) => { window.location.hash = `#${code}` }} />)}
      {denied && <div className="col-denied" title={denials[alias]}>✕ {denials[alias]}</div>}
    </div>
  )
}

async function resolveAliasTransition(code: string, alias: string, currentStatus: string, reload: () => void) {
  // запрашиваем точный статус-таргет у карточки: первый разрешённый таргет в этой alias-колонке
  const card = await api.task(code)
  const candidate = card.gate?.allowed.find((to) => aliasOf(to) === alias)
  if (!candidate) {
    const denied = card.gate?.denied.find((x) => aliasOf(x.to) === alias)
    alert(`Переход запрещён: ${denied?.reason ?? 'нет разрешённого ребра в эту колонку'}`)
    return
  }
  const result = await api.transition(code, candidate)
  if (!result.applied) alert(`Переход не применён: ${result.reason}`)
  else {
    const prevAlias = aliasOf(currentStatus)
    pushUndo({
      label: `Перевод ${code}`,
      undo: async () => { await api.transition(code, candidateBack(prevAlias, card.statusKey)) ; reload() },
    })
  }
  reload()
}

function candidateBack(alias: string, statusKey: string): string {
  return statusKey // упрощение: возврат на прежний статус-ключ (форс при необходимости)
}

export { resolveAliasTransition }
