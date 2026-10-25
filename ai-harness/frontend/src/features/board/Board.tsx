// Доска: колонки из alias-колонок, полосы историй с дочерними по колонкам,
// DnD с предподсветкой разрешённых, режим правки доски (СТ §5.2, ФТ-ah-14/66;
// эталон design_mockup/app.js:743-854, 1783-1844).

import { DndContext, PointerSensor, useSensor, useSensors, useDraggable, useDroppable, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { pushUndo } from '../../shared/undo'

const ALIAS_LABEL: Record<string, string> = {
  pending: 'На рассмотрении', backlog: 'Бэклог', todo: 'К работе', progress: 'В работе',
  review: 'На ревью', testing: 'На тестировании', done: 'Готово', canceled: 'Отменено', blocked: 'Заблокировано',
}
const LABEL_TO_KEY: Record<string, string> = Object.fromEntries(
  Object.entries(ALIAS_LABEL).map(([k, v]) => [v, k]))

interface Column { id: string; label: string; color: string; position: number }

export function aliasOf(statusKey: string): string {
  if (statusKey.startsWith('review')) return 'review'
  if (statusKey.startsWith('qa_ready') || statusKey.startsWith('in_testing')) return 'testing'
  return { pending: 'pending', backlog: 'backlog', todo: 'todo', in_progress: 'progress',
    done: 'done', canceled: 'canceled', blocked: 'blocked' }[statusKey] ?? 'progress'
}

function DraggableCard({ task }: { task: TaskCard }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: task.code })
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      className={`card ${isDragging ? 'dragging' : ''}`}
      onClick={() => { window.location.hash = `#${task.code}` }}>
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

function ColumnView({ column, tasks, denied, editMode, onEdit, onDelete }: {
  column: Column
  tasks: TaskCard[]
  denied?: string
  editMode: boolean
  onEdit: (patch: { label?: string; color?: string; position?: number }) => void
  onDelete: () => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: column.label })
  return (
    <div ref={setNodeRef} className={`col ${isOver ? 'over' : ''} ${denied ? 'denied' : ''}`}>
      {editMode ? (
        <div className="edit-head">
          <input type="color" value={column.color} title="Цвет колонки"
            onChange={(e) => onEdit({ color: e.target.value })} />
          <input type="text" defaultValue={column.label} title="Имя колонки"
            onBlur={(e) => e.target.value !== column.label && onEdit({ label: e.target.value })} />
          <button title="Сдвинуть влево" onClick={() => onEdit({ position: column.position - 1 })}>←</button>
          <button title="Сдвинуть вправо" onClick={() => onEdit({ position: column.position + 1 })}>→</button>
          <button title="Удалить колонку" onClick={onDelete}>✕</button>
        </div>
      ) : (
        <div className="col-head" style={{ borderBottom: `2px solid ${column.color}` }}>
          {column.label} <span className="count">{tasks.length}</span>
        </div>
      )}
      {tasks.map((t) => <DraggableCard key={t.code} task={t} />)}
      {denied && <div className="col-denied" title={denied}>✕ {denied}</div>}
    </div>
  )
}

