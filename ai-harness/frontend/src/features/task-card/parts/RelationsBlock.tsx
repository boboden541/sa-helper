// Связанные задачи (.rel): список связей с kind-чипом, поиск и добавление,
// снятие связи. Перенесено из TaskView.tsx 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { XIcon } from '../../../shared/chips'
import { toast } from '../../../shared/toast'
import { Collapsible } from './Collapsible'

export function RelationsBlock({ code, relations, reload }: {
  code: string
  relations: { id: string; kind: string; code: string; title: string }[]
  reload: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [kind, setKind] = useState('do_after')
  const [q, setQ] = useState('')
  const [found, setFound] = useState<{ code: string; title: string }[]>([])
  useEffect(() => {
    if (!adding || !q.trim()) { setFound([]); return }
    const t = setTimeout(() => {
      void api.tasks({ q: q.trim() }).then((d) =>
        setFound((d.items ?? []).filter((x: { code: string }) => x.code !== code).slice(0, 6)))
    }, 250)
    return () => clearTimeout(t)
  }, [q, adding, code])
  const add = (toCode: string) => {
    void api.addRelation(code, toCode, kind).then(() => { setAdding(false); setQ(''); reload() })
      .catch((e: Error) => toast(e.message, 'bad'))
  }
  const KIND: Record<string, string> = { do_after: 'делать после этой', blocked_by: 'блокирована задачей' }
  return (
    <Collapsible id="relations" title="Связанные задачи"
      right={<button className="btn small" onClick={() => setAdding(!adding)}>＋ связь</button>}>
      {(relations ?? []).map((r) => (
        <div key={r.id} className="rel" onClick={() => { window.location.hash = `#${r.code}` }}>
          <span className="code">{r.code}</span>
          <span className="rt">{r.title}</span>
          <span className={`linkchip ${r.kind === 'blocked_by' ? 'hard' : ''}`}>{KIND[r.kind] ?? r.kind}</span>
          <button className="cl-x" title="Убрать связь" onClick={(e) => {
            e.stopPropagation()
            void api.delRelation(code, r.id).then(reload)
          }}><span><XIcon /></span></button>
        </div>
      ))}
      {!relations?.length && !adding && (
        <div className="muted" style={{ fontSize: 12 }}>Связей нет. Добавьте задачу, которая делается после этой или блокирует её.</div>)}
      {adding && (
        <div className="rel-add">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="do_after">делать после этой</option>
            <option value="blocked_by">блокирована задачей</option>
          </select>
          <input placeholder="Код или название задачи…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          {found.map((f) => (
            <div key={f.code} className="rel" onClick={() => add(f.code)}>
              <span className="code">{f.code}</span><span className="rt">{f.title}</span>
            </div>
          ))}
          {q && !found.length && <div className="muted" style={{ fontSize: 12 }}>Ничего не найдено</div>}
        </div>
      )}
    </Collapsible>
  )
}
