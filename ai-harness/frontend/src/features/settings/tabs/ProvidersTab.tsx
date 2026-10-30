// Вкладка «ИИ-провайдеры» — prov-grid: список подключений + форма с пресетами.
// Перенесено из монолита Settings.tsx разметка 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'

export function Providers() {
  const [list, setList] = useState<{ id: string; name: string; protocol: string; url: string; model: string; tokenTail: string; checkStatus: string; isActive: boolean }[]>([])
  const [presets, setPresets] = useState<{ name: string; protocol: string; baseUrl: string }[]>([])
  const [form, setForm] = useState({ name: '', protocol: 'anthropic', url: '', model: '', token: '' })
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const reload = () => void api.requestProviders().then(setList)
  useEffect(reload, [])
  useEffect(() => {
    void fetch('/api/v1/provider-presets').then((r) => r.json()).then(setPresets)
  }, [])

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
                <button className="btn small" onClick={() => {
                  setEditingId(c.id)
                  setForm({ name: c.name, protocol: c.protocol,
                    url: c.url, model: c.model, token: '' })
                }}>Править</button>
                {!c.isActive && <button className="btn small danger" onClick={async () => {
                  if (!window.confirm(`Удалить подключение «${c.name}»?`)) return
                  const res = await fetch(`/api/v1/connections/${c.id}`, { method: 'DELETE' })
                  const body = await res.json().catch(() => ({}))
                  if (!res.ok) setMessage({ text: body.message, bad: true }); else reload()
                }}>Удалить</button>}
                {!c.isActive && <button className="btn small" onClick={async () => {
                  await fetch(`/api/v1/connections/${c.id}/activate`, { method: 'POST' }); reload()
                }}>Сделать активным</button>}
              </div>
            </div>
          ))}
          {list.length === 0 && <div className="muted">Подключений пока нет</div>}
        </div>
        <div className="prov-form">
          <div className="q-sec">Новое подключение</div>
          <div className="f-field"><label>{editingId ? `Правка подключения` : 'Название'}</label>
            <input value={form.name} disabled={Boolean(editingId)}
              onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="f-field"><label>Пресет провайдера — подставит адрес, поле остаётся редактируемым</label>
            <select value="" onChange={(e) => {
              const pr = presets.find((x) => x.name === e.target.value)
              if (pr) setForm({ ...form, protocol: pr.protocol, url: pr.baseUrl })
            }}>
              <option value="">— выбрать пресет —</option>
              {presets.map((pr) => <option key={pr.name} value={pr.name}>{pr.name}</option>)}
            </select></div>
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
                setMessage(res.ok ? { text: 'Подключение успешно', bad: false }
                  : { text: `${body.message}${body.techDetail ? ` — ${body.techDetail}` : ''}`, bad: true })
              } catch (err) { setMessage({ text: String(err), bad: true }) }
            }}>Проверить</button>
            <button className="btn primary" onClick={async () => {
              const res = editingId
                ? await fetch(`/api/v1/connections/${editingId}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
                : await fetch('/api/v1/connections', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
              const body = await res.json().catch(() => ({}))
              if (!res.ok) setMessage({ text: body.message, bad: true })
              else {
                setMessage({ text: editingId ? 'Правки сохранены' : 'Сохранено (не проверено)', bad: false })
                setForm({ name: '', protocol: form.protocol, url: '', model: '', token: '' })
                setEditingId(null); reload()
              }
            }}>Сохранить</button>
          </div>
          {message && <div className={`check-row ${message.bad ? 'err' : 'ok'}`}>{message.text}</div>}
        </div>
      </div>
    </div>
  )
}
