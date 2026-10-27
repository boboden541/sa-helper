/* Реестр инструментов (вариант 4, решение владельца 27.10.2026): команды и скиллы
   глобальной папки как карточки с версиями; файлы только читаются и отслеживаются. */

import { useEffect, useState } from 'react'
import { api } from '../../api/client'

interface ToolItem {
  kind: string
  name: string
  description?: string | null
  hash: string
  status: string
  sizeBytes?: number | null
}

const STATUS_RU: Record<string, string> = {
  ok: 'актуален', changed: 'изменился на диске', missing: 'исчез с диска',
}

export function ToolsTab() {
  const [data, setData] = useState<{
    toolsDir: string
    drift: number
    counts: { commands: number; skills: number }
    items: ToolItem[]
    newOnDisk: { kind: string; name: string }[]
  } | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [viewer, setViewer] = useState<{ kind: string; name: string; content: string; changed: boolean } | null>(null)
  const [toolsDir, setToolsDir] = useState('')
  const [toolsInfo, setToolsInfo] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const reload = async () => {
    try {
      setData(await fetch('/api/v1/tools').then((r) => r.json()))
    } catch { setNote('Не удалось загрузить реестр') }
  }
  useEffect(() => { void reload() }, [])
  useEffect(() => {
    void fetch('/api/v1/agents-tools-dir').then((r) => r.json()).then((d) => {
      setToolsDir(d.toolsDir ?? '')
      setToolsInfo(d.toolsDir ? (d.found ? 'папка найдена — отслеживается' : 'папка не найдена') : '')
    }).catch(() => {})
  }, [])

  const saveToolsDir = async () => {
    const res = await fetch('/api/v1/agents-tools-dir', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolsDir: toolsDir.trim() }) })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setNote(null)
    setToolsInfo(toolsDir.trim() ? 'сохранено' : '')
    void reload()
  }

  const scan = async () => {
    const res = await fetch('/api/v1/tools/scan', { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setNote(`Скан: +${body.added} новых, ${body.updated} обновлено, −${body.removed} удалено, всего ${body.total}`)
    void reload()
  }

  const saveEdit = async () => {
    if (!viewer) return
    try {
      const res = await api.toolWrite(viewer.kind, viewer.name, draft)
      setViewer({ ...viewer, content: draft, changed: false })
      setEditing(false)
      setNote(`Файл записан, версия ${res.hash}`)
      void reload()
    } catch (err) { setNote((err as Error).message) }
  }

  const open = async (kind: string, name: string) => {
    const res = await fetch(`/api/v1/tools/${kind}/${name}`)
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setViewer(body); setEditing(false); setDraft('')
  }

  return (
    <div className="set-body">
      {note && <div className="check-row err">{note}</div>}
      <div className="agent-editor" style={{ marginBottom: 12 }}>
        <div className="ag-fields">
          <div className="f-field" style={{ gridColumn: '1 / -1' }}>
            <label>Папка инструментов — один путь на все проекты (папка .claude, куда SA-Helper установлен install.sh); подключается к работе агентов как есть, без копий</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="mono" value={toolsDir} placeholder="/Users/raaliev/…/sa-helper/.claude"
                onChange={(e) => setToolsDir(e.target.value)} />
              <button className="btn" onClick={() => void saveToolsDir()}>Сохранить</button>
            </div>
            {toolsInfo && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{toolsInfo}</div>}
          </div>
        </div>
      </div>
      {data && !data.toolsDir && (
        <div className="callout"><span className="ci">!</span>
          <div className="body">Папка не задана — укажите её выше и нажмите «Сканировать».</div></div>
      )}
      <div className="flow-toolbar">
        <div className="q-sec" style={{ margin: 0 }}>Инструменты из глобальной папки</div>
        <span className="sp" />
        {data && <span className="muted" style={{ fontSize: 12.5 }}>
          команд: {data.counts.commands} · скиллов: {data.counts.skills}
          {data.drift > 0 ? ` · расхождений с диском: ${data.drift}` : ' · синхронно с диском'}
        </span>}
        <button className="btn small" onClick={() => void scan()}>Сканировать</button>
      </div>
      {data && <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
        папка: <span className="mono">{data.toolsDir}</span> — файлы только читаются, ничего не изменяется
      </div>}
      <div className="agents-grid">
        {(data?.items ?? []).map((i) => (
          <div key={i.kind + i.name} className="agent-card">
            <div className="flex">
              <b>{i.kind === 'command' ? `/${i.name}` : i.name}</b>
              <span className="mini-chip">{i.kind === 'command' ? 'команда' : 'скилл'}</span>
              <span className="sp" />
              <span className="mini-chip" style={i.status !== 'ok'
                ? { color: 'var(--danger)', borderColor: 'var(--danger)' } : undefined}>
                {STATUS_RU[i.status] ?? i.status} · {i.hash}
              </span>
              <button className="link" style={{ fontSize: 12 }} onClick={() => void open(i.kind, i.name)}>открыть</button>
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
              {(i.description ?? '').slice(0, 160) || '— без описания —'}
            </div>
          </div>
        ))}
        {data && data.newOnDisk.length > 0 && data.newOnDisk.map((n) => (
          <div key={'new' + n.kind + n.name} className="agent-card" style={{ opacity: 0.6 }}>
            <div className="flex">
              <b>{n.kind === 'command' ? `/${n.name}` : n.name}</b>
              <span className="mini-chip" style={{ color: 'var(--warn, #d90)' }}>новое на диске — просканируйте</span>
            </div>
          </div>
        ))}
      </div>
      {viewer && (
        <div className="modal" onClick={() => setViewer(null)}>
          <div className="modal-card" style={{ width: 'min(900px, 92vw)' }} onClick={(e) => e.stopPropagation()}>
            <div className="blk-h"><h3 style={{ fontSize: 15 }}>
              {viewer.kind === 'command' ? `/${viewer.name}` : viewer.name}
              {viewer.changed && <span className="mini-chip" style={{ marginLeft: 8, color: 'var(--danger)' }}>изменился на диске</span>}
            </h3></div>
            {editing ? (
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} className="mono"
                style={{ width: '100%', minHeight: '50vh', fontSize: 12.5 }} />
            ) : (
              <pre className="mono" style={{ maxHeight: '60vh', overflow: 'auto', fontSize: 12.5,
                whiteSpace: 'pre-wrap' }}>{viewer.content}</pre>
            )}
            <div className="edit-actions">
              {editing ? (
                <>
                  <button className="btn" onClick={() => setEditing(false)}>Отмена</button>
                  <button className="btn primary" onClick={() => void saveEdit()}>Сохранить в файл</button>
                </>
              ) : (
                <>
                  <button className="btn" disabled={viewer.changed}
                    title={viewer.changed ? 'Файл изменился на диске — просканируйте реестр и откройте заново' : ''}
                    onClick={() => { setDraft(viewer.content); setEditing(true) }}>Редактировать</button>
                  <button className="btn" onClick={() => setViewer(null)}>Закрыть</button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
