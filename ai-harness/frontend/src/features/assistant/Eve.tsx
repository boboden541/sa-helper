// Eve — design_mockup (итерация 13) + перетаскивание/масштабирование панели
// и markdown-ответы (решение владельца 28.10.2026).

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { renderMarkdown } from '../../shared/markdown'

interface Msg { role: 'user' | 'eve'; text: string; intent?: { kind: string; task: string; to: string } }
interface PanelGeom { left: number; top: number; width: number; height: number }

const GEOM_KEY = 'eve-panel-geom'
const MIN_W = 340
const MIN_H = 380

function loadGeom(): PanelGeom | null {
  try {
    const raw = localStorage.getItem(GEOM_KEY)
    const g = raw ? JSON.parse(raw) : null
    return g && typeof g.left === 'number' ? g : null
  } catch { return null }
}

// коды задач в HTML → кликабельные (только в текстовых узлах, не в атрибутах)
function linkifyCodes(html: string): string {
  return html.split(/(<[^>]*>)/).map((seg) => seg.startsWith('<')
    ? seg
    : seg.replace(/\b([A-ZА-ЯЁ]{2,10}-\d+)\b/g,
        '<span class="code" data-code="$1">$1</span>')).join('')
}

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
  // живой процесс формирования ответа (решение владельца 28.10.2026)
  const [stream, setStream] = useState<{ status: string; text: string } | null>(null)
  const [geom, setGeom] = useState<PanelGeom | null>(loadGeom)
  const boxRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLElement>(null)
  const screenTask = window.location.hash.match(/([A-Za-z]{2,10}-\d+)/)?.[1]?.toUpperCase()

  useEffect(() => { boxRef.current?.scrollTo(0, boxRef.current.scrollHeight) }, [messages, stream])

  const persist = (g: PanelGeom) => {
    setGeom(g)
    try { localStorage.setItem(GEOM_KEY, JSON.stringify(g)) } catch { /* приватный режим */ }
  }

  // перетаскивание панели за шапку
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)
  const onHeadDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const rect = panelRef.current?.getBoundingClientRect()
    if (!rect) return
    dragRef.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top }
    if (!geom) persist({ left: rect.left, top: rect.top, width: rect.width, height: rect.height })
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onHeadMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return
    const left = Math.min(Math.max(e.clientX - dragRef.current.dx, 8), window.innerWidth - 120)
    const top = Math.min(Math.max(e.clientY - dragRef.current.dy, 8), window.innerHeight - 80)
    persist({ ...(geom ?? { width: MIN_W, height: MIN_H, left: 0, top: 0 }), left, top })
  }
  const onHeadUp = () => { dragRef.current = null }

  // масштабирование за уголок
  const resizeRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null)
  const onResizeDown = (e: React.PointerEvent) => {
    const rect = panelRef.current?.getBoundingClientRect()
    if (!rect) return
    resizeRef.current = { x: e.clientX, y: e.clientY, w: rect.width, h: rect.height }
    if (!geom) persist({ left: rect.left, top: rect.top, width: rect.width, height: rect.height })
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onResizeMove = (e: React.PointerEvent) => {
    if (!resizeRef.current) return
    const r = resizeRef.current
    const width = Math.min(Math.max(r.w + (e.clientX - r.x), MIN_W), window.innerWidth - 16)
    const height = Math.min(Math.max(r.h + (e.clientY - r.y), MIN_H), window.innerHeight - 90)
    persist({ ...(geom ?? { left: 20, top: 0, width, height }), width, height })
  }
  const onResizeUp = () => { resizeRef.current = null }

  // клик по коду задачи в ответе → перейти к карточке
  const onBubbleClick = (e: React.MouseEvent) => {
    const el = (e.target as HTMLElement).closest('[data-code]')
    if (el) navigate(`#${el.getAttribute('data-code')}`)
  }

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
      <section className={`eve-panel ${open ? 'show' : ''}`} aria-label="Чат с Eve"
        ref={panelRef}
        style={geom ? { left: geom.left, top: geom.top, right: 'auto', bottom: 'auto',
                        width: geom.width, height: geom.height } : undefined}>
        <div className="eve-head" onPointerDown={onHeadDown} onPointerMove={onHeadMove}
          onPointerUp={onHeadUp} title="Перетащите за шапку; уголок справа снизу — размер">
          <span className="eve-ava">E</span>
          <div className="t"><b>Eve</b><span>максимальные права, всё — с аудитом</span></div>
          <button className="icon-btn" aria-label="Свернуть чат" onClick={() => setOpen(false)}>—</button>
        </div>
        <div className="eve-ctx">
          Контекст: <b>{screenTask ?? 'доска'}</b><span className="note">— вижу, какой экран открыт</span>
        </div>
        <div className="eve-msgs" ref={boxRef} onClick={onBubbleClick}>
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role === 'user' ? 'me' : 'eve'}`}>
              {m.role === 'user'
                ? renderText(m.text)
                : <div className="bub md">
                    <div dangerouslySetInnerHTML={{ __html: linkifyCodes(renderMarkdown(m.text)) }} />
                    {m.intent && (
                      <div className="intent">
                        <div className="ih">Намерение</div>
                        {m.intent.task
                          ? <>Задача {m.intent.task}{m.intent.to ? <> → «{m.intent.to}»</> : null}</>
                          : null}
                        <div className="ia">
                          <button className="btn primary small" onClick={() => void confirmIntent(m.intent, true)}>Да, выполнить</button>
                          <button className="btn small" onClick={() => void confirmIntent(m.intent, false)}>Отмена</button>
                        </div>
                      </div>
                    )}
                  </div>}
            </div>
          ))}
          {stream && (
            <div className="msg eve">
              <div className="bub md live-bub">
                <div className="live-status">
                  <span className="dot pulse" style={{ background: '#25935b' }} /> {stream.status || 'формирую ответ…'}
                </div>
                {stream.text && (
                  <div className="live-text"
                    dangerouslySetInnerHTML={{ __html: linkifyCodes(renderMarkdown(stream.text)) }} />
                )}
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
        <span className="eve-resize" aria-label="Изменить размер"
          onPointerDown={onResizeDown} onPointerMove={onResizeMove} onPointerUp={onResizeUp} />
      </section>
    </>
  )
}
