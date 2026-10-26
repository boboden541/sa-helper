// Доска — DOM design_mockup/app.js:726-854. DnD на dnd-kit (pointer-based):
// карточка тянется с курсором, разрешённые колонки подсвечиваются (.cell.ok/.over),
// запрет решается при применении с человекочитаемым toast (ФТ-ah-16).

import { DndContext, PointerSensor, useSensor, useSensors,
  useDraggable, useDroppable,
  type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { useEffect, useRef, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import {
  ALIAS_LB, ALIAS_OF, esc, prioBadge, stChip, tagHtml, typeChip,
} from '../../shared/refs'
import { pushUndo } from '../../shared/undo'
import { toast } from '../../shared/toast'

interface Column { id: string; label: string; color: string; position: number }

const KEY_BY_LABEL: Record<string, string> = {
  'На рассмотрении': 'pending', 'Бэклог': 'backlog', 'К работе': 'todo', 'В работе': 'progress',
  'На ревью': 'review', 'На тестировании': 'testing', 'Готово': 'done',
  'Заблокировано': 'blocked', 'Отменено': 'canceled',
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', in_progress: '#3d63d2',
  review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
  done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
}

function cardHtml(t: TaskCard, merged: boolean): string {
  return `<article class="card ${t.statusKey === 'blocked' ? 'top' : ''}" draggable="false" data-code="${t.code}" style="--st:${STATUS_COLORS[t.statusKey] ?? '#8792a3'}">
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

const aliasKeyOf = (t: TaskCard) => ALIAS_OF[t.statusKey] ?? 'progress'

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

function Cell({ laneId, column, bucket, allowed, dragging, reload }: {
  laneId: string
  column: Column
  bucket: TaskCard[]
  allowed: boolean
  dragging: boolean
  reload: () => void
}) {
  const key = KEY_BY_LABEL[column.label] ?? ''
  const { setNodeRef, isOver } = useDroppable({ id: `${laneId}|${column.label}`, data: { label: column.label } })
  return (
    <div ref={setNodeRef} className={`cell ${allowed && dragging ? 'ok' : ''} ${isOver && allowed && dragging ? 'over' : ''}`}
      style={{ ['--colc' as string]: bucket.length || dragging ? column.color : 'transparent' }}
      data-drop={column.label}>
      {bucket.map((t) => (
        <DraggableCard key={t.code} task={t} merged={key === 'review' || key === 'testing'}
          onOpen={() => { window.location.hash = `#${t.code}` }}
          onOpenPage={() => { window.location.hash = `#${t.code}/page` }} />
      ))}
    </div>
  )
}

