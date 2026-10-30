// Вкладка «Проекты» — cm-row с CRUD (правка/архив/удаление). Перенесено из
// монолита Settings.tsx разметка 1:1.

import { useEffect, useState } from 'react'

export function Projects() {
  const [list, setList] = useState<{ id: string; name: string; mnemonic: string; path: string; baseBranch: string; isArchived: boolean; description?: string }[]>([])
  const [edit, setEdit] = useState<{ id?: string; name: string; mnemonic: string; path: string; baseBranch: string; description: string } | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const reload = () => { void fetch('/api/v1/projects').then((r) => r.json()).then(setList) }
  useEffect(reload, [])

  const save = async () => {
    if (!edit) return
    const res = edit.id
      ? await fetch(`/api/v1/projects/${edit.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: edit.name, path: edit.path, baseBranch: edit.baseBranch, description: edit.description }) })
      : await fetch('/api/v1/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: edit.name, mnemonic: edit.mnemonic, path: edit.path, baseBranch: edit.baseBranch, description: edit.description }) })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setNote(null); setEdit(null); reload()
  }

  return (
    <div className="set-body">
      <div className="flow-toolbar">
        <button className="btn primary small" onClick={() => setEdit({ name: '', mnemonic: '', path: '', baseBranch: 'main', description: '' })}>＋ Проект</button>
        {note && <span className="check-row err">{note}</span>}
      </div>
      {edit && (
        <div className="agent-editor mt12">
          <div className="q-sec">{edit.id ? 'Правка проекта' : 'Новый проект'}</div>
          <div className="ag-fields">
            <div className="f-field"><label>Название</label>
              <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div className="f-field"><label>Мнемоника (2–10, A-Z0-9; неизменна)</label>
              <input value={edit.mnemonic} disabled={Boolean(edit.id)}
                onChange={(e) => setEdit({ ...edit, mnemonic: e.target.value.toUpperCase() })} /></div>
            <div className="f-field"><label>Путь на диске (репозиторий или мультирепозиторий; если папки нет — будет создана с git)</label>
              <input value={edit.path} onChange={(e) => setEdit({ ...edit, path: e.target.value })} /></div>
            <div className="f-field"><label>Базовая ветка</label>
              <input value={edit.baseBranch} onChange={(e) => setEdit({ ...edit, baseBranch: e.target.value })} /></div>
            <div className="f-field" style={{ gridColumn: '1 / -1' }}><label>Описание</label>
              <input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          </div>
          <div className="flex mt12">
            <button className="btn primary" onClick={() => void save()}>Сохранить</button>
            <button className="btn" onClick={() => setEdit(null)}>Отмена</button>
          </div>
        </div>
      )}
      <div className="col-mgr mt12">
        {list.map((p) => (
          <div key={p.id} className={`prov-row ${p.isArchived ? 'proj-arch' : ''}`}>
            <div className="pr-main">
              <b><span className="mono">{p.mnemonic}</span> · {p.name}</b>
              <div className="muted">{p.path} · ветка {p.baseBranch}{p.isArchived ? ' · в архиве' : ''}</div>
            </div>
            <div className="pr-actions">
              <button className="btn small" onClick={() => setEdit({ id: p.id, name: p.name, mnemonic: p.mnemonic, path: p.path, baseBranch: p.baseBranch, description: p.description ?? '' })}>Править</button>
              <button className="btn small" onClick={async () => {
                await fetch(`/api/v1/projects/${p.id}/archive?archived=${!p.isArchived}`, { method: 'POST' }); reload()
              }}>{p.isArchived ? 'Из архива' : 'В архив'}</button>
              <button className="btn danger small" onClick={async () => {
                const res = await fetch(`/api/v1/projects/${p.id}`, { method: 'DELETE' })
                const body = await res.json().catch(() => ({}))
                if (!res.ok) setNote(body.message); else reload()
              }}>Удалить</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
