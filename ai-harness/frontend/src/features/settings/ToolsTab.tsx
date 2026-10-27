/* Реестр инструментов (вариант 4, решение владельца 27.10.2026): команды и скиллы
   глобальной папки как карточки с версиями; файлы только читаются и отслеживаются. */

import { useEffect, useState } from 'react'

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

  const reload = async () => {
    try {
      setData(await fetch('/api/v1/tools').then((r) => r.json()))
    } catch { setNote('Не удалось загрузить реестр') }
  }
  useEffect(() => { void reload() }, [])

  const scan = async () => {
    const res = await fetch('/api/v1/tools/scan', { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setNote(`Скан: +${body.added} новых, ${body.updated} обновлено, −${body.removed} удалено, всего ${body.total}`)
    void reload()
  }

  const open = async (kind: string, name: string) => {
    const res = await fetch(`/api/v1/tools/${kind}/${name}`)
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setViewer(body)
  }

  if (data && !data.toolsDir) {
    return (
      <div className="set-body">
        <div className="callout"><span className="ci">!</span>
          <div className="body">Глобальная папка инструментов не задана — укажите её во вкладке
            «Агенты и матрица», затем нажмите «Сканировать».</div></div>
      </div>
    )
  }

  return (
    <div className="set-body">
      {note && <div className="check-row err">{note}</div>}
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
            <pre className="mono" style={{ maxHeight: '60vh', overflow: 'auto', fontSize: 12.5,
              whiteSpace: 'pre-wrap' }}>{viewer.content}</pre>
            <div className="edit-actions">
              <button className="btn" onClick={() => setViewer(null)}>Закрыть</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
