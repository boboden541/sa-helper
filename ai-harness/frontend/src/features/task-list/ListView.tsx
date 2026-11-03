// Список — table.tasks из макета (code, tt, TypeChip, StChip, PrioBadge, who):
// чипы — React-компоненты из shared/chips.tsx, тот же DOM, что у макетных строк

import { useSyncExternalStore, useState } from 'react'
import { TokSplit, partsOf } from '../../shared/tokens'
import { api, type TaskCard } from '../../api/client'
import { PrioBadge, StChip, TagChip, TypeChip } from '../../shared/chips'
import { currentLive, fmtTokens, subscribeLive } from '../../shared/live'

export function ListView({ tasks }: { tasks: TaskCard[] }) {
  const [tokOpenCode, setTokOpenCode] = useState<string | null>(null)
  const live = useSyncExternalStore(subscribeLive, currentLive)
  const open = async (code: string) => {
    const card = await api.task(code).catch(() => null)
    if (!card) return
    window.location.hash = `#${code}`
  }
  return (
    <div className="listwrap">
      <table className="tasks">
        <thead><tr><th>Код</th><th>Задача</th><th>Тип</th><th>Статус</th><th>Приоритет</th><th>Теги</th></tr></thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.code} onClick={() => void open(t.code)}>
              <td><span className="code">{t.code}</span></td>
              <td className="tt">{t.title}{t.storyCode && <small>история {t.storyCode}</small>}
                {(live[t.code] || t.tokensUsed) ? (
                  <span className="mini-chip mc-violet tok-click" style={{ marginLeft: 8 }}
                    title={live[t.code] ? 'Агент работает прямо сейчас — клик раскрывает вход/выход/кэш' : 'Токены, потраченные агентами — клик раскрывает вход/выход/кэш'}
                    onClick={(e) => { e.stopPropagation(); setTokOpenCode((v) => (v === t.code ? null : t.code)) }}>
                    {live[t.code]
                      ? `● ${live[t.code].agent} · ${live[t.code].minutes} мин · ${fmtTokens(live[t.code].total)}`
                      : `${fmtTokens(t.tokensUsed ?? 0)} токенов`}
                    {tokOpenCode === t.code && (() => {
                      const lv = live[t.code]
                      const [i, o, c] = partsOf(lv, t.tokensInput ?? 0, t.tokensOutput ?? 0, t.tokensCache ?? 0)
                      return <TokSplit input={i} output={o} cache={c} />
                    })()}
                  </span>
                ) : null}
              </td>
              <td><TypeChip t={t.type} /></td>
              <td><StChip st={t.statusKey} /></td>
              <td><PrioBadge p={t.priority} withLabel /></td>
              <td><span className="who">{(t.tags ?? []).map((x) => (
                <TagChip key={x} tag={x} />
              ))}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
