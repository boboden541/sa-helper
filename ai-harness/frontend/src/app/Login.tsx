// Экран входа по локальной учётной записи (ФТ-ah-73; единый отказ без раскрытия)

import { useState } from 'react'
import { api } from '../api/client'

export function Login({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    try {
      await api.login(name, password)
      onDone()
    } catch (err) {
      setError((err as Error).message)  // «Неверное имя или пароль» — без деталей
    }
  }

  return (
    <div className="login-scrim">
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); void submit() }}>
        <h2><span className="logo-mark">A</span> AI-Harness — вход</h2>
        {error && <div className="login-err">{error}</div>}
        <div className="f-field"><label>Имя</label>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></div>
        <div className="f-field"><label>Пароль</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        <button className="btn primary" type="submit">Войти</button>
      </form>
    </div>
  )
}
