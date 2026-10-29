// Карточка задачи — DOM design_mockup/app.js:1018-1148 (drawer + полная страница):
// task-head (tcode, h2, pencil), meta-row (st-chip, prio, story-link, даты, тип+агент),
// теги, callouts модерации/блокировки, trans + trans-reasons, desc-view .md / editbar,
// чеклисты .cl с .cbx/.badge/.cl-x и текстовым режимом .cl-text, ПСИ .psi-doc,
// force details, хроники .chron-tabs/.chron-row/.evt/.tech.

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { fmtTokens } from '../../shared/live'
import { RunLogPanel } from './RunLogPanel'
import { renderMarkdown } from '../../shared/markdown'
import { parseChecklist, serializeChecklist, type ChecklistLine } from '../../shared/checklist'
import { RichText } from '../../shared/editor/RichText'
import { ALIAS_OF, esc, prioBadge, stChip, tagHtml, typeChip, xIcon, TYPE, S_LABEL } from '../../shared/refs'

const PENCIL = '<svg width="13" height="13" viewBox="0 0 14 14"><path d="M9.7 1.8l2.5 2.5L4.5 12H2V9.5l7.7-7.7z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'

interface ChronicleItem {
  id: string
  type: string
  authorKind: string
  ruleCode?: string
  message: string
  at: string
  live?: boolean  // запись пришла живым потоком, пока открыт экран
}
import { toast } from '../../shared/toast'

