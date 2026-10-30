// Шапка карточки задачи — task-head (tcode, h2, pencil), meta-row (st-chip, prio,
// story-link, даты, тип+агент, живой прогон, токены, репозиторий), теги с правкой
// и выбором истории. Перенесено из монолита TaskView.tsx разметка 1:1.

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../../api/client'
import { fmtTokens } from '../../../shared/live'
import { prioBadge, stChip, tagHtml, typeChip } from '../../../shared/refs'
import { toast } from '../../../shared/toast'
import { PENCIL, type LiveRun } from './common'

export function TaskHead({ code, card, liveRun, reload }: {
  code: string
  card: TaskCard
  liveRun: LiveRun | null
  reload: () => void
}) {
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [storyEdit, setStoryEdit] = useState(false)
  const [repoOptions, setRepoOptions] = useState<{ label: string; repoPath: string | null }[]>([])
  useEffect(() => {
    if (!card?.project) return
    void api.projectRepos(card.project).then((r) => setRepoOptions(r.repos)).catch(() => setRepoOptions([]))
  }, [card?.project])
  useEffect(() => { setTitleDraft(card.title) }, [card])
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])

  const saveTitle = async () => {
    await api.patchTask(code, { title: titleDraft })
    setEditingTitle(false); reload()
  }

  return (
    <div className="blk">
      <div className="task-head">
        <span className="tcode">{card.code}</span>
        {editingTitle
          ? <input className="title-input" value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={() => void saveTitle()}
              onKeyDown={(e) => e.key === 'Enter' && void saveTitle()} />
          : <h2>{card.title}
              <button className="pencil" title="Переименовать" dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => setEditingTitle(true)} />
            </h2>}
      </div>
      <div className="meta-row">
        <span dangerouslySetInnerHTML={{ __html: stChip(card.statusKey) }} />
        <span className="pop">
          <button className="meta-item" onClick={(e) => {
            const menu = e.currentTarget.parentElement?.querySelector('.prio-menu') as HTMLElement
            if (menu) menu.hidden = !menu.hidden
          }} style={{ cursor: 'pointer' }}>
            <span className="lbl">Приоритет</span>
            <span dangerouslySetInnerHTML={{ __html: prioBadge(card.priority, true) }} />
          </button>
          <div className="prio-menu" hidden>
            {(['low', 'medium', 'high', 'critical'] as const).map((p) => (
              <button key={p} className={card.priority === p ? 'sel' : ''} onClick={async (e) => {
                e.stopPropagation()
                const menu = e.currentTarget.closest('.prio-menu') as HTMLElement
                menu.hidden = true
                await api.patchTask(code, { priority: p })
                toast(`Приоритет → ${p}`, 'ok')
                reload()
              }}>
                <span dangerouslySetInnerHTML={{ __html: prioBadge(p, true) }} />
                {card.priority === p && <span className="d">✓</span>}
              </button>
            ))}
          </div>
        </span>
        <span className="meta-item"><span className="lbl">История</span>
          {storyEdit ? <span className="muted">выберите ниже…</span> : card.storyCode ? (
            <span className="story-link" onClick={() => { window.location.hash = `#${card.storyCode}` }}>
              <span className="code">{card.storyCode}</span></span>
          ) : <span className="muted">—</span>}
          <button className="pencil" title="Привязать к истории / отвязать"
            dangerouslySetInnerHTML={{ __html: PENCIL }}
            onClick={() => setStoryEdit(!storyEdit)} />
        </span>
        {storyEdit && <StoryPicker code={code} current={card.storyCode ?? null}
          onDone={() => { setStoryEdit(false); reload() }} />}
        {['common_task', 'story', 'bug'].includes(card.type) && (
          <span className="meta-item"><span className="lbl">Репозиторий</span>
            <select value={card.repoPath ?? ''} style={{ maxWidth: 200 }}
              onChange={(e) => {
                const v = e.target.value || undefined
                void api.patchTask(code, { repoPath: v })
                  .then(() => { toast(v ? `Репозиторий → ${v}` : 'Репозиторий снят', 'ok'); reload() })
                  .catch((err: Error) => toast(err.message, 'bad'))
              }}>
              <option value="">— не указан —</option>
              {(card.project ? repoOptions : []).map((r) =>
                <option key={r.repoPath ?? ''} value={r.repoPath ?? ''}>{r.label}</option>)}
            </select></span>
        )}
        <span className="meta-item"><span className="lbl">Создана</span> <time>{card.createdAt?.slice(0, 16).replace('T', ' ')}</time></span>
        <span className="meta-item"><span className="lbl">Обновлена</span> <time>{card.updatedAt?.slice(0, 16).replace('T', ' ')}</time></span>
        <span className="meta-item" dangerouslySetInnerHTML={{ __html: typeChip(card.type) }} />
        {liveRun
          ? <span className="meta-item live-run" title="Агент работает прямо сейчас (живой поток)">
              <span className={`dot ${liveRun.stale ? '' : 'pulse'}`} style={{ background: liveRun.stale ? '#c07d1e' : '#25935b' }} />
              {liveRun.agent} работает · {liveRun.minutes} мин{liveRun.total ? ` · ${fmtTokens(liveRun.total)}` : ''}
            </span>
          : card.agent && <span className="meta-item"><span className="dot pulse" style={{ background: '#7d4fd1' }} /> в работе у {card.agent.name}</span>}
        {(card.tokensUsed ?? 0) > 0 && (
          <span className="meta-item" title="Суммарный расход токенов всеми прогонами задачи">
            <span className="lbl">Токены</span> <b className="tok">{fmtTokens(card.tokensUsed)}</b>
          </span>
        )}
      </div>
      <div className="card-tags mt8">
        {(card.tags ?? []).map((t) => <span key={t} dangerouslySetInnerHTML={{ __html: tagHtml(t) }} />)}
        {!tagsEditing && (
          <button className="pencil show" title="Редактировать теги"
            dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => { setTagsDraft([...(card.tags ?? [])]); setTagsEditing(true) }} />
        )}
      </div>
      {tagsEditing && <TagsEditor code={code} draft={tagsDraft} setDraft={setTagsDraft}
        onDone={() => { setTagsEditing(false); reload() }} />}
    </div>
  )
}

