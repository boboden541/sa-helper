// Карточка на доске — React-компонент вместо HTML-строки через dangerouslySetInnerHTML
// (бывший cardHtml() в Board.tsx). Разметка байтово та же: классы .card/.code/.card-top/
// .card-title/.card-tags/.agent/.token-row/.card-sub завязаны на Playwright e2e
// (клик по .card, код .code с data-open-page, merged-чип статуса, полоса «top» у блоков).
// Эквивалентность закреплена тестом src/tests/taskcard.test.tsx.

import type { TaskCard } from '../../api/client'
import { fmtTokens, type LiveTask } from '../../shared/live'
import { PrioBadge, StChip, TagChip, TypeChip } from '../../shared/chips'

import { useState } from 'react'
import { TokSplit, partsOf } from '../../shared/tokens'

// Цвета статусов для левой полосы карточки и полосы истории (фолбэк — серый).
export const STATUS_COLORS: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', progress: '#3d63d2', in_progress: '#3d63d2',
  review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
  done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
}

export function TaskCardView({ task, merged, live, onOpen, onOpenPage }: {
  task: TaskCard
  merged: boolean
  live?: LiveTask
  onOpen: () => void
  onOpenPage: () => void
}) {
  const blocked = task.statusKey === 'blocked'
  const [tokOpen, setTokOpen] = useState(false)
  const showTok = Boolean(live?.total || task.tokensUsed)
  return (
    <article className={`card ${blocked ? 'top' : ''}`}
      data-code={task.code}
      style={{ ['--st' as string]: STATUS_COLORS[task.statusKey] ?? '#8792a3' }}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('[data-open-page]')) onOpenPage()
        else if ((e.target as HTMLElement).closest('.card')) onOpen()
      }}>
      <div className="card-top">
        <span className="code" data-open-page={task.code}>{task.code}</span>
        <TypeChip t={task.type} />
        <span className="sp" />
        {merged ? <StChip st={task.statusKey} /> : ''}
        <PrioBadge p={task.priority} />
      </div>
      <div className="card-title">{task.title}</div>
      <div className="card-tags">{(task.tags ?? []).map((t) => <TagChip key={t} tag={t} />)}</div>
      {live
        ? <div className="agent live">
            {live.stale ? '⚠' : <span className="dot pulse" style={{ background: '#25935b' }} />}
            {`${live.agent} работает · ${live.minutes} мин${live.total ? ` · ${fmtTokens(live.total)} токенов` : ''}`}
          </div>
        : task.agent
          ? <div className="agent"><span className="dot pulse" style={{ background: '#7d4fd1' }} />{task.agent.name}</div>
          : null}
      {showTok ? (
        <div className="token-row tok-click" title="Токены, потраченные агентами на задачу — клик раскрывает вход/выход/кэш"
          onClick={(e) => { e.stopPropagation(); setTokOpen((v) => !v) }}>
          <span className="mini-chip mc-violet">
            {live?.total ? `${fmtTokens(live.total)} · сейчас` : `${fmtTokens(task.tokensUsed ?? 0)} токенов`}
          </span>
          {tokOpen && (
            <TokSplit {...(() => {
              const [i, o, c] = partsOf(live, task.tokensInput ?? 0, task.tokensOutput ?? 0, task.tokensCache ?? 0)
              return { input: i, output: o, cache: c }
            })()} />
          )}
        </div>
      ) : null}
      {blocked ? <div className="card-sub">{`✕ Требуется человек: ${task.blockedReason ?? ''}`}</div> : null}
    </article>
  )
}
