// Настройки: вкладки Status-flow (граф React Flow + таблица одной рабочей копии),
// Провайдеры, Агенты и матрица, Проекты, Очередь, Журнал (СТ §5.5).

import { useEffect, useState } from 'react'
import {
  Background, Controls, ReactFlow,
  type Connection, type Edge, type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../../api/client'
import { pushUndo } from '../../shared/undo'

const TABS = ['flow', 'providers', 'agents', 'matrix', 'projects', 'queue', 'journal'] as const

export function Settings({ reload }: { reload: () => void }) {
  const tab = useSettingsTab()
  return (
    <div className="settings">
      <div className="set-tabs">
        {TABS.map((t) => <TabButton key={t} tab={t} />)}
      </div>
      {tab === 'flow' && <FlowEditor reload={reload} />}
      {tab === 'providers' && <Providers />}
      {tab === 'agents' && <Agents />}
      {tab === 'matrix' && <Matrix />}
      {tab === 'projects' && <Projects />}
      {tab === 'queue' && <Queue />}
      {tab === 'journal' && <Journal />}
    </div>
  )
}

function useSettingsTab(): string {
  const hash = window.location.hash
  const m = hash.match(/settings\/(\w+)/)
  return m ? m[1] : 'flow'
}

function TabButton({ tab }: { tab: string }) {
  const current = useSettingsTab()
  const names: Record<string, string> = {
    flow: 'Status-flow', providers: 'Провайдеры', agents: 'Агенты',
    matrix: 'Матрица', projects: 'Проекты', queue: 'Очередь', journal: 'Журнал',
  }
  return (
    <button className={`set-tab ${current === tab ? 'active' : ''}`}
      onClick={() => { window.location.hash = `#settings/${tab}` }}>{names[tab] ?? tab}</button>
  )
}

function FlowEditor({ reload }: { reload: () => void }) {
  const [typeKey, setTypeKey] = useState('common_task')
  const [data, setData] = useState<Awaited<ReturnType<typeof api.flow>> | null>(null)
  const [columns, setColumns] = useState<{ id: string; label: string }[]>([])
  const [dirty, setDirty] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const reloadFlow = () => {
    void api.flow(typeKey).then(setData)
    void api.aliasColumns().then(setColumns)
  }
  useEffect(reloadFlow, [typeKey])

  if (!data) return <div className="empty">Загрузка flow…</div>

  const nodes: Node[] = data.statuses.map((s) => ({
    id: s.key,
    position: nodePositions(s.key, data.statuses.length),
    data: { label: <>{s.label}<br /><small>{s.key}{s.gate ? ` · гейт: ${s.gate}` : ''}</small></> },
    style: { borderRadius: 10, padding: 6, ...(s.terminal ? { border: '2px solid #1e8e3e' } : {}) },
  }))
  const edges: Edge[] = data.transitions.map((t, i) => ({
    id: `e${i}`, source: t.from, target: t.to,
    label: t.rule ?? t.display, animated: t.runner === 'auto',
  }))

  const saveDraft = async (d = data) => {
    await api.saveDraft(typeKey, {
      statuses: d.statuses.map((s) => ({ key: s.key, label: s.label, gate: s.gate,
        entry: s.entry, terminal: s.terminal, alias_column_id: s.aliasColumnId })),
      transitions: d.transitions.map((t) => ({ from: t.from, to: t.to, runner: t.runner, display: t.display })),
    })
    setDirty(false)
  }

  return (
    <div className="set-body">
      <div className="flow-toolbar">
        <select value={typeKey} onChange={(e) => setTypeKey(e.target.value)}>
          {['story', 'common_task', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <span className="mini-chip mc-accent">версия v{data.version}{data.isPublished ? '' : ' · черновик'}</span>
        <button className="btn" disabled={!dirty} onClick={() => void saveDraft()}>Сохранить черновик</button>
        <button className="btn primary" onClick={async () => {
          await saveDraft()
          try {
            const r = await api.publishFlow(typeKey)
            setMessage(`Опубликовано v${r.version}`)
            reloadFlow(); reload()
          } catch (err) {
            setMessage((err as Error).message)
          }
        }}>Опубликовать</button>
        {message && <span className="note">{message}</span>}
      </div>
      <div className="flow-body">
        <div className="flow-canvas" style={{ height: 460 }}>
          <ReactFlow
            nodes={nodes} edges={edges} fitView
            onConnect={async (conn: Connection) => {
              if (data.transitions.some((t) => t.from === conn.source && t.to === conn.target)) {
                setMessage('Такой переход уже существует')
                return
              }
              const next = { ...data, transitions: [...data.transitions, {
                from: conn.source!, to: conn.target!, runner: 'human', display: 'Ручное вмешательство' }] }
              setData(next); setDirty(true)
              pushUndo({ label: `Переход ${conn.source}→${conn.target}`, undo: () => {
                setData((cur) => cur && { ...cur, transitions: cur.transitions.filter(
                  (t) => !(t.from === conn.source && t.to === conn.target)) })
              } })
            }}
          >
            <Background /><Controls />
          </ReactFlow>
        </div>
        <table className="tasks flow-table">
          <thead><tr><th>Статус</th><th>Что происходит</th><th>Возможные переходы</th></tr></thead>
          <tbody>
            {data.statuses.map((s) => (
              <tr key={s.key}>
                <td><b>{s.label}</b><br /><small>{s.key}</small></td>
                <td>{s.gate ? `гейт: ${s.gate}` : ''}</td>
                <td>
                  {data.transitions.filter((t) => t.from === s.key).map((t, i) => (
                    <span key={i} className="chip clickable" title={t.display}
                      onClick={() => {
                        setData((cur) => cur && { ...cur, transitions: cur.transitions.filter(
                          (x) => !(x.from === t.from && x.to === t.to)) })
                        setDirty(true)
                      }}>{t.to} ✕</span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">Граф и таблица редактируют одну рабочую копию. Колонок alias: {columns.length}</p>
    </div>
  )
}

function nodePositions(key: string, total: number): { x: number; y: number } {
  let h = 0
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) % 997
  return { x: (h % 5) * 220, y: (h % 4) * 140 + total }
}

function Providers() {
  const [list, setList] = useState<{ id: string; name: string; protocol: string; url: string; model: string; tokenTail: string; checkStatus: string; isActive: boolean }[]>([])
  const [form, setForm] = useState({ name: '', protocol: 'anthropic', url: '', model: '', token: '' })
  const [message, setMessage] = useState<string | null>(null)
  const reload = () => void api.requestProviders().then(setList)
  useEffect(reload, [])

  return (
    <div className="set-body">
      <div className="prov-grid">
        <div>
          <div className="q-sec">Подключения</div>
          {list.map((c) => (
            <div key={c.id} className={`prov-row ${c.isActive ? 'active' : ''}`}>
              <div className="pr-main">
                <b>{c.name}</b> <span className="mini-chip">{c.protocol}</span>
                <div className="muted">{c.url} · {c.model}</div>
                <div className="muted">токен {c.tokenTail} · проверка: {c.checkStatus}</div>
              </div>
              <div className="pr-actions">
                {!c.isActive && (
                  <button className="btn small" onClick={async () => {
                    await fetch(`/api/v1/connections/${c.id}/activate`, { method: 'POST' }); reload()
                  }}>Сделать активным</button>
                )}
              </div>
            </div>
          ))}
          {list.length === 0 && <div className="muted">Подключений пока нет</div>}
        </div>
        <div className="prov-form">
          <div className="q-sec">Новое подключение</div>
          <div className="f-field"><label>Название</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="f-field"><label>Протокол</label>
            <select value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI-совместимый</option>
            </select></div>
          <div className="f-field"><label>URL</label>
            <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></div>
          <div className="f-field"><label>Модель</label>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
          <div className="f-field"><label>API-токен</label>
            <input type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} /></div>
          <div className="flex mt12">
            <button className="btn" onClick={async () => {
              try {
                const res = await fetch('/api/v1/connections/check', {
                  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
                const body = await res.json()
                setMessage(res.ok ? 'Подключение успешно' : `${body.message}${body.techDetail ? ` — ${body.techDetail}` : ''}`)
              } catch (err) { setMessage(String(err)) }
            }}>Проверить</button>
            <button className="btn primary" onClick={async () => {
              const res = await fetch('/api/v1/connections', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
              const body = await res.json().catch(() => ({}))
              if (!res.ok) setMessage(body.message)
              else { setMessage('Сохранено (не проверено)'); reload() }
            }}>Сохранить</button>
          </div>
          {message && <div className="muted mt8">{message}</div>}
        </div>
      </div>
    </div>
  )
}

function Agents() {
  const [list, setList] = useState<{ id: string; name: string; role: string; skillMd: string }[]>([])
  useEffect(() => { void fetch('/api/v1/agents').then((r) => r.json()).then(setList) }, [])
  return (
    <div className="set-body"><div className="agents-grid">{list.map((a) => (
        <div key={a.id} className="agent-card"><div className="flex"><b>{a.name}</b></div><div className="muted">{a.role}</div></div>
      ))}</div>
      <p className="note">Матрица назначений: вкладки типов → статусы → агенты (режим параллельно/замещение) — PUT /api/v1/matrix/&#123;type&#125;/&#123;status&#125;</p>
    </div>
  )
}

function Projects() {
  const [list, setList] = useState<{ id: string; name: string; mnemonic: string; path: string; baseBranch: string; isArchived: boolean }[]>([])
  const reload = () => void api.projects().then(() => void fetch('/api/v1/projects').then((r) => r.json()).then(setList))
  useEffect(reload, [])
  return (
    <table className="tasks mx">
      <thead><tr><th>Мнемоника</th><th>Название</th><th>Путь</th><th>Базовая ветка</th></tr></thead>
      <tbody>{list.map((p) => <tr key={p.id}><td>{p.mnemonic}</td><td>{p.name} {p.isArchived && '(архив)'}</td><td>{p.path}</td><td>{p.baseBranch}</td></tr>)}</tbody>
    </table>
  )
}

function Queue() {
  const [snap, setSnap] = useState<Awaited<ReturnType<typeof api.queue>> | null>(null)
  useEffect(() => { void api.queue().then(setSnap) }, [])
  if (!snap) return <div className="empty">Загрузка…</div>
  return (
    <div className="set-body">
      <div className="q-sec">В работе у агентов</div>
      {snap.working.map((w) => <div key={w.code} className="q-row"><span className="code">{w.code}</span><span className="q-t">{w.agent}</span><span className="muted">{w.minutes ?? 0} мин</span></div>)}
      <div className="q-sec">Ожидают</div>
      {snap.waiting.map((w) => <div key={w.code} className="q-row"><span className="code">{w.code}</span><span className="q-t">{w.status}</span><span className="muted">попыток {w.attempts}</span></div>)}
      <div className="q-sec">Заблокированы</div>
      {snap.blocked.map((b) => <div key={b.code} className="q-row"><span className="code">{b.code}</span><span className="q-t">{b.reason}</span></div>)}
    </div>
  )
}

function Journal() {
  const [rows, setRows] = useState<{ who: string; entity: string; summary: string; at: string }[]>([])
  useEffect(() => { void fetch('/api/v1/settings-journal').then((r) => r.json()).then(setRows) }, [])
  return (
    <div className="set-body">
      {rows.map((r, i) => <div key={i} className="jr-row"><time>{r.at.slice(0, 16).replace("T", " ")}</time><div className="jr-b"><b>{r.who}</b> · {r.summary}</div></div>)}
      {rows.length === 0 && <div className="empty"><b>Журнал пуст</b>правки настроек появятся здесь</div>}
    </div>
  )
}


function Matrix() {
  const [typeKey, setTypeKey] = useState('common_task')
  const [statuses, setStatuses] = useState<{ key: string; label: string }[]>([])
  const [matrix, setMatrix] = useState<Record<string, { userId: string; name: string; mode: string }[]>>({})
  const [people, setPeople] = useState<{ id: string; name: string }[]>([])
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    void api.flow(typeKey).then((f) => setStatuses(f.statuses.map((s) => ({ key: s.key, label: s.label }))))
    void api.matrix(typeKey).then((m) => setMatrix(m.matrix))
  }, [typeKey])
  useEffect(() => {
    void api.users().then((u) => setPeople(u.map((x) => ({ id: x.id, name: x.name }))))
      .catch(() => void api.agents().then((a) => setPeople(a.map((x) => ({ id: x.id, name: x.name })))))
  }, [])

  const setEntries = async (statusKey: string, entries: { userId: string; mode: string }[]) => {
    try {
      await api.setMatrix(typeKey, statusKey, entries)
      setMatrix((m) => ({ ...m, [statusKey]: entries.map((e) => ({
        userId: e.userId, name: people.find((p) => p.id === e.userId)?.name ?? '?', mode: e.mode })) }))
      setNote(null)
    } catch (err) {
      setNote((err as Error).message)
    }
  }

  return (
    <div className="set-body">
      <div className="flow-toolbar">
        <select value={typeKey} onChange={(e) => setTypeKey(e.target.value)}>
          {['story', 'common_task', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <span className="note">кто работает на каждом статусе; режимы «параллельно» / «замещение»</span>
        {note && <span className="note" style={{ color: 'var(--danger)' }}>{note}</span>}
      </div>
      <table className="tasks mx">
        <thead><tr><th>Статус</th><th>Исполнители</th></tr></thead>
        <tbody>
          {statuses.map((s) => {
            const entries = matrix[s.key] ?? []
            const mode = entries[0]?.mode ?? 'replacement'
            return (
              <tr key={s.key}>
                <td><b>{s.label}</b><br /><small>{s.key}</small></td>
                <td>
                  {entries.map((e) => (
                    <span key={e.userId} className="chip clickable" title={`${e.mode}; клик — снять`}
                      onClick={() => void setEntries(s.key, entries.filter((x) => x.userId !== e.userId)
                        .map((x, i) => ({ userId: x.userId, mode: i === 0 ? x.mode : mode })))}>
                      {e.name} · {e.mode} ✕
                    </span>
                  ))}
                  <select value="" onChange={(e) => {
                    if (!e.target.value) return
                    void setEntries(s.key, [...entries, { userId: e.target.value, mode }])
                  }}>
                    <option value="">＋ назначить…</option>
                    {people.filter((p) => !entries.some((e) => e.userId === p.id))
                      .map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <select value={mode} onChange={(e) =>
                    void setEntries(s.key, entries.map((x) => ({ userId: x.userId, mode: e.target.value })))}>
                    <option value="replacement">замещение</option>
                    <option value="parallel">параллельно</option>
                  </select>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
