// Блок «Описание» — desc-view .md (markdown) и desc-edit с editbar:
// TipTap (RichText) или текстовый markdown. Перенесено из TaskView.tsx 1:1.

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../../api/client'
import { renderMarkdown } from '../../../shared/markdown'
import { toast } from '../../../shared/toast'
import { RichText } from '../../../shared/editor/RichText'
import { PENCIL } from './common'

export function DescBlock({ code, card, reload }: {
  code: string
  card: TaskCard
  reload: () => void
}) {
  const [editingDesc, setEditingDesc] = useState(false)
  const [descMode, setDescMode] = useState<'visual' | 'md'>('visual')
  const [descDraft, setDescDraft] = useState('')
  useEffect(() => { setDescDraft(card.descriptionMd ?? '') }, [card])

  const saveDesc = async () => {
    const fresh = await api.patchTask(code, { descriptionMd: descDraft })
    if (fresh.changedByOther) toast('Карточка обновлена другим участником', 'auto')
    setEditingDesc(false); reload()
  }

  return (
    <div className="blk">
      <div className="blk-h"><h3>Описание</h3><span className="fill" />
        {!editingDesc && <button className="pencil show" title="Редактировать" dangerouslySetInnerHTML={{ __html: PENCIL }} onClick={() => setEditingDesc(true)} />}
      </div>
      {editingDesc ? (
        <div className="desc-edit">
          <div className="editbar">
            <div className="mode-tabs">
              <button className={descMode === 'visual' ? 'active' : ''} onClick={() => setDescMode('visual')}>Визуально</button>
              <button className={descMode === 'md' ? 'active' : ''} onClick={() => setDescMode('md')}>Markdown</button>
            </div>
          </div>
          {descMode === 'visual'
            ? <RichText markdown={descDraft} onChange={setDescDraft} />
            : <textarea value={descDraft} onChange={(e) => setDescDraft(e.target.value)} />}
          <div className="edit-actions">
            <button className="btn primary" onClick={() => void saveDesc()}>Сохранить</button>
            <button className="btn" onClick={() => setEditingDesc(false)}>Отмена</button>
          </div>
        </div>
      ) : (
        <div className="desc-view">
          <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(card.descriptionMd ?? '') }} />
        </div>
      )}
    </div>
  )
}
