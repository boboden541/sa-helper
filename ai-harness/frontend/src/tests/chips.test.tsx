// Vitest: React-чипы (shared/chips.tsx) обязаны давать байтово тот же DOM,
// что прежние HTML-хелперы из shared/refs.tsx (удалены после унификации —
// эталоны ниже дословно их разметка) — на классы завязаны Playwright e2e
// (.st-chip, .prio, .type-chip, .tag).

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PRIO, SC, S_LABEL, TYPE } from '../shared/refs'
import { PrioBadge, StChip, TagChip, TypeChip } from '../shared/chips'

const STATUSES = ['pending', 'backlog', 'todo', 'progress', 'in_progress', 'review_ready',
  'in_review', 'qa_ready', 'in_testing', 'done', 'canceled', 'blocked', 'weird_status']
const PRIOS = ['low', 'medium', 'high', 'critical', 'urgent']
const TYPES = ['story', 'common_task', 'qa_task', 'bug', 'analyse_task', 'unknown_type']

// Строки могут отличаться самозакрытым тегом (<path/> против <path></path>) —
// в DOM-дереве это одно и то же, поэтому сравниваем после разбора браузером.
const dom = (html: string): string => {
  const el = document.createElement('div')
  el.innerHTML = html
  return el.innerHTML
}

// Эталон: прежние HTML-хелперы из shared/refs.tsx (дословная разметка).
const esc = (s: string): string =>
  (s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function prioSvg(p: string): string {
  const c = `fill="none" stroke="${PRIO[p]?.c ?? '#8792a3'}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"`
  if (p === 'critical')
    return `<svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 12.5l4-4 4 4M3 7.5l4-4 4 4" ${c}/></svg>`
  if (p === 'high')
    return `<svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 11.5l4-7 4 7" ${c}/></svg>`
  if (p === 'low')
    return `<svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 2.5l4 7 4-7" ${c}/></svg>`
  return `<svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 5.5h8M3 8.5h8" ${c}/></svg>`
}

const prioBadge = (p: string, withLabel?: boolean): string =>
  `<span class="prio ${p}" style="--pc:${PRIO[p]?.c ?? '#8792a3'}" title="Приоритет: ${PRIO[p]?.label ?? p}">${prioSvg(p)}${withLabel ? `<span>${PRIO[p]?.label ?? p}</span>` : ''}</span>`

const typeChip = (t: string): string =>
  `<span class="type-chip" style="--tc:${TYPE[t]?.c ?? '#8792a3'}">${TYPE[t]?.label ?? t}</span>`

const stChip = (st: string): string =>
  `<span class="st-chip" style="--st:${SC[st] ?? '#8792a3'}"><span class="sdot"></span>${S_LABEL[st] ?? st}</span>`

const tagHtml = (x: string): string =>
  `<span class="tag ${x === 'by_human' || x === 'by_ai' ? 'sys' : ''}">#${esc(x)}</span>`

describe('чипы: React === HTML-хелпер (тот же DOM)', () => {
  it('st-chip для всех статусов, включая фолбэк', () => {
    for (const st of STATUSES) {
      expect(dom(renderToStaticMarkup(<StChip st={st} />))).toBe(dom(stChip(st)))
    }
  })
  it('prio-бейдж с подписью и без', () => {
    for (const p of PRIOS) {
      expect(dom(renderToStaticMarkup(<PrioBadge p={p} />))).toBe(dom(prioBadge(p)))
      expect(dom(renderToStaticMarkup(<PrioBadge p={p} withLabel />))).toBe(dom(prioBadge(p, true)))
    }
  })
  it('type-chip для всех типов, включая фолбэк', () => {
    for (const t of TYPES) {
      expect(dom(renderToStaticMarkup(<TypeChip t={t} />))).toBe(dom(typeChip(t)))
    }
  })
  it('теги: обычный, авторский (sys), экранирование спецсимволов', () => {
    for (const tag of ['ui', 'by_human', 'by_ai', 'a<b>&c']) {
      expect(dom(renderToStaticMarkup(<TagChip tag={tag} />))).toBe(dom(tagHtml(tag)))
    }
  })
})
