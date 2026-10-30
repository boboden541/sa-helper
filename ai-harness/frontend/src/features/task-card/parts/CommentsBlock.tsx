// Комментарии (.cmt): визуальный редактор (TipTap) или текстовый markdown,
// рендер комментариев через renderMarkdown. Перенесено из TaskView.tsx 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { renderMarkdown } from '../../../shared/markdown'
import { RichText } from '../../../shared/editor/RichText'

export function CommentsBlock({ code }: { code: string }) {
  const [items, setItems] = useState<{ id: string; author: string; body: string; at: string }[]>([])
  const [draft, setDraft] = useState('')
  const [mode, setMode] = useState<'visual' | 'text'>('visual')
  const reload = () => {
    void api.comments(code).then((d: unknown) => setItems(Array.isArray(d) ? (d as typeof items) : []))
      .catch(() => { /* комментарии не критичны */ })
  }
  useEffect(reload, [code])
  const send = () => {
    if (!draft.trim()) return
    void api.addComment(code, draft).then(() => { setDraft(''); reload() })
  }
  return (
    <div className="blk">
      <div className="blk-h"><h3>Комментарии</h3><span className="fill" />
        <div className="mode-tabs">
          <button className={mode === 'visual' ? 'active' : ''} onClick={() => setMode('visual')}>Визуально</button>
          <button className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>Текст</button>
        </div></div>
      {items.map((c) => (
        <div key={c.id} className="cmt">
          <span className="ava">{c.author.slice(0, 1)}</span>
          <div className="b"><div className="h"><b>{c.author}</b> · {c.at.slice(0, 16).replace('T', ' ')}</div>
            <div className="tx md" dangerouslySetInnerHTML={{ __html: renderMarkdown(c.body) }} /></div>
        </div>
      ))}
      <div className="cmt-add">
        {mode === 'visual'
          ? <RichText markdown={draft} onChange={setDraft} />
          : <textarea rows={4} placeholder="Markdown-комментарий… (**жирный**, списки, код)"
              value={draft} onChange={(e) => setDraft(e.target.value)} />}
        <div className="edit-actions">
          <button className="btn primary small" onClick={send} disabled={!draft.trim()}>Отправить</button>
        </div>
      </div>
    </div>
  )
}