export function Board({ tasks, reload }: { tasks: TaskCard[]; reload: () => void }) {
  const [columns, setColumns] = useState<Column[]>([])
  const [editMode, setEditMode] = useState(false)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [colMapFor, setColMapFor] = useState<string | null>(null)
  const [colMapAlias, setColMapAlias] = useState<Record<string, string>>({})
  const [allStatuses, setAllStatuses] = useState<{ type: string; typeLabel: string; statuses: { key: string; label: string; aliasColumnId: string }[] }[]>([])
  const [allowedKeys, setAllowedKeys] = useState<Record<string, boolean> | null>(null)
  const [dragCode, setDragCode] = useState<string | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  useEffect(reloadColumns, [])

  const stories = tasks.filter((t) => t.type === 'story')

  const onDragStart = (e: DragStartEvent) => {
    const code = String(e.active.id)
    setDragCode(code)
    void api.task(code).then((card) => {
      const ok: Record<string, boolean> = {}
      const bad: Record<string, string> = {}
      for (const to of card.gate?.allowed ?? []) ok[ALIAS_OF[to] ?? to] = true
      for (const d of card.gate?.denied ?? []) {
        const a = ALIAS_OF[d.to] ?? d.to
        if (!ok[a]) bad[a] = d.reason
      }
      setAllowedKeys(ok)
      const allow = Object.keys(ok).map((k) => ALIAS_LB[k] ?? k)
      const deny = Object.entries(bad).map(([k, r]) => `${ALIAS_LB[k] ?? k}: ${r}`)
      setHint(allow.length
        ? `Разрешено: ${allow.join(', ')}${deny.length ? ` · запреты: ${deny.join(' · ')}` : ''}`
        : deny.join(' · ') || null)
    }).catch(() => {})
  }

  const onDragEnd = (e: DragEndEvent) => {
    const code = String(e.active.id)
    const label = (e.over?.data.current as { label?: string } | undefined)?.label
    setAllowedKeys(null); setDragCode(null); setHint(null)
    if (!label) return
    void applyDrop(code, label, reload)
  }

  const cellsHtml = (laneId: string, items: TaskCard[]) => columns.map((col) => {
    const key = KEY_BY_LABEL[col.label] ?? ''
    const bucket = [...items.filter((t) => aliasKeyOf(t) === key)].sort((a, b) => {
      const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      const sa = (rank[a.priority] ?? 9) * 10 + (a.type === 'bug' ? 4 : 0)
      const sb = (rank[b.priority] ?? 9) * 10 + (b.type === 'bug' ? 4 : 0)
      return sa !== sb ? sb - sa : a.code.localeCompare(b.code)
    })
    const allowed = Boolean(allowedKeys?.[key])
    return (
      <Cell key={`${laneId}|${col.id}`} laneId={laneId} column={col} bucket={bucket}
        allowed={allowed} dragging={Boolean(dragCode)} reload={reload} />
    )
  })

  const colHeads = columns.map((col) => {
    const key = KEY_BY_LABEL[col.label] ?? ''
    const count = tasks.filter((t) => (aliasKeyOf(t) ?? '') === key).length
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
          <button className="colh-map" title="Какие статусы сводятся в колонку"
            onClick={(e) => {
              e.stopPropagation()
              setColMapFor((cur) => (cur === col.label ? null : col.label))
              if (col.label !== colMapFor) {
                void fetch('http://localhost:8088/api/v1/flows/all-statuses').then((r) => r.json()).then(setAllStatuses)
              }
            }}>статусы</button>
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

  const loose = tasks.filter((t) => t.type !== 'story' && !t.storyCode)

  return (
    <>
      {dragCode && hint && <div className="draghint">{hint}</div>}
      <section className="board-scroll" aria-label="Kanban-доска">
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
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
            {colMapFor && (
            <aside className="colmap-panel" aria-label="Статусы колонки">
              <div className="blk-h"><h3>Колонка «{colMapFor}»</h3><span className="fill" />
                <button className="icon-btn" onClick={() => setColMapFor(null)} style={{ width: 22, height: 22 }}>✕</button></div>
              <div className="muted" style={{ fontSize: 12 }}>Отметьте, какие статусы сводятся в эту колонку. Статус живёт в одной колонке.</div>
              {(() => {
              const col = columns.find((c) => c.label === colMapFor)
              if (!col) return null
              return allStatuses.map((t) => (
                <div key={t.type} className="cm-type">
                  <div className="q-sec">{t.typeLabel}</div>
                  <div className="cm-sts">
                    {t.statuses.map((s) => {
                      const mine = s.aliasColumnId && colMapAlias[col.label] === s.key
                      const other = s.aliasColumnId && !mine
                      return (
                        <button key={s.key} className={`cm-st ${mine ? 'mine' : ''}`}
                          onClick={async () => {
                            const newAlias = mine ? '' : col.id
                            await fetch(`/api/v1/flows/${t.type}/status-alias`, {
                              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ statusKey: s.key, aliasColumnId: newAlias }),
                            })
                            // обновить локальный маппинг
                            setColMapAlias((m) => { const n = { ...m }; if (newAlias) n[col.label] = s.key; else delete n[col.label]; return n })
                            reloadColumns(); reload()
                          }}>
                          <span className="st-dot" style={{ background: STATUS_COLORS[s.key] ?? '#8792a3' }} />
                          <span className="cm-l">{s.label}</span>
                          {mine && <span className="cm-check">✓</span>}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))
              })()}
            </aside>
          )}
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
    </>
  )

  function reloadColumns() {
    void api.aliasColumns().then((cols) =>
      setColumns([...cols].sort((a, b) => a.position - b.position)))
  }
}

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'задача'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'задачи'
  return 'задач'
}

async function applyDrop(code: string, columnLabel: string, reload: () => void) {
  const card = await api.task(code)
  const key = KEY_BY_LABEL[columnLabel]
  if (!key) return
  const candidate = card.gate?.allowed.find((to) => (ALIAS_OF[to] ?? to) === key)
  if (!candidate) {
    const denied = card.gate?.denied.find((x) => (ALIAS_OF[x.to] ?? x.to) === key)
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
