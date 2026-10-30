// Вкладка «Агенты и матрица» — agents-grid + agent-editor (скиллы, tools_dir, MCP)
// и матрица назначений table.mx с ag-cell/AgCellPopover. Перенесено из монолита
// Settings.tsx разметка 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { toast } from '../../../shared/toast'
import { FLOW_TYPES } from '../shared'

export function AgentsAndMatrix() {
  const [agents, setAgents] = useState<{ id: string; name: string; role: string; connectionId: string; isPreset: boolean; model: string; allowedTools: string[]; mcpServers: Record<string, unknown> | null; agentDir: string; skills: string[] }[]>([])
  const [users, setUsers] = useState<{ id: string; name: string; userType: string }[]>([])
  const [editor, setEditor] = useState<{ id?: string; name: string; role: string; model: string; tools: string; mcpJson: string; agentDir: string; skills: string[] } | null>(null)
  const [regSkills, setRegSkills] = useState<{ name: string; status: string }[]>([])
  const [note, setNote] = useState<string | null>(null)
    const reload = async () => {
    void fetch('/api/v1/tools').then((r) => r.json()).then((d) => setRegSkills(
      (d.items ?? []).filter((i: { kind: string }) => i.kind === 'skill').map(
        (i: { name: string; status: string }) => ({ name: i.name, status: i.status })))).catch(() => {})
    setAgents(await api.agents())
    setUsers(await api.users())
  }
  useEffect(() => { void reload() }, [])


  const clone = async (id: string) => {
    const res = await fetch(`/api/v1/agents/${id}/clone`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) setNote(body.message)
    else { toast(`Клонирован: ${body.name}`, 'ok'); void reload() }
  }
  const remove = async (id: string, name: string) => {
    const res = await fetch(`/api/v1/agents/${id}`, { method: 'DELETE' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) setNote(body.message)
    else { toast(`Агент ${name} удалён`, 'ok'); void reload() }
  }
  const saveEditor = async () => {
    if (!editor) return
    let mcp: Record<string, unknown> | null = null
    if (editor.mcpJson.trim()) {
      try { mcp = JSON.parse(editor.mcpJson) } catch { setNote('MCP-серверы: некорректный JSON'); return }
    }
    const payload = { name: editor.name, role: editor.role,
      model: editor.model, allowedTools: editor.tools.split(/[\s,]+/).filter(Boolean),
      mcpServers: mcp, agentDir: editor.agentDir.trim(), skills: editor.skills }
    const res = editor.id
      ? await fetch(`/api/v1/agents/${editor.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload) })
      : await fetch('/api/v1/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload) })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setEditor(null); setNote(null); void reload()
  }

  return (
    <div className="set-body">
      {note && <div className="check-row err">{note}</div>}
      <div className="flow-toolbar">
        <div className="q-sec" style={{ margin: 0 }}>Пользователи-агенты</div>
        <span className="sp" />
        <button className="btn primary small" onClick={() => setEditor({
          name: '', role: '',
          model: '', tools: '', mcpJson: '', agentDir: '', skills: [] })}>＋ Агент</button>
      </div>
      <div className="agents-grid">
        {agents.map((a) => (
          <div key={a.id} className="agent-card">
            <div className="flex">
              <span className="eve-ava" style={{ background: 'var(--surface3)', color: 'var(--text2)' }}>{a.name.slice(0, 1)}</span>
              <b>{a.name}</b>
              {a.isPreset && <span className="mini-chip">предустановленный</span>}
              <span className="sp" />
              <button className="link" style={{ fontSize: 12 }} onClick={() => setEditor({ id: a.id, name: a.name, role: a.role, model: a.model ?? '', tools: (a.allowedTools ?? []).join(', '), mcpJson: a.mcpServers ? JSON.stringify(a.mcpServers, null, 2) : '', agentDir: a.agentDir ?? '', skills: a.skills ?? [] })}>править</button>
              <span className="muted">·</span>
              <button className="link" style={{ fontSize: 12 }} onClick={() => void clone(a.id)}>клонировать</button>
              <span className="muted">·</span>
              <button className="link" style={{ fontSize: 12, color: 'var(--danger)' }} onClick={() => void remove(a.id, a.name)}>удалить</button>
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>{a.role}</div>
            <div className="flex mt8" style={{ flexWrap: 'wrap' }}>
              <span className="mini-chip">{a.connectionId ? 'своё подключение' : 'активное подключение'}</span>
              {a.model && <span className="mini-chip">модель: {a.model}</span>}
              {a.agentDir && <span className="mini-chip">папка скиллов</span>}
              {!!a.skills?.length && <span className="mini-chip">скиллы: {a.skills.join(', ')}</span>}
              {a.mcpServers && <span className="mini-chip">MCP: {Object.keys(a.mcpServers).length}</span>}
              {!!a.allowedTools?.length && <span className="mini-chip">инструменты: {a.allowedTools.length}</span>}
            </div>
          </div>
        ))}
      </div>
      {editor && (
        <div className="agent-editor mt12">
          <div className="q-sec">{editor.id ? 'Правка агента' : 'Новый агент'}</div>
          <div className="ag-fields">
            <div className="f-field"><label>Название</label>
              <input value={editor.name} onChange={(e) => setEditor({ ...editor, name: e.target.value })} /></div>
            <div className="f-field"><label>Роль (за что отвечает)</label>
              <input value={editor.role} onChange={(e) => setEditor({ ...editor, role: e.target.value })} /></div>
            <div className="f-field"><label>Модель прогона (необязательно — иначе модель подключения)</label>
              <input value={editor.model} placeholder="например glm-5.3-flash"
                onChange={(e) => setEditor({ ...editor, model: e.target.value })} /></div>
            <div className="f-field"><label>Инструменты через запятую (пусто — стандартный набор: Read, Grep, Glob, Edit, Write, Bash)</label>
              <input value={editor.tools} placeholder="Read, Edit, Bash"
                onChange={(e) => setEditor({ ...editor, tools: e.target.value })} /></div>

            <div className="f-field" style={{ gridColumn: '1 / -1' }}>
              <label>Скиллы из реестра (подключаются к прогону явно; пусто — агент сам найдёт скиллы в папке инструментов)</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {regSkills.map((s) => (
                  <span key={s.name} className="mini-chip" style={{ cursor: 'pointer' }}
                    onClick={() => setEditor({ ...editor, skills: editor.skills.includes(s.name)
                      ? editor.skills.filter((x) => x !== s.name)
                      : [...editor.skills, s.name] })}>
                    {editor.skills.includes(s.name) ? '✓ ' : ''}{s.name}
                  </span>
                ))}
                {regSkills.length === 0 && <span className="muted" style={{ fontSize: 12 }}>
                  Реестр пуст — просканируйте папку в «Настройки → Инструменты»</span>}
              </div>
            </div>
            <div className="f-field" style={{ gridColumn: '1 / -1' }}>
              <label>Папка агентов на вашем компьютере (необязательно) — подключается к работе агента без копий: скиллы, команды, субагенты. Если пусто — берётся глобальная папка инструментов</label>
              <input className="mono" value={editor.agentDir} placeholder="/Users/raaliev/…/sa-helper/.claude"
                onChange={(e) => setEditor({ ...editor, agentDir: e.target.value })} /></div>
            <div className="f-field" style={{ gridColumn: '1 / -1' }}>
              <label>MCP-серверы — JSON (необязательно), например {'{"graph": {"type": "http", "url": "http://host.docker.internal:8000/mcp"}}'} (пусто — без MCP)</label>
              <textarea rows={3} className="mono" value={editor.mcpJson}
                onChange={(e) => setEditor({ ...editor, mcpJson: e.target.value })} /></div>
          </div>
          <div className="flex mt12">
            <button className="btn primary" onClick={() => void saveEditor()}>Сохранить</button>
            <button className="btn" onClick={() => setEditor(null)}>Отмена</button>
          </div>
        </div>
      )}

      <Matrix agentsAndUsers={users} />
    </div>
  )
}

function Matrix({ agentsAndUsers }: { agentsAndUsers: { id: string; name: string; userType: string }[] }) {
  const [typeKey, setTypeKey] = useState('common_task')
  const [statuses, setStatuses] = useState<{ key: string; label: string; stageDesc?: string }[]>([])
  const [matrix, setMatrix] = useState<Record<string, { userId: string; name: string; mode: string }[]>>({})
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    void api.flow(typeKey).then((f) => setStatuses(f.statuses.map((s) => ({ key: s.key, label: s.label, stageDesc: s.stageDesc }))))
    void api.matrix(typeKey).then((m) => setMatrix(m.matrix))
  }, [typeKey])

  const setEntries = async (statusKey: string, entries: { userId: string; mode: string }[]) => {
    try {
      await api.setMatrix(typeKey, statusKey, entries)
      setMatrix((m) => ({ ...m, [statusKey]: entries.map((e) => ({
        userId: e.userId, name: agentsAndUsers.find((p) => p.id === e.userId)?.name ?? '?', mode: e.mode })) }))
      setNote(null)
    } catch (err) { setNote((err as Error).message) }
  }

  return (
    <>
      <div className="q-sec" style={{ marginTop: 24 }}>Матрица назначений — кто работает на каждом статусе</div>
      <div className="flow-toolbar">
        <div className="seg">
          {FLOW_TYPES.map(([k, l]) => (
            <button key={k} className={typeKey === k ? 'active' : ''} onClick={() => setTypeKey(k)}>{l}</button>
          ))}
        </div>
        <span className="muted">несколько агентов — «параллельно» или «замещение»</span>
        {note && <span className="check-row err">{note}</span>}
      </div>
      <table className="tasks mx">
        <thead><tr><th className="mx-c1">Статус</th><th>Что происходит</th><th className="mx-c3">Агенты</th><th className="mx-c4">Режим</th></tr></thead>
        <tbody>
          {statuses.map((s) => {
            const entries = matrix[s.key] ?? []
            const mode = entries[0]?.mode ?? 'replacement'
            return (
              <tr key={s.key}>
                <td><b>{s.label}</b><br /><span className="muted mono" style={{ fontSize: 10 }}>{s.key}</span></td>
                <td className="muted">{s.stageDesc ?? ''}</td>
                <td>
                  <div className="ag-cell">
                    {entries.map((e) => (
                      <span key={e.userId} className="mini-chip" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                        {e.name}
                        <button title="Снять назначение" style={{ color: 'inherit' }}
                          onClick={() => void setEntries(s.key, entries.filter((x) => x.userId !== e.userId))}>✕</button>
                      </span>
                    ))}
                    <AgCellPopover statusKey={s.key} people={agentsAndUsers} entries={entries}
                      defaultMode={mode} onApply={(next) => void setEntries(s.key, next)} />
                  </div>
                </td>
                <td>
                  <select value={mode} onChange={(e) =>
                    void setEntries(s.key, entries.map((x) => ({ userId: x.userId, mode: e.target.value })))}
                    disabled={entries.length === 0}>
                    <option value="replacement">замещение</option>
                    <option value="parallel">параллельно</option>
                  </select>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

function AgCellPopover({ statusKey, people, entries, defaultMode, onApply }: {
  statusKey: string
  people: { id: string; name: string; userType: string }[]
  entries: { userId: string; name: string; mode: string }[]
  defaultMode: string
  onApply: (entries: { userId: string; mode: string }[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Record<string, boolean>>(
    Object.fromEntries(entries.map((e) => [e.userId, true])))

  return (
    <span style={{ position: 'relative' }}>
      <button className="btn small" onClick={() => setOpen(!open)}>＋ назначить</button>
      {open && (
        <div className="ag-pop" onClick={(e) => e.stopPropagation()}>
          {people.map((p) => (
            <label key={p.id} className="f-check" style={{ display: 'flex' }}>
              <input type="checkbox" checked={Boolean(picked[p.id])}
                onChange={(e) => setPicked((prev) => ({ ...prev, [p.id]: e.target.checked }))} />
              {p.name} <span className="muted">({p.userType === 'agent' ? 'агент' : 'человек'})</span>
            </label>
          ))}
          <div className="edit-actions">
            <button className="btn small primary" onClick={() => {
              onApply(Object.entries(picked).filter(([, on]) => on)
                .map(([userId], i) => ({ userId, mode: defaultMode })))
              setOpen(false)
            }}>Применить</button>
            <button className="btn small" onClick={() => setOpen(false)}>Отмена</button>
          </div>
          <div className="muted" style={{ fontSize: 11 }}>Статус: {statusKey}</div>
        </div>
      )}
    </span>
  )
}
