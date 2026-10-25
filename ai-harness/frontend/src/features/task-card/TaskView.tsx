// Карточка задачи — DOM design_mockup/app.js:1018-1148 (drawer + полная страница):
// task-head (tcode, h2, pencil), meta-row (st-chip, prio, story-link, даты, тип+агент),
// теги, callouts модерации/блокировки, trans + trans-reasons, desc-view .md / editbar,
// чеклисты .cl с .cbx/.badge/.cl-x и текстовым режимом .cl-text, ПСИ .psi-doc,
// force details, хроники .chron-tabs/.chron-row/.evt/.tech.

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { renderMarkdown } from '../../shared/markdown'
import { parseChecklist, serializeChecklist, type ChecklistLine } from '../../shared/checklist'
import { RichText } from '../../shared/editor/RichText'
import { ALIAS_OF, esc, prioBadge, stChip, tagHtml, typeChip, xIcon, TYPE, S_LABEL } from '../../shared/refs'

const PENCIL = '<svg width="13" height="13" viewBox="0 0 14 14"><path d="M9.7 1.8l2.5 2.5L4.5 12H2V9.5l7.7-7.7z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'
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
  const [chronicle, setChronicle] = useState<{ id: string; type: string; authorKind: string; ruleCode?: string; message: string; at: string }[]>([])
  const [chronTab, setChronTab] = useState('all')
  const [editingDesc, setEditingDesc] = useState(false)
  const [descMode, setDescMode] = useState<'visual' | 'md'>('visual')
  const [descDraft, setDescDraft] = useState('')
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [forceOpen, setForceOpen] = useState(false)
  const [forceTo, setForceTo] = useState('')
  const [forceReason, setForceReason] = useState('')

  const reload = () => {
    void api.task(code).then((c) => { setCard(c); setDescDraft(c.descriptionMd ?? ''); setTitleDraft(c.title) })
      .catch(() => toast(`Задача ${code} не найдена`, 'bad'))
    void api.chronicle(code).then((r) => setChronicle(r.items))
  }
  useEffect(reload, [code])

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
    ['all', 'все'], ['field', 'поле'], ['transition', 'переходы'],
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
          <span className="meta-item" dangerouslySetInnerHTML={{ __html: prioBadge(card.priority, true) }} />
          {card.storyCode && (
            <span className="meta-item"><span className="lbl">История</span>
              <span className="story-link" onClick={() => { window.location.hash = `#${card.storyCode}` }}>
                <span className="code">{card.storyCode}</span></span></span>)}
          <span className="meta-item"><span className="lbl">Создана</span> <time>{card.createdAt?.slice(0, 16).replace('T', ' ')}</time></span>
          <span className="meta-item"><span className="lbl">Обновлена</span> <time>{card.updatedAt?.slice(0, 16).replace('T', ' ')}</time></span>
          <span className="meta-item" dangerouslySetInnerHTML={{ __html: typeChip(card.type) }} />
          {card.agent && <span className="meta-item"><span className="dot pulse" style={{ background: '#7d4fd1' }} /> в работе у {card.agent.name}</span>}
        </div>
        <div className="card-tags mt8">{(card.tags ?? []).map((t) => (
          <span key={t} dangerouslySetInnerHTML={{ __html: tagHtml(t) }} />
        ))}</div>
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
          <span className="cur">Сейчас: {S_LABEL[card.statusKey] ?? card.statusKey} →</span>
          {card.gate?.allowed.map((to) => (
            <button key={to} className="btn" onClick={async () => {
              const r = await api.transition(code, to)
              if (!r.applied) toast(r.reason ?? 'отказ', 'bad'); else toast(`<b>${code}</b> → ${S_LABEL[to] ?? to}`, 'ok')
              reload()
            }}>{S_LABEL[to] ?? to}</button>
          ))}
        </div>
        {card.gate && card.gate.denied.length > 0 && (
          <div className="trans-reasons">
            {card.gate.denied.map((d) => (
              <div key={d.to}><span dangerouslySetInnerHTML={{ __html: xIcon }} />
                {S_LABEL[d.to] ?? d.to} — {d.reason}</div>
            ))}
          </div>
        )}
        <details className="force" open={forceOpen}>
          <summary onClick={(e) => { setForceOpen(!forceOpen) }}>Форс-переход — с обязательной причиной</summary>
          <div className="fb">
            <textarea placeholder="Причина (обязательно)…"
              value={forceReason} onChange={(e) => setForceReason(e.target.value)} />
            <div className="fr">
              <select value={forceTo} onChange={(e) => setForceTo(e.target.value)}>
                <option value="">Куда…</option>
                {Object.keys(S_LABEL).map((s) => <option key={s} value={s}>{S_LABEL[s]}</option>)}
              </select>
              <button className="btn danger" disabled={!forceReason.trim() || !forceTo}
                onClick={async () => {
                  await api.force(code, forceTo, forceReason)
                  toast(`<b>${code}</b>: форс → ${S_LABEL[forceTo] ?? forceTo}`, 'auto')
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

      {typeVisible.developer && <ChecklistBlock code={code} kind="developer" title="Smart чек-лист разработчика" />}
      {typeVisible.reviewer && <ChecklistBlock code={code} kind="reviewer" title="Чек-лист ревьюера" />}
      {typeVisible.tester && <ChecklistBlock code={code} kind="tester" title="Чек-лист тестировщика" />}

      {card.type === 'story' && <PsiBlock code={code} reload={reload} />}

      <div className="blk">
        <div className="blk-h"><h3>Хроники</h3></div>
        <div className="chron-tabs">
          {chronTypes.map(([key, label]) => (
            <button key={key} className={chronTab === key ? 'active' : ''} onClick={() => setChronTab(key)}>{label}</button>
          ))}
        </div>
        {chronFiltered.map((c) => (
          <div key={c.id} className="chron-row">
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
    await fetch(`/api/v1/tasks/${code}/checklists/${kind}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines: serializeChecklist(next) }),
    })
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

function PsiBlock({ code, reload }: { code: string; reload: () => void }) {
  const [doc, setDoc] = useState<{ items: { position: number; kind: string; text: string; expected?: string; actual?: string; status: string; bugTaskId?: string }[]; runs: { id: string; passed: number; failed: number }[] } | null>(null)
  const [runMode, setRunMode] = useState(false)
  const [results, setResults] = useState<Record<number, { passed: boolean; actual: string }>>({})
  const reloadPsi = () => { void api.psi(code).then(setDoc) }
  useEffect(reloadPsi, [code])

  if (!doc || doc.items.length === 0) {
    return <div className="blk"><div className="blk-h"><h3>ПСИ</h3></div><div className="muted">Документ ПСИ ещё не составлен</div></div>
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
