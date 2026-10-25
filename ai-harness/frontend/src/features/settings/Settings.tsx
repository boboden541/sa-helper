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

const TABS = ['flow', 'providers', 'agents', 'projects', 'queue', 'journal'] as const

export function Settings({ reload }: { reload: () => void }) {
  const tab = useSettingsTab()
  return (
    <div className="settings">
      <div className="seg">
        {TABS.map((t) => <TabButton key={t} tab={t} />)}
      </div>
      {tab === 'flow' && <FlowEditor reload={reload} />}
      {tab === 'providers' && <Providers />}
      {tab === 'agents' && <Agents />}
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
  return (
    <button className={current === tab ? 'active' : ''}
      onClick={() => { window.location.hash = `#settings/${tab}` }}>{tab}</button>
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
    <div className="flow-editor">
      <div className="toolbar">
        <select value={typeKey} onChange={(e) => setTypeKey(e.target.value)}>
          {['story', 'common_task', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <span className="chip">версия v{data.version}{data.isPublished ? '' : ' (черновик)'}</span>
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
      <div className="flow-split">
        <div className="flow-graph" style={{ height: 420 }}>
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
        <table className="flow-table">
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
    <div className="providers">
      <h3>Подключения</h3>
      <table className="tasklist">
        <thead><tr><th>Название</th><th>Протокол</th><th>Модель</th><th>Токен</th><th>Проверка</th><th></th></tr></thead>
        <tbody>
          {list.map((c) => (
            <tr key={c.id}>
              <td>{c.name}{c.isActive && <b> · активное</b>}</td>
              <td>{c.protocol}</td><td>{c.model}</td><td>{c.tokenTail}</td><td>{c.checkStatus}</td>
              <td>
                {!c.isActive && <button className="btn small" onClick={async () => {
                  await fetch(`/api/v1/connections/${c.id}/activate`, { method: 'POST' }); reload()
                }}>Сделать активным</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Новое подключение</h3>
      <div className="form">
        <input placeholder="название" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
          <option value="anthropic">Anthropic</option>
          <option value="openai">OpenAI-совместимый</option>
        </select>
        <input placeholder="URL" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
        <input placeholder="модель" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
        <input placeholder="API-токен" type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} />
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
        {message && <span className="note">{message}</span>}
      </div>
    </div>
  )
}

function Agents() {
  const [list, setList] = useState<{ id: string; name: string; role: string; skillMd: string }[]>([])
  useEffect(() => { void fetch('/api/v1/agents').then((r) => r.json()).then(setList) }, [])
  return (
    <div className="agents">
      <h3>Пользователи-агенты</h3>
      <table className="tasklist">
        <thead><tr><th>Имя</th><th>Роль</th></tr></thead>
        <tbody>{list.map((a) => <tr key={a.id}><td>{a.name}</td><td>{a.role}</td></tr>)}</tbody>
      </table>
      <p className="note">Матрица назначений: вкладки типов → статусы → агенты (режим параллельно/замещение) — PUT /api/v1/matrix/&#123;type&#125;/&#123;status&#125;</p>
    </div>
  )
}

function Projects() {
  const [list, setList] = useState<{ id: string; name: string; mnemonic: string; path: string; baseBranch: string; isArchived: boolean }[]>([])
  const reload = () => void api.projects().then(() => void fetch('/api/v1/projects').then((r) => r.json()).then(setList))
  useEffect(reload, [])
  return (
    <table className="tasklist">
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
    <div className="queue">
      <h3>В работе у агентов</h3>
      {snap.working.map((w) => <div key={w.code}>{w.code} — {w.agent} · {w.minutes ?? 0} мин</div>)}
      <h3>Ожидают</h3>
      {snap.waiting.map((w) => <div key={w.code}>{w.code} · попыток {w.attempts}</div>)}
      <h3>Заблокированы</h3>
      {snap.blocked.map((b) => <div key={b.code}>{b.code} — {b.reason}</div>)}
    </div>
  )
}

function Journal() {
  const [rows, setRows] = useState<{ who: string; entity: string; summary: string; at: string }[]>([])
  useEffect(() => { void fetch('/api/v1/settings-journal').then((r) => r.json()).then(setRows) }, [])
  return (
    <div className="journal">
      {rows.map((r, i) => <div key={i} className="chron-row"><b>{r.who}</b> · {r.entity} · {r.summary} · <small>{r.at}</small></div>)}
      {rows.length === 0 && <div className="empty">Журнал пуст</div>}
    </div>
  )
}
