// Доска — DOM design_mockup/app.js:726-854. DnD на dnd-kit (pointer-based):
// карточка тянется с курсором, разрешённые колонки подсвечиваются (.cell.ok/.over),
// запрет решается при применении с человекочитаемым toast (ФТ-ah-16).
// Раскладка по колонкам — по реестру «тип+статус → alias-колонка» (/all-statuses),
// а не по жёсткому словарю меток: правка доски и colmap не должны прятать задачи.

import { DndContext, PointerSensor, useSensor, useSensors,
  useDraggable, useDroppable,
  type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import {
  ALIAS_OF, esc, prioBadge, stChip, tagHtml, typeChip,
} from '../../shared/refs'
import { pushUndo } from '../../shared/undo'
import { toast } from '../../shared/toast'
import { ColmapPanel } from './ColmapPanel'

interface Column { id: string; label: string; color: string; position: number }

// Фолбэк на дефолтные метки — только пока реестр /all-statuses не догрузился.
const KEY_BY_LABEL: Record<string, string> = {
  'На рассмотрении': 'pending', 'Бэклог': 'backlog', 'К работе': 'todo', 'В работе': 'progress',
  'На ревью': 'review', 'На тестировании': 'testing', 'Готово': 'done',
  'Заблокировано': 'blocked', 'Отменено': 'canceled',
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', progress: '#3d63d2', in_progress: '#3d63d2',
  review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
  done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
}

function cardHtml(t: TaskCard, merged: boolean): string {
  return `<article class="card ${t.statusKey === 'blocked' ? 'top' : ''}" style="--st:${STATUS_COLORS[t.statusKey] ?? '#8792a3'}">
    <div class="card-top">
      <span class="code" data-open-page="${t.code}">${t.code}</span>
      ${typeChip(t.type)}
      <span class="sp"></span>
      ${merged ? stChip(t.statusKey) : ''}
      ${prioBadge(t.priority)}
    </div>
    <div class="card-title">${esc(t.title)}</div>
    <div class="card-tags">${(t.tags ?? []).map(tagHtml).join('')}</div>
    ${t.agent ? `<div class="agent"><span class="dot pulse" style="background:#7d4fd1"></span>${esc(t.agent.name)}</div>` : ''}
    ${t.statusKey === 'blocked' ? `<div class="card-sub">✕ Требуется человек: ${esc(t.blockedReason ?? '')}</div>` : ''}
  </article>`
}

function DraggableCard({ task, merged, onOpen, onOpenPage }: {
  task: TaskCard
  merged: boolean
  onOpen: () => void
  onOpenPage: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.code })
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 40 }
    : undefined
  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes}
      className={isDragging ? 'card-dragging-src' : ''}>
      <div dangerouslySetInnerHTML={{ __html: cardHtml(task, merged) }}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest('[data-open-page]')) onOpenPage()
          else if ((e.target as HTMLElement).closest('.card')) onOpen()
        }} />
    </div>
  )
}

function Cell({ laneId, column, bucket, allowed, dragging }: {
  laneId: string
  column: Column
  bucket: TaskCard[]
  allowed: boolean
  dragging: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `${laneId}|${column.id}`, data: { colId: column.id, label: column.label } })
  return (
    <div ref={setNodeRef} className={`cell ${allowed && dragging ? 'ok' : ''} ${isOver && allowed && dragging ? 'over' : ''}`}
      style={{ ['--colc' as string]: bucket.length || dragging ? column.color : 'transparent' }}
      data-drop={column.label}>
      {bucket.map((t) => (
        <DraggableCard key={t.code} task={t} merged={t.statusKey === 'review_ready' || t.statusKey === 'in_review' || t.statusKey === 'qa_ready' || t.statusKey === 'in_testing'}
          onOpen={() => { window.location.hash = `#${t.code}` }}
          onOpenPage={() => { window.location.hash = `#${t.code}/page` }} />
      ))}
    </div>
  )
}