function useTaskCode(): string | null {
  const hash = window.location.hash.replace(/^#/, '')
  const m = hash.match(/^([A-Za-z]{2,10}-\d+)/)
  return m ? m[1].toUpperCase() : null
}

export function TaskView() {
  const code = useTaskCode()
  const [page, setPage] = useState(window.location.hash.endsWith('/page'))
  useEffect(() => {
    const onHash = () => setPage(window.location.hash.endsWith('/page'))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  if (!code) return <div className="empty"><b>Задача не открыта</b>выберите задачу на доске или в поиске</div>
  return page
    ? <TaskFullPage code={code} />
    : <TaskDrawer code={code} />
}

function TaskDrawer({ code }: { code: string }) {
  return (
    <>
      <div className="scrim show" onClick={() => { window.location.hash = '#board' }} />
      <aside className="drawer show" aria-label="Карточка задачи">
        <div className="drawer-head">
          <span className="crumb">Проект · <b>{code}</b></span>
          <span className="sp" />
          <button className="btn small" onClick={() => { window.location.hash = `#${code}/page` }}>Полная страница</button>
          <button className="icon-btn" aria-label="Закрыть" onClick={() => { window.location.hash = '#board' }}>{xIconHtml()}</button>
        </div>
        <div className="drawer-body"><TaskBody code={code} /></div>
      </aside>
    </>
  )
}

function xIconHtml() {
  return <span dangerouslySetInnerHTML={{ __html: xIcon }} />
}

function TaskFullPage({ code }: { code: string }) {
  return (
    <section className="taskpage" aria-label="Полная страница задачи">
      <div className="tp-head">
        <span className="crumb"><b>{code}</b> · полная страница</span>
        <button className="btn small" onClick={() => { window.location.hash = `#${code}` }}>← К доске</button>
      </div>
      <div className="tp-body"><div className="tp-inner"><TaskBody code={code} /></div></div>
    </section>
  )
}

function TaskBody({ code }: { code: string }) {
  const [card, setCard] = useState<TaskCard | null>(null)
  const [chronicle, setChronicle] = useState<ChronicleItem[]>([])
  const [chronTab, setChronTab] = useState('all')
  const [storyEdit, setStoryEdit] = useState(false)
  const [editingDesc, setEditingDesc] = useState(false)
  const [descMode, setDescMode] = useState<'visual' | 'md'>('visual')
  const [descDraft, setDescDraft] = useState('')
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [forceTo, setForceTo] = useState('')
  const [forceReason, setForceReason] = useState('')
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])
  const [liveRun, setLiveRun] = useState<{ agent: string; minutes: number; total: number; stale: boolean } | null>(null)
  const [lastLog, setLastLog] = useState('')

  // подпись статуса: точная — из flow-версии задачи (gate.labels),
  // фолбэк — канонический словарь; кастомные статусы владельца не показываются ключами
  const L = (key: string): string =>
    (card as { gate?: { labels?: Record<string, string> } } | null)?.gate?.labels?.[key]
      ?? S_LABEL[key] ?? key
  const reload = () => {
    void api.task(code).then((c) => { setCard(c); setDescDraft(c.descriptionMd ?? ''); setTitleDraft(c.title) })
      .catch(() => toast(`Задача ${code} не найдена`, 'bad'))
    void api.chronicle(code).then((r) => setChronicle(r.items))
      .catch(() => { /* хроника не критична: тихий фолбэк */ })
  }
  useEffect(reload, [code])

  // живой поток карточки (решение владельца 27.10.2026): активный прогон, токены,
  // строки лога и новые записи хроники появляются в реальном времени
  useEffect(() => {
    const es = new EventSource(`/api/v1/tasks/${code}/live`)
    es.addEventListener('run', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as { agent?: string; minutes?: number; total?: number; stale?: boolean }
        setLiveRun(d.agent ? { agent: d.agent, minutes: d.minutes ?? 0, total: d.total ?? 0, stale: Boolean(d.stale) } : null)
        if (d.agent) reload()
      } catch { /* пустое событие — прогон завершён */ }
    })
    es.addEventListener('log', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as { kind: string; text: string | null }
        if (d.text && d.kind !== 'prompt') setLastLog((d.text ?? '').slice(0, 140))
      } catch { /* ignore */ }
    })
    es.addEventListener('chronicle', (e) => {
      try {
        const item = JSON.parse((e as MessageEvent).data) as ChronicleItem
        setChronicle((cur) => cur.some((x) => x.id === item.id) ? cur : [{ ...item, live: true }, ...cur])
      } catch { /* ignore */ }
    })
    es.onerror = () => { /* браузер переподключится сам */ }
    return () => es.close()
  }, [code])

  if (!card) return <div className="empty"><b>Загрузка…</b></div>

  const approve = async () => {
    const r = await api.transition(code, 'backlog')
    if (!r.applied) toast(r.reason ?? 'отказ', 'bad')
    reload()
  }
  const reject = async () => {
    const r = await api.transition(code, 'canceled')
    if (!r.applied) toast(r.reason ?? 'отказ', 'bad')
    reload()
  }
  const saveTitle = async () => {
    await api.patchTask(code, { title: titleDraft })
    setEditingTitle(false); reload()
  }
  const saveDesc = async () => {
    const fresh = await api.patchTask(code, { descriptionMd: descDraft })
    if (fresh.changedByOther) toast('Карточка обновлена другим участником', 'auto')
    setEditingDesc(false); reload()
  }

  const typeVisible = {
    developer: ['common_task', 'bug'].includes(card.type),
    reviewer: ['common_task', 'analyse_task'].includes(card.type),
    tester: ['common_task', 'qa_task', 'bug', 'story'].includes(card.type),
  }

  const chronTypes = [
    ['runs', 'Прогоны'], ['all', 'все'], ['field', 'поле'], ['transition', 'переходы'],
    ['force', 'форс'], ['agent', 'агент'], ['psi', 'ПСИ'], ['bug', 'баг'],
  ]
  const chronFiltered = chronicle.filter((c) => chronTab === 'all' || c.type === chronTab)

  return (
    <>
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

      {card.statusKey === 'pending' && (
        <div className="callout warn">
          <span className="ci">⏳</span>
          <div className="body">
            Задача-предложение ждёт модерации. Апрув переведёт в бэклог, отклонение — отменит.
            <div className="actions">
              <button className="btn primary" onClick={() => void approve()}>Одобрить</button>
              <button className="btn danger" onClick={() => void reject()}>Отклонить</button>
            </div>
          </div>
        </div>
      )}
      {card.statusKey === 'blocked' && (
        <div className="callout bad">
          <span className="ci">⛔</span>
          <div className="body">{card.blockedReason || 'Работа заблокирована'}</div>
        </div>
      )}

      <div className="blk">
        <div className="trans">
          <span className="cur">Сейчас: {L(card.statusKey)} →</span>
          {card.gate?.allowed.map((to) => (
            <button key={to} className="btn" onClick={async () => {
              const r = await api.transition(code, to)
              if (!r.applied) toast(r.reason ?? 'отказ', 'bad'); else toast(`<b>${code}</b> → ${L(to)}`, 'ok')
              reload()
            }}>{L(to)}</button>
          ))}
        </div>
        {card.gate && card.gate.denied.length > 0 && (
          <div className="trans-reasons">
            {card.gate.denied.map((d) => (
              <div key={d.to}><span dangerouslySetInnerHTML={{ __html: xIcon }} />
                {L(d.to)} — {d.reason}</div>
            ))}
          </div>
        )}
        <details className="force">
          <summary>Форс-переход — с обязательной причиной</summary>
          <div className="fb">
            <textarea placeholder="Причина (обязательно)…"
              value={forceReason} onChange={(e) => setForceReason(e.target.value)} />
            <div className="fr">
              <select value={forceTo} onChange={(e) => setForceTo(e.target.value)}>
                <option value="">Куда…</option>
                {Object.entries({ ...S_LABEL, ...(card.gate?.labels ?? {}) }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <button className="btn danger" disabled={!forceReason.trim() || !forceTo}
                onClick={async () => {
                  await api.force(code, forceTo, forceReason)
                  toast(`<b>${code}</b>: форс → ${L(forceTo)}`, 'auto')
                  setForceReason(''); setForceTo(''); reload()
                }}>Форс-переход</button>
              <span className="note">Пишется в хроники как «форс · ручное вмешательство»</span>
            </div>
          </div>
        </details>
      </div>

      <div className="blk">
        <div className="blk-h"><h3>Описание</h3><span className="fill" />
          {!editingDesc && <button className="pencil show" title="Редактировать" dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => setEditingDesc(true)} />}
        </div>
        {editingDesc ? (
          <div className="desc-edit">
            <div className="editbar">
              <div className="mode-tabs">
                <button className={descMode === 'visual' ? 'active' : ''} onClick={() => setDescMode('visual')}>Визуально</button>
                <button className={descMode === 'md' ? 'active' : ''} onClick={() => setDescMode('md')}>Markdown</button>
              </div>
            </div>
            {descMode === 'visual'
              ? <RichText markdown={descDraft} onChange={setDescDraft} />
              : <textarea value={descDraft} onChange={(e) => setDescDraft(e.target.value)} />}
            <div className="edit-actions">
              <button className="btn primary" onClick={() => void saveDesc()}>Сохранить</button>
              <button className="btn" onClick={() => setEditingDesc(false)}>Отмена</button>
            </div>
          </div>
        ) : (
          <div className="desc-view">
            <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(card.descriptionMd ?? '') }} />
          </div>
        )}
      </div>

      <RelationsBlock code={code} relations={card.relations ?? []} reload={reload} />

      {typeVisible.developer && <ChecklistBlock code={code} kind="developer" title="Smart чек-лист разработчика" />}
      {typeVisible.reviewer && <ChecklistBlock code={code} kind="reviewer" title="Чек-лист ревьюера" />}
      {typeVisible.tester && <ChecklistBlock code={code} kind="tester" title="Чек-лист тестировщика" />}

      {card.type === 'story' && <PsiBlock code={code} reload={reload} psiPath={card.psiPath ?? null} />}

      {typeVisible.reviewer && <ArtifactBlock code={code} kind="review_report" title="Отчёт о ревью" />}
      {typeVisible.tester && card.type !== 'story' && <ArtifactBlock code={code} kind="qa_report" title="Отчёт о тестировании" />}

      <CommentsBlock code={code} />

      <div className="blk">
        <div className="blk-h"><h3>Хроники</h3></div>
        <div className="chron-tabs">
          {chronTypes.map(([key, label]) => (
            <button key={key} className={chronTab === key ? 'active' : ''} onClick={() => setChronTab(key)}>{label}</button>
          ))}
        </div>
        {chronTab !== 'runs' && liveRun && (
          <div className="chron-live" title="Записи появляются по мере работы агента">
            <span className={`dot ${liveRun.stale ? '' : 'pulse'}`} style={{ background: liveRun.stale ? '#c07d1e' : '#25935b' }} />
            <b>{liveRun.agent}</b> работает{liveRun.minutes ? ` · ${liveRun.minutes} мин` : ''}{liveRun.total ? ` · ${fmtTokens(liveRun.total)} токенов` : ''}
            {lastLog && <span className="ll"> · {lastLog}</span>}
          </div>
        )}
        {chronTab === 'runs' ? <RunLogPanel code={code} /> : chronFiltered.map((c) => (
          <div key={c.id} className={`chron-row ${c.live ? 'chron-new' : ''}`}>
            <time>{c.at.slice(11, 16)} · {c.at.slice(5, 10)}</time>
            <div className="chron-body">
              <span className="evt" style={{ ['--ec' as string]: evtColor(c.type) }}>{c.type}</span>
              {c.ruleCode && <span className="mini-chip mc-accent">{c.ruleCode}</span>} {c.message}
              <div className="who">{c.authorKind}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

function evtColor(type: string): string {
  return { field: '#8792a3', transition: '#3d63d2', force: '#c2601a', agent: '#7d4fd1',
    denied: '#cf4436', psi: '#1f8fb5', bug: '#cf4436' }[type] ?? '#8792a3'
}

export function ChecklistBlock({ code, kind, title }: { code: string; kind: string; title: string }) {
  const [lines, setLines] = useState<ChecklistLine[]>([])
  const [textMode, setTextMode] = useState(false)
  const [draft, setDraft] = useState('')
  const [newLine, setNewLine] = useState('')

  const reload = () => {
    void fetch(`/api/v1/tasks/${code}/checklists/${kind}`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setLines((d.items ?? []).map((i: { kind: string; text: string; status: string; level?: number }) =>
        i.kind === 'heading'
          ? { kind: 'heading', level: i.level ?? 1, text: i.text }
          : { kind: 'item', text: i.text, status: i.status as ChecklistLine['status'] })))
  }
  useEffect(reload, [code, kind])

  const save = async (next: ChecklistLine[]) => {
    setLines(next)
    const r = await fetch(`/api/v1/tasks/${code}/checklists/${kind}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines: serializeChecklist(next) }),
    })
    if (!r.ok) {
      toast('Не удалось сохранить чеклист', 'bad')
    }
  }

  const items = lines.filter((l) => l.kind === 'item')
  const closed = items.filter((l) => ['done', 'closed'].includes(l.status ?? '')).length

  const CLS_COLORS: Record<string, string> = {
    todo: '#8792a3', in_progress: '#3d63d2', closed: '#b98a12', done: '#25935b', failed: '#cf4436',
  }

  return (
    <div className="blk">
      <div className="blk-h">
        <h3>{title}</h3>
        <span className="muted">владелец: {kind === "developer" ? "разработчик" : kind === "reviewer" ? "ревьюер" : "тестировщик"}</span>
        <span className="bar"><i style={{ width: items.length ? `${(closed / items.length) * 100}%` : '0%' }} /></span>
        <span className="progr">{closed}/{items.length}</span>
        <button className="pencil" title="Текстовый режим (markdown со статусами)" aria-label="Текстовый режим" dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => { setDraft(serializeChecklist(lines)); setTextMode(!textMode) }} />
      </div>
      {textMode ? (
        <div className="cl-text">
          <div className="cl-gutter">{draft.split('\n').map((_, i) => <div key={i}>{i + 1}</div>)}</div>
          <textarea rows={Math.max(4, lines.length + 1)} value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => { void save(parseChecklist(draft)); setTextMode(false) }} />
        </div>
      ) : (
        <div className="cl">
          {lines.map((l, idx) => (
            <div key={idx} className={`cl-row ${l.status === 'done' ? 'done' : ''}`}>
              {l.kind === 'item' ? (
                <>
                  <button className="cbx" title="Сменить статус" onClick={() => {
                    const order: ChecklistLine['status'][] = ['todo', 'in_progress', 'done']
                    const cur = order.indexOf(l.status as ChecklistLine['status'])
                    const next = [...lines]
                    next[idx] = { ...l, status: order[(cur + 1) % order.length] }
                    void save(next)
                  }}>{l.status === 'done' ? '✓' : ''}</button>
                  <span className="cl-t">{l.text}</span>
                  <span className="badge" style={{ ['--bc' as string]: CLS_COLORS[l.status ?? 'todo'] }}>{l.status}</span>
                </>
              ) : (
                <span className={`cl-h${l.level ?? 1}`}>{'#'.repeat(l.level ?? 1)} {l.text}</span>
              )}
              <button className="cl-x" onClick={() => void save(lines.filter((_, i) => i !== idx))}>
                <span dangerouslySetInnerHTML={{ __html: xIcon }} />
              </button>
            </div>
          ))}
          <div className="cl-add">
            <input placeholder="Новый пункт — Enter добавляет"
              value={newLine}
              onChange={(e) => setNewLine(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newLine.trim()) {
                  void save([...lines, ...parseChecklist(newLine)])
                  setNewLine('')
                }
              }} />
          </div>
          <div className="cl-hint">Текстовый режим: <code>- ~ x + !</code> статусы пунктов, <code>#…#####</code> заголовки</div>
        </div>
      )}
    </div>
  )
}

function PsiBlock({ code, reload, psiPath }: { code: string; reload: () => void; psiPath: string | null }) {
  const [doc, setDoc] = useState<{ items: { position: number; kind: string; text: string; expected?: string; actual?: string; status: string; bugTaskId?: string }[]; runs: { id: string; passed: number; failed: number }[] } | null>(null)
  const [runMode, setRunMode] = useState(false)
  const [results, setResults] = useState<Record<number, { passed: boolean; actual: string }>>({})
  const reloadPsi = () => { void api.psi(code).then(setDoc).catch(() => { /* ПСИ ещё нет — норма */ }) }
  useEffect(reloadPsi, [code])

  const savePath = psiPath?.trim() || `.harness/psi/${code}/psi.md`
  if (!doc || doc.items.length === 0) {
    return <div className="blk"><div className="blk-h"><h3>ПСИ</h3></div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Сохраняется в: <span className="mono">{savePath}</span></div>
      <div className="muted">Документ ПСИ ещё не составлен</div></div>
  }
  const versions = doc.runs.length

  return (
    <div className="blk">
      <div className="blk-h"><h3>ПСИ · приёмо-сдаточные испытания</h3></div>
      <div className="psi-doc">
        <div className="psi-head"><b>ПСИ</b> · пунктов: {doc.items.filter((i) => i.kind === 'item').length} · протоколов: {versions}</div>
        {doc.items.filter((i) => i.kind === 'heading').length > 0 && null}
        {doc.items.filter((i) => i.kind === 'item').map((i) => (
          <div key={i.position} className={`psi-item ${runMode ? 'run' : ''}`}>
            <span className="n num">{i.position}.</span>
            <span className="a">
              {i.text}
              <span className="exp">Ожидаемо: {i.expected}</span>
              {runMode && (
                <>
                  <input className="psi-fact" placeholder="Фактический результат…"
                    value={results[i.position]?.actual ?? ''}
                    onChange={(e) => setResults((r) => ({ ...r, [i.position]: { passed: r[i.position]?.passed ?? true, actual: e.target.value } }))} />
                  <div className="psi-runbtns" style={{ flexDirection: 'row', gap: 6 }}>
                    <button className={`btn small ${results[i.position]?.passed === true ? 'primary' : ''}`}
                      onClick={() => setResults((r) => ({ ...r, [i.position]: { passed: true, actual: r[i.position]?.actual ?? '' } }))}>✓ Пройден</button>
                    <button className={`btn small danger ${results[i.position]?.passed === false ? 'primary' : ''}`}
                      onClick={() => setResults((r) => ({ ...r, [i.position]: { passed: false, actual: r[i.position]?.actual ?? '' } }))}>✗ Не пройден</button>
                  </div>
                </>
              )}
              {!runMode && i.actual && <span className={`fact ${i.status === 'failed' ? '' : 'ok'}`}>Факт: {i.actual}</span>}
            </span>
            <span className={`badge ${''}`} style={{ ['--bc' as string]: i.status === 'failed' ? '#cf4436' : i.status === 'done' ? '#25935b' : '#8792a3' }}>
              {i.status === 'done' ? 'пройден' : i.status === 'failed' ? 'не пройден' : 'не прогонялся'}
            </span>
          </div>
        ))}
        <div className="psi-runs">
          {runMode
            ? <>
                <button className="btn primary small" onClick={async () => {
                  const r = await api.psiRun(code, Object.entries(results).map(([position, v]) => ({
                    position: Number(position), passed: v.passed, actual: v.actual })))
                  toast(`Прогон: ${r.passed} ✓ / ${r.failed} ✗` +
                    (r.bugProposals.length ? ` · предложено багов: ${r.bugProposals.length}` : ''), r.failed ? 'bad' : 'ok')
                  setRunMode(false); setResults({}); reloadPsi(); reload()
                }}>Завершить прогон</button>
                <button className="btn small" onClick={() => { setRunMode(false); setResults({}) }}>Отмена</button>
              </>
            : <>
                <button className="btn small" onClick={() => setRunMode(true)}>▶ Начать прогон</button>
                <button className="btn small" onClick={async () => {
                  await fetch(`/api/v1/stories/${code}/psi/new-cycle`, { method: 'POST' })
                  toast('Новый цикл: пункты сброшены, протоколы целы', 'ok'); reloadPsi()
                }}>Новый цикл</button>
                {doc.runs.map((r) => (
                  <span key={r.id} className="mini-chip">{r.passed}✓/{r.failed}✗</span>
                ))}
              </>}
        </div>
      </div>
    </div>
  )
}

export { TYPE, esc }


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

function ArtifactBlock({ code, kind, title }: { code: string; kind: string; title: string }) {
  const [versions, setVersions] = useState<{ version: number; bodyMd: string; at: string }[]>([])
  const [body, setBody] = useState('')
  const reload = () => { void api.artifact(code, kind).then((d) => setVersions(d.versions ?? [])) }
  useEffect(reload, [code, kind])
  return (
    <div className="blk">
      <div className="blk-h"><h3>{title}</h3><span className="progr">{versions.length ? `v${versions[versions.length - 1].version}` : 'нет'}</span></div>
      {versions.map((v) => (
        <details key={v.version} className="tech">
          <summary>Версия v{v.version} · {v.at.slice(0, 16).replace('T', ' ')}</summary>
          <pre>{v.bodyMd}</pre>
        </details>
      ))}
      <textarea className="psi-fact" rows={3} placeholder="Новый отчёт (markdown)…"
        value={body} onChange={(e) => setBody(e.target.value)} />
      <button className="btn small mt8" disabled={!body.trim()} onClick={async () => {
        await api.addArtifact(code, kind, body); setBody(''); reload()
      }}>Добавить отчёт</button>
    </div>
  )
}

function CommentsBlock({ code }: { code: string }) {
  const [items, setItems] = useState<{ id: string; author: string; body: string; at: string }[]>([])
  const [draft, setDraft] = useState('')
  const [mode, setMode] = useState<'visual' | 'text'>('visual')
  const reload = () => {
    void api.comments(code).then((d: unknown) => setItems(Array.isArray(d) ? (d as typeof items) : []))
      .catch(() => { /* комментарии не критичны */ })
  }
  useEffect(reload, [code])
  const send = () => {
    if (!draft.trim()) return
    void api.addComment(code, draft).then(() => { setDraft(''); reload() })
  }
  return (
    <div className="blk">
      <div className="blk-h"><h3>Комментарии</h3><span className="fill" />
        <div className="mode-tabs">
          <button className={mode === 'visual' ? 'active' : ''} onClick={() => setMode('visual')}>Визуально</button>
          <button className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>Текст</button>
        </div></div>
      {items.map((c) => (
        <div key={c.id} className="cmt">
          <span className="ava">{c.author.slice(0, 1)}</span>
          <div className="b"><div className="h"><b>{c.author}</b> · {c.at.slice(0, 16).replace('T', ' ')}</div>
            <div className="tx md" dangerouslySetInnerHTML={{ __html: renderMarkdown(c.body) }} /></div>
        </div>
      ))}
      <div className="cmt-add">
        {mode === 'visual'
          ? <RichText markdown={draft} onChange={setDraft} />
          : <textarea rows={4} placeholder="Markdown-комментарий… (**жирный**, списки, код)"
              value={draft} onChange={(e) => setDraft(e.target.value)} />}
        <div className="edit-actions">
          <button className="btn primary small" onClick={send} disabled={!draft.trim()}>Отправить</button>
        </div>
      </div>
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

function RelationsBlock({ code, relations, reload }: {
  code: string
  relations: { id: string; kind: string; code: string; title: string }[]
  reload: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [kind, setKind] = useState('do_after')
  const [q, setQ] = useState('')
  const [found, setFound] = useState<{ code: string; title: string }[]>([])
  useEffect(() => {
    if (!adding || !q.trim()) { setFound([]); return }
    const t = setTimeout(() => {
      void api.tasks({ q: q.trim() }).then((d) =>
        setFound((d.items ?? []).filter((x: { code: string }) => x.code !== code).slice(0, 6)))
    }, 250)
    return () => clearTimeout(t)
  }, [q, adding, code])
  const add = (toCode: string) => {
    void api.addRelation(code, toCode, kind).then(() => { setAdding(false); setQ(''); reload() })
      .catch((e: Error) => toast(e.message, 'bad'))
  }
  const KIND: Record<string, string> = { do_after: 'делать после этой', blocked_by: 'блокирована задачей' }
  return (
    <div className="blk">
      <div className="blk-h"><h3>Связанные задачи</h3><span className="fill" />
        <button className="btn small" onClick={() => setAdding(!adding)}>＋ связь</button></div>
      {(relations ?? []).map((r) => (
        <div key={r.id} className="rel" onClick={() => { window.location.hash = `#${r.code}` }}>
          <span className="code">{r.code}</span>
          <span className="rt">{r.title}</span>
          <span className={`linkchip ${r.kind === 'blocked_by' ? 'hard' : ''}`}>{KIND[r.kind] ?? r.kind}</span>
          <button className="cl-x" title="Убрать связь" onClick={(e) => {
            e.stopPropagation()
            void api.delRelation(code, r.id).then(reload)
          }}><span dangerouslySetInnerHTML={{ __html: xIcon }} /></button>
        </div>
      ))}
      {!relations?.length && !adding && (
        <div className="muted" style={{ fontSize: 12 }}>Связей нет. Добавьте задачу, которая делается после этой или блокирует её.</div>)}
      {adding && (
        <div className="rel-add">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="do_after">делать после этой</option>
            <option value="blocked_by">блокирована задачей</option>
          </select>
          <input placeholder="Код или название задачи…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          {found.map((f) => (
            <div key={f.code} className="rel" onClick={() => add(f.code)}>
              <span className="code">{f.code}</span><span className="rt">{f.title}</span>
            </div>
          ))}
          {q && !found.length && <div className="muted" style={{ fontSize: 12 }}>Ничего не найдено</div>}
        </div>
      )}
    </div>
  )
}
