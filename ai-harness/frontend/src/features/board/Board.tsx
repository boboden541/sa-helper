// Доска — DOM design_mockup/app.js:726-854. DnD императивный, как в макете:
// никаких setState во время перетаскивания (перерисовка уничтожает drag-узел),
// подсветка разрешённых колонок — классами .cell.ok/.over напрямую в DOM,
// причины запретов — в .draghint. Полосы историй, режим правки, «＋ колонка».

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
  return `<article class="card ${t.statusKey === 'blocked' ? 'top' : ''}" draggable="true" data-code="${t.code}" style="--st:${STATUS_COLORS[t.statusKey] ?? '#8792a3'}">
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

export function Board({ tasks, reload }: { tasks: TaskCard[]; reload: () => void }) {
  const [columns, setColumns] = useState<Column[]>([])
  const [editMode, setEditMode] = useState(false)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const boardRef = useRef<HTMLDivElement>(null)
  const hintRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ code: string } | null>(null)

  useEffect(reloadColumns, [])

  // --- императивная подсветка DnD (никаких setState во время drag) ---
  function paintDrag(card: TaskCard) {
    const aliasOk: Record<string, boolean> = {}
    const aliasReason: Record<string, string> = {}
    for (const to of card.gate?.allowed ?? []) aliasOk[ALIAS_OF[to] ?? to] = true
    for (const d of card.gate?.denied ?? []) {
      const a = ALIAS_OF[d.to] ?? d.to
      if (!aliasOk[a]) aliasReason[a] = d.reason
    }
    boardRef.current?.querySelectorAll('.cell').forEach((el) => {
      const key = KEY_BY_LABEL[el.getAttribute('data-drop') ?? ''] ?? ''
      el.classList.toggle('ok', Boolean(aliasOk[key]))
    })
    const allow = Object.keys(aliasOk).map((k) => ALIAS_LB[k] ?? k)
    const deny = Object.entries(aliasReason).map(([k, r]) => `${ALIAS_LB[k] ?? k}: ${r}`)
    if (hintRef.current) {
      hintRef.current.innerHTML = allow.length
        ? `Разрешено: <b>${allow.join(', ')}</b>${deny.length ? ` · <span class="no">${deny.join(' · ')}</span>` : ''}`
        : `<span class="no">${deny.join(' · ') || 'нет допустимых переходов'}</span>`
    }
  }

  function clearPaint() {
    boardRef.current?.querySelectorAll('.cell.ok, .cell.over').forEach((el) => {
      el.classList.remove('ok', 'over')
    })
    document.body.classList.remove('is-dragging')
    if (hintRef.current) hintRef.current.innerHTML = ''
    dragRef.current = null
  }

  const cellsHtml = (items: TaskCard[]) => columns.map((col) => {
    const key = KEY_BY_LABEL[col.label] ?? ''
    const bucket = [...items.filter((t) => (ALIAS_OF[t.statusKey] ?? 'progress') === key)]
      .sort((a, b) => {
        const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
        const sa = (rank[a.priority] ?? 9) * 10 + (a.type === 'bug' ? 4 : 0)
        const sb = (rank[b.priority] ?? 9) * 10 + (b.type === 'bug' ? 4 : 0)
        return sa !== sb ? sb - sa : a.code.localeCompare(b.code)
      })
    return (
      <div key={col.id} className="cell" data-drop={col.label}
        style={{ ['--colc' as string]: bucket.length ? col.color : 'transparent' }}
        onDragOver={(e) => {
          // drop принимается на любой колонке (как в макете): запрет решается
          // на применении с человекочитаемым toast; подсветка .ok — только UX
          if (!dragRef.current) return
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
          if (e.currentTarget.classList.contains('ok')) e.currentTarget.classList.add('over')
        }}
        onDragLeave={(e) => e.currentTarget.classList.remove('over')}
        onDrop={(e) => {
          e.preventDefault()
          const code = dragRef.current?.code
          const wasCode = code
          clearPaint()
          if (wasCode) void applyDrop(wasCode, col.label, reload)
        }}>
        {bucket.map((t) => (
          <div key={t.code}
            dangerouslySetInnerHTML={{ __html: cardHtml(t, key === 'review' || key === 'testing') }}
            onDragStart={(e) => {
              dragRef.current = { code: t.code }
              document.body.classList.add('is-dragging')
              e.dataTransfer.effectAllowed = 'move'
              e.dataTransfer.setData('text/plain', t.code)
              void api.task(t.code).then(paintDrag)
            }}
            onDragEnd={clearPaint}
            onClick={(e) => {
              if ((e.target as HTMLElement).closest('[data-open-page]')) {
                window.location.hash = `#${t.code}/page`
                return
              }
              if ((e.target as HTMLElement).closest('.card')) {
                window.location.hash = `#${t.code}`
              }
            }} />
        ))}
      </div>
    )
  })

  const colHeads = columns.map((col) => {
    const key = KEY_BY_LABEL[col.label] ?? ''
    const count = tasks.filter((t) => t.type !== 'story' && (ALIAS_OF[t.statusKey] ?? '') === key).length
      + storiesOf(tasks).filter((s) => (ALIAS_OF[s.statusKey] ?? '') === key).length
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

  return (
    <>
      <div ref={hintRef} className="draghint" />
      <section className="board-scroll" aria-label="Kanban-доска">
        <div className={`board-grid ${editMode ? 'editing' : ''}`} ref={boardRef}>
          {colHeads}
          {addColumnGhost}
          {storiesOf(tasks).map((story) => {
            const kids = tasks.filter((t) => t.storyCode === story.code)
            const closedKids = kids.filter((k) => ['done', 'canceled'].includes(k.statusKey)).length
            return (
              <div key={story.code} className="lane">
                {storyBand(story, closedKids, kids.length)}
                {!collapsed[story.code] && <div className="lane-cells">{cellsHtml(kids)}</div>}
              </div>
            )
          })}
          {(() => {
            const loose = tasks.filter((t) => t.type !== 'story' && !t.storyCode)
            return loose.length > 0 ? (
              <div className="lane">
                <div className="lane-band" style={{ ['--st' as string]: '#8792a3' }}>
                  <span className="chev" style={{ visibility: 'hidden' }} />
                  <span className="t" style={{ color: 'var(--text3)' }}>Без истории</span>
                  <span className="kidscnt num">{loose.length} {plural(loose.length)}</span>
                  <span className="fill" />
                </div>
                <div className="lane-cells">{cellsHtml(loose)}</div>
              </div>
            ) : null
          })()}
        </div>
      </section>
    </>
  )

  function reloadColumns() {
    void api.aliasColumns().then((cols) =>
      setColumns([...cols].sort((a, b) => a.position - b.position)))
  }
}

function storiesOf(tasks: TaskCard[]): TaskCard[] {
  return tasks.filter((t) => t.type === 'story')
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