export function Board({ tasks, reload, boardEdit }: { tasks: TaskCard[]; reload: () => void; boardEdit: boolean }) {
  const [columns, setColumns] = useState<Column[]>([])
  const editMode = boardEdit
  const [colMapFor, setColMapFor] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [allowedCols, setAllowedCols] = useState<Record<string, boolean> | null>(null)
  const [dragCode, setDragCode] = useState<string | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [statusCol, setStatusCol] = useState<Record<string, string>>({})
  const [terminalKeys, setTerminalKeys] = useState<Record<string, boolean>>({})
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  useEffect(reloadColumns, [])

  // «тип|статус» → alias-колонка; статус без колонки на доске не виден (§14).
  const colIdOfStatus = (type: string, statusKey: string): string => {
    if (Object.keys(statusCol).length > 0) return statusCol[`${type}|${statusKey}`] ?? ''
    const alias = ALIAS_OF[statusKey] ?? statusKey
    return columns.find((c) => (KEY_BY_LABEL[c.label] ?? '') === alias)?.id ?? ''
  }

  // Завершённое на доске не показывается: «финиш» = терминальный статус
  // модели задачи (галочка «терм.» в редакторе flow). Список показывает всё.
  const isDone = (t: TaskCard): boolean => Boolean(terminalKeys[`${t.type}|${t.statusKey}`])

  const stories = tasks.filter((t) => t.type === 'story' && !isDone(t))

  const onDragStart = (e: DragStartEvent) => {
    const code = String(e.active.id)
    document.body.classList.add('is-dragging')
    setDragCode(code)
    void api.task(code).then((card) => {
      const ok: Record<string, boolean> = {}
      const bad: Record<string, string> = {}
      for (const to of card.gate?.allowed ?? []) {
        const cid = colIdOfStatus(card.type, to)
        if (cid) ok[cid] = true
      }
      for (const d of card.gate?.denied ?? []) {
        const cid = colIdOfStatus(card.type, d.to)
        if (cid && !ok[cid]) bad[cid] = d.reason
      }
      setAllowedCols(ok)
      const lb = (cid: string) => columns.find((c) => c.id === cid)?.label ?? cid
      const allow = Object.keys(ok).map(lb)
      const deny = Object.entries(bad).map(([cid, r]) => `${lb(cid)}: ${r}`)
      setHint(allow.length
        ? `Разрешено: ${allow.join(', ')}${deny.length ? ` · запреты: ${deny.join(' · ')}` : ''}`
        : deny.join(' · ') || null)
    }).catch(() => {})
  }

  const onDragEnd = (e: DragEndEvent) => {
    const code = String(e.active.id)
    const d = e.over?.data.current as { colId?: string; label?: string } | undefined
    document.body.classList.remove('is-dragging')
    setAllowedCols(null); setDragCode(null); setHint(null)
    if (!d?.colId) return
    void applyDrop(code, d.colId, d.label ?? '', colIdOfStatus, reload)
  }

  const onDragCancel = () => {
    document.body.classList.remove('is-dragging')
    setAllowedCols(null); setDragCode(null); setHint(null)
  }

  const cellsHtml = (laneId: string, items: TaskCard[]) => columns.map((col) => {
    const bucket = [...items.filter((t) => colIdOfStatus(t.type, t.statusKey) === col.id && !isDone(t))].sort((a, b) => {
      const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      const sa = (rank[a.priority] ?? 9) * 10 + (a.type === 'bug' ? 4 : 0)
      const sb = (rank[b.priority] ?? 9) * 10 + (b.type === 'bug' ? 4 : 0)
      return sa !== sb ? sb - sa : a.code.localeCompare(b.code)
    })
    const allowed = Boolean(allowedCols?.[col.id])
    return (
      <Cell key={`${laneId}|${col.id}`} laneId={laneId} column={col} bucket={bucket}
        allowed={allowed} dragging={Boolean(dragCode)} />
    )
  })

  const colHeads = columns.map((col) => {
    const count = tasks.filter((t) => !isDone(t) && colIdOfStatus(t.type, t.statusKey) === col.id).length
    if (editMode) {
      return (
        <div key={col.id} className="col-head edit" style={{ ['--st' as string]: col.color }}>
          <button className="cdot clickable" title="Цвет колонки"
            onClick={(e) => {
              const btn = e.currentTarget
              const pop = document.createElement('div')
              pop.className = 'palette-pop'
              ;['#c07d1e', '#8792a3', '#1f8fb5', '#3d63d2', '#7d4fd1', '#c2601a', '#25935b', '#cf4436', '#5a6472'].forEach((c) => {
                const b = document.createElement('button')
                b.style.background = c
                b.onclick = () => {
                  void api.updateColumn(col.id, { color: c }).then(reloadColumns)
                  pop.remove()
                }
                pop.appendChild(b)
              })
              document.body.appendChild(pop)
              const r = btn.getBoundingClientRect()
              pop.style.left = `${r.left}px`
              pop.style.top = `${r.bottom + 6}px`
              const close = (ev: MouseEvent) => {
                if (!pop.contains(ev.target as Node)) { pop.remove(); document.removeEventListener('mousedown', close) }
              }
              setTimeout(() => document.addEventListener('mousedown', close))
            }}>
            <span style={{ background: col.color, width: 8, height: 8, borderRadius: 3, display: 'block' }} />
          </button>
          <input className="colh-name" defaultValue={col.label}
            onBlur={(e) => e.target.value !== col.label &&
              void api.updateColumn(col.id, { label: e.target.value }).then(reloadColumns)} />
          <span className="colh-key">{col.position}</span>
          <button className="colh-map" title="Assign statuses"
            onClick={() => setColMapFor(col.label)}>статусы</button>
          <button className="colh-x" title="Удалить колонку" onClick={() => {
            void api.deleteColumn(col.id)
              .then(() => { reloadColumns(); reload() })
              .catch((err: Error) => toast(err.message, 'bad'))
          }}>✕</button>
        </div>
      )
    }
    return (
      <div key={col.id} className="col-head" style={{ ['--st' as string]: col.color }}>
        <span className="cdot" /><b>{col.label}</b>
        <span className="n num">{count}</span>
      </div>
    )
  })

  const addColumnGhost = editMode ? (
    <div className="col-head ghost" onClick={() => {
      const label = window.prompt('Название новой колонки')
      if (label?.trim()) void api.createColumn({ label: label.trim() }).then(reloadColumns)
    }}>＋ колонка</div>
  ) : null

  const storyBand = (story: TaskCard, closedKids: number, kidCount: number) => (
    <div className="lane-band clickable" title="История движется автоматически по правилам M1–M6"
      style={{ ['--st' as string]: STATUS_COLORS[story.statusKey] ?? '#8792a3' }}
      onClick={() => { window.location.hash = `#${story.code}` }}>
      <button className="chev" aria-label={collapsed[story.code] ? 'Развернуть историю' : 'Свернуть историю'}
        onClick={(e) => { e.stopPropagation(); setCollapsed((c) => ({ ...c, [story.code]: !c[story.code] })) }}>
        <svg width="12" height="12" viewBox="0 0 12 12" style={{ transform: collapsed[story.code] ? 'rotate(-90deg)' : 'none' }}><path d="M2.5 4l3.5 4 3.5-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </button>
      <span className="code">{story.code}</span>
      <span className="t">{story.title}</span>
      <span dangerouslySetInnerHTML={{ __html: stChip(story.statusKey) }} />
      <span className="kidscnt num">{closedKids}/{kidCount} {plural(kidCount)}</span>
      <span className="fill" />
      <span dangerouslySetInnerHTML={{ __html: prioBadge(story.priority) }} />
    </div>
  )

  // Задача без истории ИЛИ с историей, которой нет в выдаче (в т.ч. завершённой),
  // — в полосу «Без истории». Завершённые задачи на доске не показываются.
  const loose = tasks.filter((t) => t.type !== 'story' && !isDone(t) &&
    (!t.storyCode || !stories.some((s) => s.code === t.storyCode)))

  return (
    <>
      {dragCode && hint && <div className="draghint">{hint}</div>}
      <section className="board-scroll" aria-label="Kanban-доска">
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={onDragCancel}>
          <div className={`board-grid ${editMode ? 'editing' : ''}`}>
            {colHeads}
            {addColumnGhost}
            {stories.map((story) => {
              const kids = tasks.filter((t) => t.storyCode === story.code)
              const closedKids = kids.filter((k) => ['done', 'canceled'].includes(k.statusKey)).length
              return (
                <div key={story.code} className="lane">
                  {storyBand(story, closedKids, kids.length)}
                  {!collapsed[story.code] && <div className="lane-cells">{cellsHtml(story.code, kids)}</div>}
                </div>
              )
            })}
            {loose.length > 0 && (
              <div className="lane">
                <div className="lane-band" style={{ ['--st' as string]: '#8792a3' }}>
                  <span className="chev" style={{ visibility: 'hidden' }} />
                  <span className="t" style={{ color: 'var(--text3)' }}>Без истории</span>
                  <span className="kidscnt num">{loose.length} {plural(loose.length)}</span>
                  <span className="fill" />
                </div>
                <div className="lane-cells">{cellsHtml('loose', loose)}</div>
              </div>
            )}
          </div>
        </DndContext>
      </section>
      {colMapFor && (
        <ColmapPanel columnLabel={colMapFor} columns={columns}
          onClose={() => setColMapFor(null)}
          onAssigned={() => { reloadColumns(); reload() }} />
      )}
    </>
  )

  function reloadColumns() {
    void api.aliasColumns().then((cols) =>
      setColumns([...cols].sort((a, b) => a.position - b.position)))
    void fetch('/api/v1/all-statuses').then((r) => r.json()).then((d) => {
      const m: Record<string, string> = {}
      const term: Record<string, boolean> = {}
      for (const t of (Array.isArray(d) ? d : [])) {
        for (const s of (t.statuses ?? [])) {
          m[`${t.type}|${s.key}`] = s.aliasColumnId ?? ''
          term[`${t.type}|${s.key}`] = Boolean(s.terminal)
        }
      }
      setStatusCol(m)
      setTerminalKeys(term)
    }).catch(() => {})
  }
}

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'задача'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'задачи'
  return 'задач'
}

async function applyDrop(code: string, colId: string, columnLabel: string,
  colOf: (type: string, statusKey: string) => string, reload: () => void) {
  const card = await api.task(code)
  const candidate = card.gate?.allowed.find((to) => colOf(card.type, to) === colId)
  if (!candidate) {
    const denied = card.gate?.denied.find((x) => colOf(card.type, x.to) === colId)
    toast(`Переход запрещён: ${denied?.reason ?? 'нет ребра в эту колонку'}`, 'bad')
    return
  }
  const result = await api.transition(code, candidate)
  if (!result.applied) toast(`Переход не применён: ${result.reason}`, 'bad')
  else {
    toast(`<b>${code}</b>: перевод в «${columnLabel}»`, 'ok')
    pushUndo({
      label: `Перевод ${code}`,
      undo: async () => {
        await api.force(code, card.statusKey, 'отмена правки (undo)').catch(() => {})
        reload()
      },
    })
  }
  reload()
}
