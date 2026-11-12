// Справочники — дословный порт design_mockup/app.js:19-42, 518-525.
// Прежние строковые хелперы чипов (stChip / prioBadge / typeChip / tagHtml / xIcon)
// удалены: единая реализация — React-чипы в shared/chips.tsx, тот же DOM.

export const TYPE: Record<string, { label: string; c: string }> = {
  story: { label: 'История', c: '#7d4fd1' },
  common_task: { label: 'Задача', c: '#3d63d2' },
  qa_task: { label: 'QA', c: '#1f8fb5' },
  bug: { label: 'Баг', c: '#cf4436' },
  analyse_task: { label: 'Анализ', c: '#c2601a' },
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
export const PRIO: Record<string, { label: string; c: string }> = {
  low: { label: 'Низкий', c: '#4f83cf' },
  medium: { label: 'Средний', c: '#8792a3' },
  high: { label: 'Высокий', c: '#cf4436' },
  critical: { label: 'Критический', c: '#cf4436' },
}
