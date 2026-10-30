// Vitest: карточка доски (TaskCardView) обязана давать тот же DOM, что прежний
// cardHtml() из Board.tsx (HTML-строка через dangerouslySetInnerHTML) — на
// разметку завязаны Playwright e2e (.card, .code[data-open-page], .card-top,
// merged-чип статуса, .card.top у блоков, .agent.live, .token-row, .card-sub).

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { TaskCard } from '../api/client'
import { fmtTokens, type LiveTask } from '../shared/live'
import { esc, prioBadge, stChip, tagHtml, typeChip } from '../shared/refs'
import { TaskCardView } from '../features/board/TaskCard'

// Сравниваем DOM-дерево: строки могут отличаться самозакрытыми тегами и
// пробелами между тегами (наследие шаблонной строки). Пробельные текстовые
// узлы не влияют ни на CSS (flex их игнорирует), ни на Playwright-селекторы
// (toContainText/hasText нормализуют пробелы) — схлопываем.
const dom = (html: string): string => {
  const el = document.createElement('div')
  el.innerHTML = html
  return el.innerHTML.replace(/>\s+</g, '><')
}

// Эталон: прежняя сборка карточки HTML-строкой (Board.tsx до рефакторинга).
function legacyCardHtml(t: TaskCard, merged: boolean, live?: LiveTask): string {
  const STATUS_COLORS: Record<string, string> = {
    pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', progress: '#3d63d2', in_progress: '#3d63d2',
    review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
    done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
  }
  return `<article class="card ${t.statusKey === 'blocked' ? 'top' : ''}" data-code="${t.code}" style="--st:${STATUS_COLORS[t.statusKey] ?? '#8792a3'}">
    <div class="card-top">
      <span class="code" data-open-page="${t.code}">${t.code}</span>
      ${typeChip(t.type)}
      <span class="sp"></span>
      ${merged ? stChip(t.statusKey) : ''}
      ${prioBadge(t.priority)}
    </div>
    <div class="card-title">${esc(t.title)}</div>
    <div class="card-tags">${(t.tags ?? []).map(tagHtml).join('')}</div>
    ${live
      ? `<div class="agent live">${live.stale ? '⚠' : '<span class="dot pulse" style="background:#25935b"></span>'}${esc(live.agent)} работает · ${live.minutes} мин${live.total ? ` · ${fmtTokens(live.total)} токенов` : ''}</div>`
      : t.agent ? `<div class="agent"><span class="dot pulse" style="background:#7d4fd1"></span>${esc(t.agent.name)}</div>` : ''}
    ${(live?.total || t.tokensUsed) ? `<div class="token-row"><span class="mini-chip mc-violet" title="Токены, потраченные агентами на задачу">${live?.total ? `${fmtTokens(live.total)} · сейчас` : `${fmtTokens(t.tokensUsed ?? 0)} токенов`}</span></div>` : ''}
    ${t.statusKey === 'blocked' ? `<div class="card-sub">✕ Требуется человек: ${esc(t.blockedReason ?? '')}</div>` : ''}
  </article>`
}

const base: TaskCard = {
  code: 'AH-123',
  title: 'Профиль <пользователя> & права',
  priority: 'high',
  type: 'common_task',
  statusKey: 'progress',
  tags: ['by_human', 'ui'],
  agent: { name: 'Агент <Разработчик>' },
  tokensUsed: 1543,
}

function render(t: TaskCard, merged = false, live?: LiveTask): string {
  return dom(renderToStaticMarkup(
    <TaskCardView task={t} merged={merged} live={live}
      onOpen={() => {}} onOpenPage={() => {}} />))
}

describe('карточка доски: React === прежний cardHtml', () => {
  it('обычная карточка с агентом и токенами', () => {
    expect(render(base)).toBe(dom(legacyCardHtml(base, false)))
  })
  it('merged-вариант — чип статуса рядом с типом', () => {
    const merged = { ...base, statusKey: 'review_ready' }
    expect(render(merged, true)).toBe(dom(legacyCardHtml(merged, true)))
  })
  it('заблокированная — .top и .card-sub', () => {
    const blocked: TaskCard = { ...base, statusKey: 'blocked', blockedReason: 'нужен доступ <к API>' }
    expect(render(blocked)).toBe(dom(legacyCardHtml(blocked, false)))
  })
  it('живой прогон — .agent.live с точкой и токенами «сейчас»', () => {
    const live: LiveTask = { code: 'AH-123', title: '', agent: 'Агент', minutes: 7,
      stale: false, input: 0, output: 0, cache: 0, total: 20481 }
    expect(render(base, false, live)).toBe(dom(legacyCardHtml(base, false, live)))
  })
  it('живой прогон со stale — ⚠ вместо точки', () => {
    const live: LiveTask = { code: 'AH-123', title: '', agent: 'Агент', minutes: 3,
      stale: true, input: 0, output: 0, cache: 0, total: 0 }
    const noTokens = { ...base, tokensUsed: undefined }
    expect(render(noTokens, false, live)).toBe(dom(legacyCardHtml(noTokens, false, live)))
  })
  it('минимальная карточка — без тегов, агента и токенов', () => {
    const bare: TaskCard = { code: 'QA-9', title: 'Пустая', priority: 'low', type: 'qa_task', statusKey: 'todo' }
    expect(render(bare)).toBe(dom(legacyCardHtml(bare, false)))
  })
  it('неизвестный статус — серая полоса, фолбэк классов', () => {
    const odd: TaskCard = { ...base, statusKey: 'custom_status' }
    expect(render(odd)).toBe(dom(legacyCardHtml(odd, false)))
  })
})
