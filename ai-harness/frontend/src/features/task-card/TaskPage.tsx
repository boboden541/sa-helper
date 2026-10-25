// Карточка задачи: идентификация → классификация → метаданные → описание →
// работа (чеклисты/форс) → память (хроники, ПСИ) (СТ §5.3, 14 групп в фикс. порядке).

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { renderMarkdown } from '../../shared/markdown'
import { ChecklistBlock } from './Checklist'

export function TaskPage() {
  const code = useCode()
  const [card, setCard] = useState<TaskCard | null>(null)
  const [chronicle, setChronicle] = useState<{ id: string; type: string; authorKind: string; ruleCode?: string; message: string; at: string }[]>([])
  const [editing, setEditing] = useState(false)
  const [descDraft, setDescDraft] = useState('')
  const [mode, setMode] = useState<'visual' | 'md'>('visual')
  const [forceReason, setForceReason] = useState('')
  const [forceTo, setForceTo] = useState('')
  const [changed, setChanged] = useState(false)

  const reload = () => {
    if (!code) return
    void api.task(code).then((c) => { setCard(c); setDescDraft(c.descriptionMd ?? '') })
    void api.chronicle(code).then((r) => setChronicle(r.items))
  }
  useEffect(reload, [code])

  if (!code) return <div className="empty">Откройте задачу с доски или поиска</div>
  if (!card) return <div className="empty">Загрузка…</div>

  const saveDescription = async () => {
    const fresh = await api.patchTask(code, { descriptionMd: descDraft })
    if (fresh.changedByOther) setChanged(true)
    setEditing(false)
    reload()
  }

  return (
    <div className="taskpage">
      {changed && <div className="banner warn">Карточка обновлена другим участником — показана свежая версия</div>}
      {card.statusKey === 'pending' && <div className="banner">Задача ждёт модерации (pending)</div>}
      {card.statusKey === 'blocked' && <div className="banner danger">Заблокировано: {card.blockedReason}</div>}
      {card.agent && <div className="banner">⟳ В работе у агента {card.agent.name}</div>}

      <header className="card-head">
        <span className="code">{card.code}</span>
        <h2>{card.title}</h2>
        <span className={`prio prio-${card.priority}`}>{card.priority}</span>
        <span className="chip">{card.type}</span>
        {card.storyCode && <span className="chip">история {card.storyCode}</span>}
        <span className="dates">{card.createdAt} · обновлено {card.updatedAt}</span>
      </header>

      <div className="tags">{(card.tags ?? []).map((t) => <span key={t} className="tag">#{t}</span>)}</div>

      <section className="block">
        <h3>Описание {editing
          ? <span className="modes"><button className={mode === 'visual' ? 'on' : ''} onClick={() => setMode('visual')}>Визуально</button><button className={mode === 'md' ? 'on' : ''} onClick={() => setMode('md')}>Markdown</button><button className="btn small" onClick={() => void saveDescription()}>Сохранить</button><button className="btn small" onClick={() => setEditing(false)}>Отмена</button></span>
          : <button className="pencil" onClick={() => setEditing(true)}>✎</button>}</h3>
        {editing && mode === 'md'
          ? <textarea className="desc-edit" value={descDraft} onChange={(e) => setDescDraft(e.target.value)} rows={8} />
          : editing
            ? <textarea className="desc-edit" value={descDraft} onChange={(e) => setDescDraft(e.target.value)} rows={8} placeholder="Визуальный редактор (TipTap) подключается здесь" />
            : <div className="desc" dangerouslySetInnerHTML={{ __html: renderMarkdown(card.descriptionMd ?? '') }} />}
      </section>

      {card.type !== 'story' && ['common_task', 'bug'].includes(card.type) && (
        <ChecklistBlock code={code} kind="developer" title="Smart чек-лист разработчика" />
      )}
      {['common_task', 'analyse_task'].includes(card.type) && (
        <ChecklistBlock code={code} kind="reviewer" title="Чек-лист ревьюера" />
      )}
      {['common_task', 'qa_task', 'bug', 'story'].includes(card.type) && (
        <ChecklistBlock code={code} kind="tester" title="Чек-лист тестировщика" />
      )}

      <section className="block">
        <h3>Переходы</h3>
        <div className="transitions">
          {card.gate?.allowed.map((to) => (
            <button key={to} className="btn" onClick={async () => {
              const r = await api.transition(code, to)
              if (!r.applied) alert(r.reason)
              reload()
            }}>{to}</button>
          ))}
          {card.gate?.denied.map((d) => (
            <button key={d.to} className="btn dead" disabled title={d.reason}>{d.to}</button>
          ))}
        </div>
        <details className="force">
          <summary>Форс-переход (причина обязательна)</summary>
          <input placeholder="статус, напр. todo" value={forceTo} onChange={(e) => setForceTo(e.target.value)} />
          <input placeholder="причина…" value={forceReason} onChange={(e) => setForceReason(e.target.value)} />
          <button className="btn" disabled={!forceReason.trim() || !forceTo.trim()} onClick={async () => {
            await api.force(code, forceTo, forceReason)
            setForceReason(''); setForceTo(''); reload()
          }}>Форс</button>
        </details>
      </section>

      {card.type === 'story' && <PsiBlock code={code} reload={reload} />}

      <section className="block">
        <h3>Хроники</h3>
        <div className="chron">
          {chronicle.map((c) => (
            <div key={c.id} className={`chron-row t-${c.type}`}>
              <span className="chron-type">{c.type}</span>
              {c.ruleCode && <span className="chip">{c.ruleCode}</span>}
              <span>{c.message}</span>
              <span className="chron-who">{c.authorKind} · {c.at}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function useCode(): string | null {
  const hash = window.location.hash.replace(/^#/, '')
  const m = hash.match(/^([A-Za-z]{2,10}-\d+)/)
  return m ? m[1].toUpperCase() : null
}

function PsiBlock({ code, reload }: { code: string; reload: () => void }) {
  const [doc, setDoc] = useState<{ items: { position: number; kind: string; text: string; expected?: string; actual?: string; status: string }[]; runs: unknown[] } | null>(null)
  const [results, setResults] = useState<Record<number, { passed: boolean; actual: string }>>({})
  const reloadPsi = () => void api.psi(code).then(setDoc)
  useEffect(reloadPsi, [code])

  if (!doc || doc.items.length === 0) return <section className="block"><h3>ПСИ</h3><div className="empty">Документ ПСИ ещё не составлен</div></section>

  return (
    <section className="block">
      <h3>ПСИ · документ и прогоны</h3>
      {doc.items.filter((i) => i.kind === 'item').map((i) => (
        <div key={i.position} className="psi-row">
          <span className={`psi-status s-${i.status}`}>{i.status}</span>
          <b>{i.position}.</b> {i.text}
          <div className="psi-expected">Ожидаемо: {i.expected}</div>
          <input placeholder="фактический результат" value={results[i.position]?.actual ?? i.actual ?? ''}
            onChange={(e) => setResults((r) => ({ ...r, [i.position]: { passed: r[i.position]?.passed ?? true, actual: e.target.value } }))} />
          <label><input type="checkbox" checked={results[i.position]?.passed ?? i.status !== 'failed'}
            onChange={(e) => setResults((r) => ({ ...r, [i.position]: { passed: e.target.checked, actual: r[i.position]?.actual ?? '' } }))} /> пройден</label>
        </div>
      ))}
      <button className="btn" onClick={async () => {
        await api.psiRun(code, Object.entries(results).map(([position, r]) => ({
          position: Number(position), passed: r.passed, actual: r.actual,
        })))
        setResults({}); reloadPsi(); reload()
      }}>Завершить прогон</button>
      <div className="runs">Протоколов: {doc.runs.length}</div>
    </section>
  )
}
