// Чеклисты: визуальный режим (статусы-бейджи, инлайн-правка) и текстовый
// IDE-режим с `- ~ x + !` (ФТ-ah-9; эталон design_mockup/app.js:529-555).

import { useEffect, useState } from 'react'
import { parseChecklist, serializeChecklist, type ChecklistLine } from '../../shared/checklist'

interface Item { position: number; kind: string; text: string; status: string; level?: number }

export function ChecklistBlock({ code, kind, title }: { code: string; kind: string; title: string }) {
  const [lines, setLines] = useState<ChecklistLine[]>([])
  const [textMode, setTextMode] = useState(false)
  const [draft, setDraft] = useState('')
  const [newLine, setNewLine] = useState('')

  const reload = () => {
    // пункты приходят агрегатом карточки; для этапа читаем через PSI-подобный контракт чеклистов
    void fetch(`/api/v1/tasks/${code}/checklists/${kind}`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setLines((d.items ?? []).map((i: Item) => i.kind === 'heading'
        ? { kind: 'heading', level: i.level ?? 1, text: i.text }
        : { kind: 'item', text: i.text, status: i.status as ChecklistLine['status'] })))
  }
  useEffect(reload, [code, kind])

  const save = async (lines: ChecklistLine[]) => {
    setLines(lines)
    await fetch(`/api/v1/tasks/${code}/checklists/${kind}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines: serializeChecklist(lines) }),
    })
  }

  const closed = lines.filter((l) => l.kind === 'item' && ['done', 'closed'].includes(l.status ?? '')).length
  const total = lines.filter((l) => l.kind === 'item').length

  return (
    <section className="block">
      <h3>{title} <span className="progress">{closed}/{total}</span>
        <button className="pencil" onClick={() => { setDraft(serializeChecklist(lines)); setTextMode(!textMode) }}>✎ текст</button>
      </h3>
      {textMode ? (
        <textarea className="cl-edit" rows={Math.max(4, lines.length + 1)} value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => { void save(parseChecklist(draft)); setTextMode(false) }} />
      ) : (
        <div className="cl-visual">
          {lines.map((l, idx) => (
            <div key={idx} className={`cl-row ${l.kind}`}>
              {l.kind === 'item' && (
                <select value={l.status} onChange={(e) => {
                  const next = [...lines]
                  next[idx] = { ...l, status: e.target.value as ChecklistLine['status'] }
                  void save(next)
                }}>
                  {['todo', 'in_progress', 'closed', 'done', 'failed'].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              )}
              {l.kind === 'heading' ? <b>{'#'.repeat(l.level ?? 1)} {l.text}</b> : <span>{l.text}</span>}
              <button className="x" onClick={() => void save(lines.filter((_, i) => i !== idx))}>✕</button>
            </div>
          ))}
          <input placeholder="Новый пункт (Enter)…" value={newLine}
            onChange={(e) => setNewLine(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newLine.trim()) {
                const parsed = parseChecklist(newLine)
                void save([...lines, ...parsed])
                setNewLine('')
              }
            }} />
        </div>
      )}
    </section>
  )
}
