// Диалог создания — .modal > .modal-card > .cr-form (design_mockup/app.js:1623-1669):
// ввод переживает перерисовки, после успеха поля очищаются, проект/тип/автор — стартовые.

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { RichText } from '../../shared/editor/RichText'

interface CreateState {
  projectId: string
  type: string
  title: string
  priority: string
  authorTag: string
  tags: string
  descriptionMd: string
  descMode: 'visual' | 'md'
}

const STORE = (CreateDialog as unknown as { last?: CreateState })

export function CreateDialog({ onClose, prefillTitle }: { onClose: () => void; prefillTitle?: string }) {
  const [state, setState] = useState<CreateState>(() => STORE.last ?? {
    projectId: 'AH', type: 'common_task', title: prefillTitle ?? '', priority: '',
    authorTag: 'by_human', tags: '', descriptionMd: '', descMode: 'visual',
  })
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<CreateState>) => setState((s) => ({ ...s, ...patch }))
  useEffect(() => { STORE.last = state }, [state])

  const submit = async () => {
    try {
      await api.createTask({
        projectId: state.projectId, type: state.type, title: state.title,
        priority: state.priority, authorTag: state.authorTag,
        tags: state.tags.split(/[\s,]+/).filter(Boolean),
        descriptionMd: state.descriptionMd,
      })
      setState((s) => ({ ...s, title: '', priority: '', tags: '', descriptionMd: '' }))
      onClose()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="blk-h"><h3 style={{ fontSize: 15 }}>Новая задача</h3></div>
        {error && <div className="callout bad"><span className="ci">!</span><div className="body">{error}</div></div>}
        <div className="cr-form">
          <div className="f-field"><label>Проект</label>
            <input value={state.projectId} onChange={(e) => set({ projectId: e.target.value.toUpperCase() })} /></div>
          <div className="f-field"><label>Тип задачи</label>
            <select value={state.type} onChange={(e) => set({ type: e.target.value })}>
              {['common_task', 'story', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
            </select></div>
          <div className="f-field" style={{ gridColumn: '1 / -1' }}><label>Название (1–64)</label>
            <input value={state.title} maxLength={64} onChange={(e) => set({ title: e.target.value })} /></div>
          <div className="f-field"><label>Приоритет — обязателен, по умолчанию не проставлен</label>
            <select value={state.priority} onChange={(e) => set({ priority: e.target.value })}>
              <option value="">— не проставлен —</option>
              {['low', 'medium', 'high', 'critical'].map((p) => <option key={p}>{p}</option>)}
            </select></div>
          <div className="f-field"><label>Автор</label>
            <select value={state.authorTag} onChange={(e) => set({ authorTag: e.target.value })}>
              <option value="by_human">by_human</option>
              <option value="by_ai">by_ai</option>
            </select></div>
          <div className="f-field" style={{ gridColumn: '1 / -1' }}><label>Теги (до 5, через пробел; авторский добавится сам)</label>
            <input value={state.tags} onChange={(e) => set({ tags: e.target.value })} /></div>
          <div className="f-field" style={{ gridColumn: '1 / -1' }}>
            <label>Описание <span className="mode-tabs" style={{ marginLeft: 8 }}>
              <button className={state.descMode === 'visual' ? 'active' : ''} onClick={() => set({ descMode: 'visual' })}>Визуально</button>
              <button className={state.descMode === 'md' ? 'active' : ''} onClick={() => set({ descMode: 'md' })}>Markdown</button>
            </span></label>
            {state.descMode === 'visual'
              ? <RichText markdown={state.descriptionMd} onChange={(md) => set({ descriptionMd: md })} />
              : <textarea rows={6} value={state.descriptionMd} onChange={(e) => set({ descriptionMd: e.target.value })} />}
          </div>
        </div>
        <div className="edit-actions" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Отмена</button>
          <button className="btn primary" onClick={() => void submit()}>Создать</button>
        </div>
      </div>
    </div>
  )
}
