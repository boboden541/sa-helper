// Диалог создания: ввод переживает перерисовки, после успеха поля очищаются,
// проект/тип/автор остаются стартовыми (ФТ-ah-69; design_mockup/app.js:1623-1669).

import { useEffect, useState } from 'react'
import { api } from '../../api/client'

interface CreateState {
  projectId: string
  type: string
  title: string
  priority: string
  authorTag: string
  tags: string
  descriptionMd: string
}

export function CreateDialog({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<CreateState>(() => {
    // ввод переживает перерисовки: хранится в модуле диалога
    return (CreateDialog as unknown as { last?: CreateState }).last ?? {
      projectId: 'AH', type: 'common_task', title: '', priority: '',
      authorTag: 'by_human', tags: '', descriptionMd: '',
    }
  })
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<CreateState>) => setState((s) => ({ ...s, ...patch }))

  useEffect(() => { (CreateDialog as unknown as { last?: CreateState }).last = state }, [state])

  const submit = async () => {
    try {
      await api.createTask({
        projectId: state.projectId, type: state.type, title: state.title,
        priority: state.priority, authorTag: state.authorTag,
        tags: state.tags.split(/[\s,]+/).filter(Boolean),
        descriptionMd: state.descriptionMd,
      })
      // после успеха поля очищаются, проект/тип/автор — стартовые
      setState((s) => ({ ...s, title: '', priority: '', tags: '', descriptionMd: '' }))
      onClose()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Новая задача</h2>
        {error && <div className="banner danger">{error}</div>}
        <label>Проект
          <input value={state.projectId} onChange={(e) => set({ projectId: e.target.value.toUpperCase() })} />
        </label>
        <label>Тип
          <select value={state.type} onChange={(e) => set({ type: e.target.value })}>
            {['common_task', 'story', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Название (1–64)
          <input value={state.title} onChange={(e) => set({ title: e.target.value })} maxLength={64} />
        </label>
        <label>Приоритет (обязателен, по умолчанию не проставлен)
          <select value={state.priority} onChange={(e) => set({ priority: e.target.value })}>
            <option value="">— не проставлен —</option>
            {['low', 'medium', 'high', 'critical'].map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Автор
          <select value={state.authorTag} onChange={(e) => set({ authorTag: e.target.value })}>
            <option value="by_human">by_human</option>
            <option value="by_ai">by_ai</option>
          </select>
        </label>
        <label>Теги (до 5, через пробел)
          <input value={state.tags} onChange={(e) => set({ tags: e.target.value })} />
        </label>
        <label>Описание (markdown, ≤20 000)
          <textarea rows={6} value={state.descriptionMd} onChange={(e) => set({ descriptionMd: e.target.value })} />
        </label>
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>Отмена</button>
          <button className="btn primary" onClick={() => void submit()}>Создать</button>
        </div>
      </div>
    </div>
  )
}
