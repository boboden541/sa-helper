// Eve — design_mockup (итерация 13): кнопка справа снизу, панель .eve-panel.show,
// .msg.eve .bub / .msg.me, карточка намерения .intent, chips, textarea-ввод.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'

interface Msg { role: 'user' | 'eve'; text: string; intent?: { kind: string; task: string; to: string } }

export function EveChat({ open, setOpen, navigate, onOpenCreate }: {
  open: boolean
  setOpen: (open: boolean) => void
  navigate: (hash: string) => void
  onOpenCreate: () => void
}) {
  const [messages, setMessages] = useState<Msg[]>([
    { role: 'eve', text: 'Я Eve. Спросите или дайте задание: «переведи AH-3 на ревью», «почему AH-8 встала?», «создай задачу «Название»».' },
  ])
  const [input, setInput] = useState('')
  // живой процесс формирования ответа (решение владельца 28.10.2026):
  // что делает агент прямо сейчас + накапливающийся текст ответа
  const [stream, setStream] = useState<{ status: string; text: string } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const screenTask = window.location.hash.match(/([A-Za-z]{2,10}-\d+)/)?.[1]?.toUpperCase()

  useEffect(() => { boxRef.current?.scrollTo(0, boxRef.current.scrollHeight) }, [messages])

  const renderText = (text: string) =>
    text.split(/([A-Za-z]{2,10}-\d+)/).map((part, i) =>
      /^[A-Za-z]{2,10}-\d+$/.test(part)
        ? <span key={i} className="code" onClick={() => navigate(`#${part}`)}>{part}</span>
        : <span key={i}>{part}</span>)

  const send = async (text: string) => {
    if (!text.trim()) return
    setMessages((m) => [...m, { role: 'user', text }])
    setInput('')
    setStream({ status: 'формирую ответ…', text: '' })
    const finalize = (final: { reply?: string; action?: string; intent?: { kind: string; task: string; to: string } }) => {
      setStream(null)
      if (final.action === 'confirm' && final.intent) {
        setMessages((m) => [...m, { role: 'eve', text: final.reply ?? 'Подтвердите: «да»', intent: final.intent }])
        return
      }
      if (final.action === 'open_create_dialog') {
        setMessages((m) => [...m, { role: 'eve', text: 'Открываю диалог создания — название подставлено.' }])
        onOpenCreate()
        return
      }
      setMessages((m) => [...m, { role: 'eve', text: final.reply ?? 'Готово.' }])
    }
    try {
      const res = await fetch('/api/v1/assistant/messages/stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ text, screenTaskCode: screenTask }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      let final: Parameters<typeof finalize>[0] | null = null
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const ev = JSON.parse(line.slice(5)) as {
            type: string; detail?: string; text?: string
            reply?: string; action?: string; intent?: { kind: string; task: string; to: string }
          }
          if (ev.type === 'progress') setStream((s) => ({ status: ev.detail ?? '', text: s?.text ?? '' }))
          else if (ev.type === 'delta') setStream((s) => ({ status: s?.status ?? '', text: (s?.text ?? '') + (ev.text ?? '') }))
          else if (ev.type === 'done') final = ev
        }
      }
      finalize(final ?? { reply: 'Поток оборвался без ответа.' })
    } catch (err) {
      setStream(null)
      setMessages((m) => [...m, { role: 'eve', text: `Связь с Eve оборвалась: ${String(err).slice(0, 120)}` }])
    }
  }

  const confirmIntent = async (intent: { kind: string; task: string; to: string } | undefined, yes: boolean) => {
    setMessages((m) => m.filter((x) => !x.intent))
    await send(yes ? 'да' : 'отмена')
  }

  return (
    <>
      {!open && (
        <button className="eve-btn" onClick={() => setOpen(true)}>
          <span className="eve-ava">E</span> Eve · помощник
        </button>
      )}
      <section className={`eve-panel ${open ? 'show' : ''}`} aria-label="Чат с Eve">
        <div className="eve-head">
          <span className="eve-ava">E</span>
          <div className="t"><b>Eve</b><span>максимальные права, всё — с аудитом</span></div>
          <button className="icon-btn" aria-label="Свернуть чат" onClick={() => setOpen(false)}>—</button>
        </div>
        <div className="eve-ctx">
          Контекст: <b>{screenTask ?? 'доска'}</b><span className="note">— вижу, какой экран открыт</span>
        </div>
        <div className="eve-msgs" ref={boxRef}>
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role === 'user' ? 'me' : 'eve'}`}>
              {m.role === 'user'
                ? renderText(m.text)
                : <div className="bub">
                    {renderText(m.text)}
                    {m.intent && (
                      <div className="intent">
                        <div className="ih">Намерение</div>
                        Перевести {m.intent.task} → «{m.intent.to}»
                        <div className="ia">
                          <button className="btn primary small" onClick={() => void confirmIntent(m.intent, true)}>Да, перевести</button>
                          <button className="btn small" onClick={() => void confirmIntent(m.intent, false)}>Отмена</button>
                        </div>
                      </div>
                    )}
                  </div>}
            </div>
          ))}
          {stream && (
            <div className="msg eve">
              <div className="bub live-bub">
                <div className="live-status">
                  <span className="dot pulse" style={{ background: '#25935b' }} /> {stream.status || 'формирую ответ…'}
                </div>
                {stream.text && <div className="live-text">{renderText(stream.text)}</div>}
              </div>
            </div>
          )}
        </div>
        <div className="eve-chips">
          <button onClick={() => void send('Почему задача встала?')}>Почему встала?</button>
          <button onClick={() => void send('Сводка по проекту')}>Сводка по проекту</button>
        </div>
        <div className="eve-input">
          <textarea rows={2} placeholder="Спросите или дайте задание… (Enter — отправить)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) }
            }} />
          <button aria-label="Отправить" onClick={() => void send(input)}>
            <svg width="14" height="14" viewBox="0 0 16 16"><path d="M2 8L14 2 9.5 14 7.5 9.5 2 8z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
          </button>
        </div>
      </section>
    </>
  )
}
