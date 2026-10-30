// Переходы и форс — trans (кнопки разрешённых переходов), trans-reasons
// (запреты с причинами) и details.force (форс-переход с обязательной причиной).
// Перенесено из TaskView.tsx 1:1.

import { useState } from 'react'
import { api, type TaskCard } from '../../../api/client'
import { S_LABEL, xIcon } from '../../../shared/refs'
import { toast } from '../../../shared/toast'

export function TransBlock({ code, card, L, reload }: {
  code: string
  card: TaskCard
  L: (key: string) => string
  reload: () => void
}) {
  const [forceTo, setForceTo] = useState('')
  const [forceReason, setForceReason] = useState('')

  return (
    <div className="blk">
      <div className="trans">
        <span className="cur">Сейчас: {L(card.statusKey)} →</span>
        {card.gate?.allowed.map((to) => (
          <button key={to} className="btn" onClick={async () => {
            const r = await api.transition(code, to)
            if (!r.applied) toast(r.reason ?? 'отказ', 'bad'); else toast(`<b>${code}</b> → ${L(to)}`, 'ok')
            reload()
          }}>{L(to)}</button>
        ))}
      </div>
      {card.gate && card.gate.denied.length > 0 && (
        <div className="trans-reasons">
          {card.gate.denied.map((d) => (
            <div key={d.to}><span dangerouslySetInnerHTML={{ __html: xIcon }} />
              {L(d.to)} — {d.reason}</div>
          ))}
        </div>
      )}
      <details className="force">
        <summary>Форс-переход — с обязательной причиной</summary>
        <div className="fb">
          <textarea placeholder="Причина (обязательно)…"
            value={forceReason} onChange={(e) => setForceReason(e.target.value)} />
          <div className="fr">
            <select value={forceTo} onChange={(e) => setForceTo(e.target.value)}>
              <option value="">Куда…</option>
              {Object.entries({ ...S_LABEL, ...(card.gate?.labels ?? {}) }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <button className="btn danger" disabled={!forceReason.trim() || !forceTo}
              onClick={async () => {
                await api.force(code, forceTo, forceReason)
                toast(`<b>${code}</b>: форс → ${L(forceTo)}`, 'auto')
                setForceReason(''); setForceTo(''); reload()
              }}>Форс-переход</button>
            <span className="note">Пишется в хроники как «форс · ручное вмешательство»</span>
          </div>
        </div>
      </details>
    </div>
  )
}
