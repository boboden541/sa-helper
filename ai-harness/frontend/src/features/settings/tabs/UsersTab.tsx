// Вкладка «Пользователи»: люди системы, включатель обязательного входа,
// смена своего пароля. Раннее людей нельзя было завести ни через API, ни
// через UI (единственная учётка — сид Алексей/harness) — анализ 11.11.2026.

import { useEffect, useState } from 'react'

type Human = { id: string; name: string; createdAt: string | null }

export function Users() {
  const [users, setUsers] = useState<Human[]>([])
  const [required, setRequired] = useState(false)
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const show = (text: string, bad: boolean) => { setNote({ text, bad }) }

  const reload = () => {
    void fetch('/api/v1/auth/users')
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
      .then(setUsers)
      .catch(() => show('Не удалось загрузить список', true))
    void fetch('/api/v1/auth/required')
      .then((r) => r.json())
      .then((d: { enabled: boolean }) => setRequired(d.enabled))
      .catch(() => {})
  }
  useEffect(reload, [])

  const create = async () => {
    const res = await fetch('/api/v1/auth/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, password }),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { show(body.message || 'Не удалось создать', true); return }
    setName(''); setPassword('')
    show(`Создан: ${body.name}`, false)
    reload()
  }

  const changePassword = async () => {
    const res = await fetch('/api/v1/auth/change-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oldPassword, newPassword }),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { show(body.message || 'Не удалось сменить пароль', true); return }
    setOldPassword(''); setNewPassword('')
    show('Пароль изменён', false)
  }

  const toggleRequired = async () => {
    const res = await fetch('/api/v1/auth/required', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !required }),
    })
    if (!res.ok) { show('Не удалось переключить', true); return }
    setRequired(!required)
    show(required ? 'Обязательный вход выключен' : 'Обязательный вход включён', false)
  }

  return (
    <div className="set-body">
      <div className="q-sec">Обязательный вход</div>
      <div className="pr-row">
        <div>
          <div>{required ? 'Включён — без входа API закрыт (401)' : 'Выключен — анонимный dev-доступ от имени первого человека'}</div>
          <div className="muted">Рубильник работает и без сессии (бутстрап): включение может запереть вас на экране логина — убедитесь, что пароль известен.</div>
        </div>
        <button className={`btn small ${required ? '' : ''}`} onClick={toggleRequired}>
          {required ? 'Выключить' : 'Включить'}
        </button>
      </div>

      <div className="q-sec">Смена своего пароля</div>
      <div className="pr-row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input type="password" placeholder="текущий пароль" value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)} />
        <input type="password" placeholder="новый (мин. 6)" value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)} />
        <button className="btn small" onClick={changePassword}>Сменить</button>
      </div>

      <div className="q-sec">Люди системы</div>
      {users.map((u) => (
        <div key={u.id} className="pr-row">
          <span>{u.name}</span>
          <span className="muted">{u.createdAt ? u.createdAt.slice(0, 10) : ''}</span>
        </div>
      ))}
      <div className="pr-row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input placeholder="имя" value={name} onChange={(e) => setName(e.target.value)} />
        <input type="password" placeholder="пароль (мин. 6)" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <button className="btn small" onClick={create}>Создать</button>
      </div>

      {note && <div className={note.bad ? 'pr-note bad' : 'pr-note'} style={{ color: note.bad ? 'var(--danger)' : 'var(--ok)' }}>{note.text}</div>}
    </div>
  )
}
