// Диалог создания — .modal > .modal-card > .cr-form (design_mockup/app.js:1623-1669):
// ввод переживает перерисовки, после успеха поля очищаются, проект/тип/автор — стартовые.

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { RichText } from '../../shared/editor/RichText'
import { useApp } from '../../app/store'

interface CreateState {
  projectId: string
  type: string
  title: string
  priority: string
  authorTag: string
  tags: string
  descriptionMd: string
  descMode: 'visual' | 'md'
  psiPath: string
}

const STORE = (CreateDialog as unknown as { last?: CreateState })

export function CreateDialog({ onClose, prefillTitle }: { onClose: () => void; prefillTitle?: string }) {
  const [state, setState] = useState<CreateState>(() => STORE.last ?? {
    projectId: 'AH', type: 'common_task', title: prefillTitle ?? '', priority: '',
    authorTag: 'by_human', tags: '', descriptionMd: '', descMode: 'visual', psiPath: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [psiWarn, setPsiWarn] = useState<{ custom: string } | null>(null)
  const [projects, setProjects] = useState<{ mnemonic: string; name: string; isArchived: boolean }[]>([])
  const [projQ, setProjQ] = useState<string | null>(null)
  useEffect(() => {
    void api.projects().then(setProjects).catch(() => {})
    const active = useApp.getState().project
    if (active) setState((s) => ({ ...s, projectId: active }))
  }, [])
  const set = (patch: Partial<CreateState>) => setState((s) => ({ ...s, ...patch }))
  useEffect(() => { STORE.last = state }, [state])

  const submit = async (psiPath?: string) => {
    try {
      await api.createTask({
        projectId: state.projectId, type: state.type, title: state.title,
        priority: state.priority, authorTag: state.authorTag,
        tags: state.tags.split(/[\s,]+/).filter(Boolean),
        descriptionMd: state.descriptionMd,
        psiPath: psiPath ?? (state.psiPath.trim() || undefined),
      })
      setState((s) => ({ ...s, title: '', priority: '', tags: '', descriptionMd: '', psiPath: '' }))
      onClose()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="modal" onClick={psiWarn ? undefined : onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        {psiWarn && (
          <div className="modal psi-warn" onClick={(e) => e.stopPropagation()}>
            <div className="modal-card">
              <div className="blk-h"><h3 style={{ fontSize: 15 }}>Не указан путь сохранения документа ПСИ</h3></div>
              <div className="f-field">
                <label>Указать путь вручную</label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input value={psiWarn.custom} placeholder="/Users/…/документы/psi.md или папка внутри проекта"
                    onChange={(e) => setPsiWarn({ custom: e.target.value })} />
                  <button className="btn primary" disabled={!psiWarn.custom.trim()}
                    onClick={() => {
                      const pp = psiWarn.custom.trim()
                      set({ psiPath: pp })
                      setPsiWarn(null)
                      void submit(pp)
                    }}>Указать путь</button>
                </div>
              </div>
              <div className="f-field">
                <label>Продолжить со стандартным путём (недоступно для изменения)</label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input value=".harness/psi/<код истории>/psi.md" disabled className="mono" />
                  <button className="btn" onClick={() => {
                    set({ psiPath: '' })
                    setPsiWarn(null)
                    void submit('')
                  }}>Продолжить</button>
                </div>
              </div>
              <div className="edit-actions">
                <button className="btn" onClick={() => setPsiWarn(null)}>Вернуться к форме</button>
              </div>
            </div>
          </div>
        )}
        <div className="blk-h"><h3 style={{ fontSize: 15 }}>Новая задача</h3></div>
        {error && <div className="callout bad"><span className="ci">!</span><div className="body">{error}</div></div>}
        <div className="cr-form">
          <div className="f-field" style={{ position: 'relative' }}>
            <label>Проект (поиск по названию или мнемонике)</label>
            <input value={projQ ?? state.projectId}
              placeholder="AH — AI Harness…"
              onChange={(e) => { setProjQ(e.target.value); set({ projectId: e.target.value.toUpperCase() }) }} />
            {projQ !== null && (
              <div className="proj-drop">
                {projects.filter((pr) => !pr.isArchived && (
                  !projQ.trim() || pr.name.toLowerCase().includes(projQ.toLowerCase())
                  || pr.mnemonic.toLowerCase().includes(projQ.toLowerCase()))).map((pr) => (
                  <div key={pr.mnemonic} className="rel" onClick={() => { set({ projectId: pr.mnemonic }); setProjQ(null) }}>
                    <span className="code">{pr.mnemonic}</span><span className="rt">{pr.name}</span>
                  </div>
                ))}
                {!projects.filter((pr) => !pr.isArchived && (
                  !projQ.trim() || pr.name.toLowerCase().includes(projQ.toLowerCase())
                  || pr.mnemonic.toLowerCase().includes(projQ.toLowerCase()))).length
                  && <div className="muted" style={{ fontSize: 12 }}>Проект не найден — проверьте мнемонику в «Настройки → Проекты»</div>}
              </div>)}
          </div>
          <div className="f-field"><label>Тип задачи</label>
            <select value={state.type} onChange={(e) => set({ type: e.target.value })}>
              {['common_task', 'story', 'qa_task', 'bug', 'analyse_task'].map((t) => <option key={t}>{t}</option>)}
            </select></div>
          {state.type === 'story' && (
            <div className="f-field" style={{ gridColumn: '1 / -1' }}>
              <label>Путь сохранения документа ПСИ (необязательно)</label>
              <input value={state.psiPath}
                placeholder="ПСИ: например /Users/raaliev/Проекты/доки/psi.md — если пусто, стандартный путь"
                onChange={(e) => set({ psiPath: e.target.value })} />
            </div>)}
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
          <button className="btn primary" onClick={() => {
            if (state.type === 'story' && !state.psiPath.trim() && psiWarn === null) {
              setPsiWarn({ custom: '' })
              return
            }
            void submit()
          }}>Создать</button>
        </div>
      </div>
    </div>
  )
}
