// Список — table.tasks из макета (code, tt, type-chip, st-chip, prioBadge, who)

import { useSyncExternalStore } from 'react'
import { api, type TaskCard } from '../../api/client'
import { prioBadge, stChip, tagHtml, typeChip } from '../../shared/refs'
import { currentLive, fmtTokens, subscribeLive } from '../../shared/live'

export function ListView({ tasks }: { tasks: TaskCard[] }) {
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
                  <span className="mini-chip mc-violet" style={{ marginLeft: 8 }}
                    title={live[t.code] ? 'Агент работает прямо сейчас' : 'Токены, потраченные агентами'}>
                    {live[t.code]
                      ? `● ${live[t.code].agent} · ${live[t.code].minutes} мин · ${fmtTokens(live[t.code].total)}`
                      : `${fmtTokens(t.tokensUsed ?? 0)} токенов`}
                  </span>
                ) : null}
              </td>
              <td dangerouslySetInnerHTML={{ __html: typeChip(t.type) }} />
              <td dangerouslySetInnerHTML={{ __html: stChip(t.statusKey) }} />
              <td dangerouslySetInnerHTML={{ __html: prioBadge(t.priority, true) }} />
              <td><span className="who">{(t.tags ?? []).map((x) => (
                <span key={x} dangerouslySetInnerHTML={{ __html: tagHtml(x) }} />
              ))}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
