// Чат Eve: контекст экрана, намерение→«да», кликабельные коды (СТ §5.6)

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'

interface Msg { role: 'user' | 'eve'; text: string }

export function EveChat({ open, setOpen, navigate }: {
  open: boolean
  setOpen: (open: boolean) => void
  navigate: (hash: string) => void
}) {
  const [messages, setMessages] = useState<Msg[]>([
    { role: 'eve', text: 'Я Eve. Спросите или дайте задание: «переведи SA-12 на ревью», «почему SA-14 встала?»' },
  ])
  const [input, setInput] = useState('')
  const [pendingIntent, setPendingIntent] = useState<{ kind: string; task: string; to: string } | null>(null)
  const screenTask = window.location.hash.match(/([A-Za-z]{2,10}-\d+)/)?.[1]?.toUpperCase()
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => { boxRef.current?.scrollTo(0, boxRef.current.scrollHeight) }, [messages])

  const send = async (text: string) => {
    if (!text.trim()) return
    setMessages((m) => [...m, { role: 'user', text }])
    setInput('')
    const res = await api.eve(text, screenTask)
    if (res.action === 'confirm' && res.intent) {
      setPendingIntent(res.intent)
      setMessages((m) => [...m, { role: 'eve', text: res.reply ?? 'Подтвердите: «да»' }])
      return
    }
    if (res.action === 'open_create_dialog') {
      setMessages((m) => [...m, { role: 'eve', text: 'Открываю диалог создания задачи…' }])
      window.dispatchEvent(new CustomEvent('eve-open-create', { detail: res }))
      return
    }
    setMessages((m) => [...m, { role: 'eve', text: res.reply ?? 'Готово.' }])
  }

  const sendConfirm = async (yes: boolean) => {
    setPendingIntent(null)
    await send(yes ? 'да' : 'отмена')
  }

  if (!open) {
    return <button className="eve-btn" onClick={() => setOpen(true)}>Eve · помощник</button>
  }
  return (
    <section className="eve-panel">
      <div className="eve-head">
        <b>Eve</b><span className="note">максимальные права, всё — с аудитом</span>
        <button className="icon-btn" onClick={() => setOpen(false)}>—</button>
      </div>
      {screenTask && <div className="eve-ctx">Контекст: <b>{screenTask}</b></div>}
      <div className="eve-msgs" ref={boxRef}>
        {messages.map((m, i) => (
          <div key={i} className={`eve-msg ${m.role}`}>
            {[...m.text.matchAll(/([A-Za-z]{2,10}-\d+)/g)].length > 0
              ? m.text.split(/([A-Za-z]{2,10}-\d+)/).map((part, j) =>
                  /([A-Za-z]{2,10}-\d+)/.test(part)
                    ? <a key={j} className="code-link" onClick={() => navigate(`#${part}`)}>{part}</a>
                    : part)
              : m.text}
          </div>
        ))}
      </div>
      {pendingIntent && (
        <div className="eve-confirm">
          <button className="btn primary" onClick={() => void sendConfirm(true)}>Да, перевести</button>
          <button className="btn" onClick={() => void sendConfirm(false)}>Отмена</button>
        </div>
      )}
      <div className="eve-chips">
        {['Почему задача встала?', 'Сводка по проекту'].map((q) => (
          <button key={q} onClick={() => void send(q)}>{q}</button>
        ))}
      </div>
      <div className="eve-input">
        <textarea rows={2} value={input} placeholder="Спросите или дайте задание… (Enter — отправить)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) } }} />
      </div>
    </section>
  )
}
