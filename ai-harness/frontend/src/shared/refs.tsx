// Справочники и бейджи — дословный порт design_mockup/app.js:19-42, 518-525.

export const TYPE: Record<string, { label: string; c: string }> = {
  story: { label: 'История', c: '#7d4fd1' },
  common_task: { label: 'Задача', c: '#3d63d2' },
  qa_task: { label: 'QA', c: '#1f8fb5' },
  bug: { label: 'Баг', c: '#cf4436' },
  analyse_task: { label: 'Анализ', c: '#c2601a' },
}

export const ALIAS_LB: Record<string, string> = {
  pending: 'На рассмотрении', backlog: 'Бэклог', todo: 'К работе', progress: 'В работе',
  review: 'На ревью', testing: 'На тестировании', done: 'Готово', blocked: 'Заблокировано', canceled: 'Отменено',
}
export const ALIAS_C: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', progress: '#3d63d2',
  review: '#7d4fd1', testing: '#c2601a', done: '#25935b', blocked: '#cf4436', canceled: '#8792a3',
}
export const S_LABEL: Record<string, string> = {
  pending: 'На рассмотрении', backlog: 'Бэклог', todo: 'К работе',
  in_progress: 'В работе', review_ready: 'Готово к ревью', in_review: 'На ревью',
  qa_ready: 'Готово к тестированию', in_testing: 'На тестировании',
  done: 'Готово', canceled: 'Отменено', blocked: 'Заблокировано',
}
export const SC: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', in_progress: '#3d63d2',
  review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
  done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
}
export const ALIAS_OF: Record<string, string> = {
  pending: 'pending', backlog: 'backlog', todo: 'todo', in_progress: 'progress',
  review_ready: 'review', in_review: 'review', qa_ready: 'testing', in_testing: 'testing',
  done: 'done', canceled: 'canceled', blocked: 'blocked',
}
export const PRIO: Record<string, { label: string; c: string; lvl: number }> = {
  low: { label: 'Низкий', c: '#4f83cf', lvl: 1 },
  medium: { label: 'Средний', c: '#8792a3', lvl: 2 },
  high: { label: 'Высокий', c: '#cf4436', lvl: 3 },
  critical: { label: 'Критический', c: '#cf4436', lvl: 4 },
}

export function esc(s: string): string {
  return (s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

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

export const prioBadge = (p: string, withLabel?: boolean): string =>
  `<span class="prio ${p}" style="--pc:${PRIO[p]?.c ?? '#8792a3'}" title="Приоритет: ${PRIO[p]?.label ?? p}">${prioSvg(p)}${withLabel ? `<span>${PRIO[p]?.label ?? p}</span>` : ''}</span>`

export const typeChip = (t: string): string =>
  `<span class="type-chip" style="--tc:${TYPE[t]?.c ?? '#8792a3'}">${TYPE[t]?.label ?? t}</span>`

export const stChip = (st: string): string =>
  `<span class="st-chip" style="--st:${SC[st] ?? '#8792a3'}"><span class="sdot"></span>${S_LABEL[st] ?? st}</span>`

export const tagHtml = (x: string): string =>
  `<span class="tag ${x === 'by_human' || x === 'by_ai' ? 'sys' : ''}">#${esc(x)}</span>`

export const xIcon =
  '<svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