export function Board({ tasks, reload }: { tasks: TaskCard[]; reload: () => void }) {
  const [activeCode, setActiveCode] = useState<string | null>(null)
  const [denials, setDenials] = useState<Record<string, string>>({})
  const [hint, setHint] = useState<string | null>(null)
  const [columns, setColumns] = useState<Column[]>([])
  const [editMode, setEditMode] = useState(false)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const sensors = useSensors(useSensor(PointerSensor))

  const reloadColumns = () => { void api.aliasColumns().then((cols) => setColumns(cols.sort((a, b) => a.position - b.position))) }
  useEffect(reloadColumns, [])
  useEffect(reloadColumns, [editMode])

  useEffect(() => {
    if (!activeCode) { setDenials({}); setHint(null); return }
    void api.task(activeCode).then((card) => {
      const d: Record<string, string> = {}
      card.gate?.denied.forEach((x) => { d[aliasOf(x.to)] = x.reason })
      setDenials(d)
      const allowed = card.gate?.allowed.map(aliasOf) ?? []
      const reasons = card.gate?.denied.map((x) => `→ ${ALIAS_LABEL[aliasOf(x.to)]}: ${x.reason}`) ?? []
      setHint(allowed.length
        ? `Разрешено: ${allowed.map((a) => ALIAS_LABEL[a]).join(', ')}. Запрещено: ${Object.values(d).length}`
        : reasons.join(' · ') || null)
    }).catch(() => setDenials({}))
  }, [activeCode])

  const onDragStart = (e: DragStartEvent) => setActiveCode(String(e.active.id))
  const onDragEnd = (e: DragEndEvent) => {
    const code = String(e.active.id)
    const label = String(e.over?.id ?? '')
    setActiveCode(null)
    if (!label) return
    void applyDrop(code, label, reload)
  }

  const stories = tasks.filter((t) => t.type === 'story')
  const loose = tasks.filter((t) => t.type !== 'story' && !t.storyCode)
  const childrenOf = (code: string) => tasks.filter((t) => t.storyCode === code)

  const renderColumns = (items: TaskCard[]) => columns.map((column) => {
    const key = LABEL_TO_KEY[column.label] ?? ''
    const bucket = items.filter((t) => aliasOf(t.statusKey) === key)
    return (
      <ColumnView key={column.id} column={column} tasks={bucket} editMode={editMode}
        denied={denials[key]}
        onEdit={(patch) => {
          void api.updateColumn(column.id, patch).then(() => {
            reloadColumns(); reload()
          })
        }}
        onDelete={() => {
          void api.deleteColumn(column.id)
            .then(() => { reloadColumns(); reload() })
            .catch((err: Error) => alert(err.message))
        }} />
    )
  })

  const addColumn = () => {
    const label = window.prompt('Название новой колонки')
    if (!label?.trim()) return
    void api.createColumn({ label: label.trim() }).then(() => reloadColumns())
  }

  return (
    <div className="board-wrap">
      <div className="toolbar">
        <button className={`btn ${editMode ? 'primary' : ''}`}
          onClick={() => setEditMode(!editMode)}>
          {editMode ? 'Готово' : '✎ Правка доски'}
        </button>
        {editMode && <button className="btn" onClick={addColumn}>＋ колонка</button>}
        {hint && <div className="draghint">{hint}</div>}
      </div>
      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
        {/* полосы историй: на всю доску, дочерние — по колонкам под полосой (ФТ-ah-14) */}
        {stories.map((story) => (
          <section key={story.code} className="story-section">
            <div className="story-band" onClick={() => setCollapsed((c) => ({ ...c, [story.code]: !c[story.code] }))}>
              <span className="code">{story.code}</span>
              <b>{story.title}</b>
              <span className="chip">{story.statusKey}</span>
              <span className="count">{childrenOf(story.code).length} дочерних</span>
              <span>{collapsed[story.code] ? '▸' : '▾'}</span>
            </div>
            {!collapsed[story.code] && (
              <div className="board">{renderColumns(childrenOf(story.code))}</div>
            )}
          </section>
        ))}
        <div className="board">{renderColumns(loose)}</div>
      </DndContext>
    </div>
  )
}

async function applyDrop(code: string, columnLabel: string, reload: () => void) {
  const card = await api.task(code)
  const key = LABEL_TO_KEY[columnLabel]
  if (!key) return
  const candidate = card.gate?.allowed.find((to) => aliasOf(to) === key)
  if (!candidate) {
    const denied = card.gate?.denied.find((x) => aliasOf(x.to) === key)
    alert(`Переход запрещён: ${denied?.reason ?? 'нет разрешённого ребра в эту колонку'}`)
    return
  }
  const result = await api.transition(code, candidate)
  if (!result.applied) alert(`Переход не применён: ${result.reason}`)
  else {
    pushUndo({
      label: `Перевод ${code} в ${columnLabel}`,
      undo: async () => {
        await api.force(code, card.statusKey, 'отмена правки (undo)').catch(() => {})
        reload()
      },
    })
  }
  reload()
}
