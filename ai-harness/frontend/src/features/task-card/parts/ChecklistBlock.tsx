// Чеклисты (.cl): cbx-циклы статусов, .badge с цветом, cl-x, заголовки cl-h,
// текстовый режим .cl-text (markdown со статусами `- ~ x + !`). Экспортировался
// из TaskView.tsx — теперь отсюда; разметка 1:1.

import { useEffect, useState } from 'react'
import { parseChecklist, serializeChecklist, type ChecklistLine } from '../../../shared/checklist'
import { xIcon } from '../../../shared/refs'
import { toast } from '../../../shared/toast'
import { PENCIL } from './common'

export function ChecklistBlock({ code, kind, title }: { code: string; kind: string; title: string }) {
  const [lines, setLines] = useState<ChecklistLine[]>([])
  const [textMode, setTextMode] = useState(false)
  const [draft, setDraft] = useState('')
  const [newLine, setNewLine] = useState('')

  const reload = () => {
    void fetch(`/api/v1/tasks/${code}/checklists/${kind}`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setLines((d.items ?? []).map((i: { kind: string; text: string; status: string; level?: number }) =>
        i.kind === 'heading'
          ? { kind: 'heading', level: i.level ?? 1, text: i.text }
          : { kind: 'item', text: i.text, status: i.status as ChecklistLine['status'] })))
  }
  useEffect(reload, [code, kind])

  const save = async (next: ChecklistLine[]) => {
    setLines(next)
    const r = await fetch(`/api/v1/tasks/${code}/checklists/${kind}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines: serializeChecklist(next) }),
    })
    if (!r.ok) {
      toast('Не удалось сохранить чеклист', 'bad')
    }
  }

  const items = lines.filter((l) => l.kind === 'item')
  const closed = items.filter((l) => ['done', 'closed'].includes(l.status ?? '')).length

  const CLS_COLORS: Record<string, string> = {
    todo: '#8792a3', in_progress: '#3d63d2', closed: '#b98a12', done: '#25935b', failed: '#cf4436',
  }

  return (
    <div className="blk">
      <div className="blk-h">
        <h3>{title}</h3>
        <span className="muted">владелец: {kind === "developer" ? "разработчик" : kind === "reviewer" ? "ревьюер" : "тестировщик"}</span>
        <span className="bar"><i style={{ width: items.length ? `${(closed / items.length) * 100}%` : '0%' }} /></span>
        <span className="progr">{closed}/{items.length}</span>
        <button className="pencil" title="Текстовый режим (markdown со статусами)" aria-label="Текстовый режим" dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => { setDraft(serializeChecklist(lines)); setTextMode(!textMode) }} />
      </div>
      {textMode ? (
        <div className="cl-text">
          <div className="cl-gutter">{draft.split('\n').map((_, i) => <div key={i}>{i + 1}</div>)}</div>
          <textarea rows={Math.max(4, lines.length + 1)} value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => { void save(parseChecklist(draft)); setTextMode(false) }} />
        </div>
      ) : (
        <div className="cl">
          {lines.map((l, idx) => (
            <div key={idx} className={`cl-row ${l.status === 'done' ? 'done' : ''}`}>
              {l.kind === 'item' ? (
                <>
                  <button className="cbx" title="Сменить статус" onClick={() => {
                    const order: ChecklistLine['status'][] = ['todo', 'in_progress', 'done']
                    const cur = order.indexOf(l.status as ChecklistLine['status'])
                    const next = [...lines]
                    next[idx] = { ...l, status: order[(cur + 1) % order.length] }
                    void save(next)
                  }}>{l.status === 'done' ? '✓' : ''}</button>
                  <span className="cl-t">{l.text}</span>
                  <span className="badge" style={{ ['--bc' as string]: CLS_COLORS[l.status ?? 'todo'] }}>{l.status}</span>
                </>
              ) : (
                <span className={`cl-h${l.level ?? 1}`}>{'#'.repeat(l.level ?? 1)} {l.text}</span>
              )}
              <button className="cl-x" onClick={() => void save(lines.filter((_, i) => i !== idx))}>
                <span dangerouslySetInnerHTML={{ __html: xIcon }} />
              </button>
            </div>
          ))}
          <div className="cl-add">
            <input placeholder="Новый пункт — Enter добавляет"
              value={newLine}
              onChange={(e) => setNewLine(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newLine.trim()) {
                  void save([...lines, ...parseChecklist(newLine)])
                  setNewLine('')
                }
              }} />
          </div>
          <div className="cl-hint">Текстовый режим: <code>- ~ x + !</code> статусы пунктов, <code>#…#####</code> заголовки</div>
        </div>
      )}
    </div>
  )
}
