// Доска — DOM и поведение design_mockup/app.js:726-854:
// .board-grid, .col-head (cdot/b/.n), .lane-band историй, .lane-cells > .cell,
// карточки cardHtml (code, type-chip, st-chip, prioBadge, tags, agent, card-sub),
// нативный DnD с подсветкой .cell.ok/.over и подсказкой .draghint,
// режим правки доски (.col-head.edit, палитра, colh-x, ghost «＋ колонка»).

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import {
  ALIAS_LB, ALIAS_OF, esc, prioBadge, stChip, tagHtml, typeChip,
} from '../../shared/refs'
import { pushUndo } from '../../shared/undo'
import { toast } from '../../shared/toast'

interface Column { id: string; label: string; color: string; position: number }

// ключ alias → колонка (по названию, как в макете ALIAS_LB)
const KEY_BY_LABEL: Record<string, string> = {
  'На рассмотрении': 'pending', 'Бэклог': 'backlog', 'К работе': 'todo', 'В работе': 'progress',
  'На ревью': 'review', 'На тестировании': 'testing', 'Готово': 'done',
  'Заблокировано': 'blocked', 'Отменено': 'canceled',
}
const labelOfKey = (key: string) => ALIAS_LB[key] ?? key

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

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'задача'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'задачи'
  return 'задач'
}

export function Board({ tasks, reload }: { tasks: TaskCard[]; reload: () => void }) {
  const [columns, setColumns] = useState<Column[]>([])
  const [editMode, setEditMode] = useState(false)
  const [dragCode, setDragCode] = useState<string | null>(null)
  const [okAliases, setOkAliases] = useState<Record<string, boolean>>({})
  const [deniedReasons, setDeniedReasons] = useState<Record<string, string>>({})
  const [overLabel, setOverLabel] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  useEffect(reloadColumns, [])

  useEffect(() => {
    if (!dragCode) { setOkAliases({}); setDeniedReasons({}); return }
    void api.task(dragCode).then((card) => {
      const ok: Record<string, boolean> = {}
      const denied: Record<string, string> = {}
      card.gate?.allowed.forEach((to) => { ok[to] = true })
      card.gate?.denied.forEach((x) => { denied[x.to] = x.reason })
      // сводим к alias-ключам: разрешено, если хоть один таргет колонки разрешён
      const okAlias: Record<string, boolean> = {}
      const deniedAlias: Record<string, string> = {}
      for (const to of card.gate?.allowed ?? []) okAlias[to] = true
      const aliasTargets: Record<string, { ok: boolean; reason: string }> = {}
      for (const to of card.gate?.allowed ?? []) aliasTargets[to] = { ok: true, reason: '' }
      for (const [to, reason] of Object.entries(denied)) {
        if (!aliasTargets[to]) aliasTargets[to] = { ok: false, reason }
      }
      for (const [to, info] of Object.entries(aliasTargets)) {
        const alias = ALIAS_OF[to] ?? to
        if (info.ok) okAlias[alias] = true
        else if (!okAlias[alias]) deniedAlias[alias] = info.reason
      }
      setOkAliases(okAlias)
      setDeniedReasons(deniedAlias)
      const allowList = Object.keys(okAlias).map((a) => labelOfKey(a))
      const denyList = Object.entries(deniedAlias)
        .map(([a, r]) => `${labelOfKey(a)}: ${r}`)
      setHint(allowList.length
        ? <>Разрешено: <b>{allowList.join(', ')}</b>{denyList.length ? <> · <span className="no">{denyList.join(' · ')}</span></> : null}</>
        : <span className="no">{denyList.join(' · ') || 'нет разрешённых переходов'}</span>)
    }).catch(() => { setOkAliases({}); setDeniedReasons({}) })
  }, [dragCode])

  const [hint, setHint] = useState<JSX.Element | null>(null)

  const stories = tasks.filter((t) => t.type === 'story')
  const loose = tasks.filter((t) => t.type !== 'story' && !t.storyCode)
  const byAlias = (items: TaskCard[], key: string) =>
    items.filter((t) => (t as TaskCard & { _alias?: string })._alias === key)

  // alias для каждой задачи считается один раз на рендер
  for (const t of tasks) {
    ;(t as TaskCard & { _alias?: string })._alias = ALIAS_OF[t.statusKey] ?? 'progress'
  }

  const cellsHtml = (items: TaskCard[]) => columns.map((col) => {
    const key = KEY_BY_LABEL[col.label] ?? ''
    const bucket = [...byAlias(items, key)].sort((a, b) => {
      const rank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
      const sa = (rank[a.priority] ?? 9) * 10 + (a.type === 'bug' ? 4 : 0)
      const sb = (rank[b.priority] ?? 9) * 10 + (b.type === 'bug' ? 4 : 0)
      return sa !== sb ? sb - sa : a.code.localeCompare(b.code)
    })
    const isOk = Boolean(okAliases[key])
    const isOver = overLabel === col.label
    const dragging = Boolean(dragCode)
    return (
      <div key={col.id} className={`cell ${isOk ? 'ok' : ''} ${isOver ? 'over' : ''}`}
        style={{ ['--colc' as string]: bucket.length || dragging ? col.color : 'transparent' }}
        data-drop={col.label}
        onDragOver={(e) => {
          if (!dragCode) return
          e.preventDefault()
          setOverLabel(col.label)
        }}
        onDragLeave={() => setOverLabel((cur) => (cur === col.label ? null : cur))}
        onDrop={(e) => {
          e.preventDefault()
          setOverLabel(null)
          if (dragCode) void applyDrop(dragCode, col.label, reload)
          setDragCode(null)
        }}>
        {bucket.map((t) => (
          <div key={t.code} dangerouslySetInnerHTML={{
            __html: cardHtml(t, key === 'review' || key === 'testing'),
          }}
            onDragStart={(e) => {
              setDragCode(t.code)
              document.body.classList.add('is-dragging')
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragEnd={() => { setDragCode(null); document.body.classList.remove('is-dragging') }}
            onClick={(e) => {
              // код задачи → полная страница; карточка → site-page поверх доски
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
    const count = byAlias(tasks, key).length
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
      {hint && <div className="draghint">{hint}</div>}
      <section className="board-scroll" aria-label="Kanban-доска">
        <div className={`board-grid ${editMode ? 'editing' : ''}`}>
          {colHeads}
          {addColumnGhost}
          {stories.map((story) => {
            const kids = tasks.filter((t) => t.storyCode === story.code)
            const closedKids = kids.filter((k) => ['done', 'canceled'].includes(k.statusKey)).length
            return (
              <div key={story.code} className="lane">
                {storyBand(story, closedKids, kids.length)}
                {!collapsed[story.code] && <div className="lane-cells">{cellsHtml(kids)}</div>}
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
              <div className="lane-cells">{cellsHtml(loose)}</div>
            </div>
          )}
        </div>
      </section>
    </>
  )

  function reloadColumns() {
    void api.aliasColumns().then((cols) =>
      setColumns([...cols].sort((a, b) => a.position - b.position)))
  }
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
