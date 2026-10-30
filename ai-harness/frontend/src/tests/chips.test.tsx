// Vitest: React-чипы (shared/chips.tsx) обязаны давать байтово тот же DOM,
// что и прежние HTML-хелперы из shared/refs.tsx — на классы завязаны
// Playwright e2e (.st-chip, .prio, .type-chip, .tag).

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { prioBadge, stChip, tagHtml, typeChip } from '../shared/refs'
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