function TagsEditor({ code, draft, setDraft, onDone }: {
  code: string; draft: string[]; setDraft: (d: string[]) => void; onDone: () => void
}) {
  const [input, setInput] = useState('')
  return (
    <div className="tags-edit">
      {draft.map((t) => {
        const sys = t === 'by_human' || t === 'by_ai'
        return (
          <span key={t} className="tagx">#{t}
            <button title={sys ? 'Авторский тег удалить нельзя' : 'Убрать тег'} disabled={sys}
              onClick={() => setDraft(draft.filter((x) => x !== t))}>✕</button>
          </span>
        )
      })}
      <span className="tag-input-wrap">
        <input value={input} placeholder="новый тег…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && input.trim()) {
              const label = input.trim().replace(/^#/, '')
              if (!draft.includes(label) && draft.length < 5) setDraft([...draft, label])
              setInput('')
            }
          }} />
      </span>
      <button className="btn small" onClick={async () => {
        await api.patchTags(code, draft); onDone()
      }}>Сохранить</button>
      <button className="btn small" onClick={onDone}>Отмена</button>
    </div>
  )
}

function StoryPicker({ code, current, onDone }: { code: string; current: string | null; onDone: () => void }) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<{ code: string; title: string; statusKey: string }[]>([])
  useEffect(() => {
    if (!q.trim()) { setFound([]); return }
    const t = setTimeout(() => {
      void api.tasks({ q: q.trim(), types: 'story' }).then((d) =>
        setFound((d.items ?? []).filter((x: { code: string }) => x.code !== code)))
    }, 250)
    return () => clearTimeout(t)
  }, [q, code])
  const link = (storyCode: string | null) => {
    void api.storyLink(code, storyCode).then(onDone)
      .catch((e: Error) => toast(e.message, 'bad'))
  }
  return (
    <div className="story-picker">
      <input placeholder="Найдите историю по коду или названию…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      {current && <button className="btn danger small" onClick={() => link(null)}>Отвязать от {current}</button>}
      {found.map((f) => (
        <div key={f.code} className="rel" onClick={() => link(f.code)}>
          <span className="code">{f.code}</span>
          <span className="rt">{f.title}</span>
          <span className="mini-chip">{f.statusKey}</span>
        </div>
      ))}
      {q && !found.length && <div className="muted" style={{ fontSize: 12 }}>Истории не найдены</div>}
    </div>
  )
}
