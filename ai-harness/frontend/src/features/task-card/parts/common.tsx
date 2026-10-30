// Общие мелочи подкомпонентов карточки задачи: иконка-карандаш правки,
// тип записи хроники (в т.ч. «живые» из SSE) и форма живого прогона в шапке.

export const PENCIL = '<svg width="13" height="13" viewBox="0 0 14 14"><path d="M9.7 1.8l2.5 2.5L4.5 12H2V9.5l7.7-7.7z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'

export interface ChronicleItem {
  id: string
  type: string
  authorKind: string
  ruleCode?: string
  message: string
  at: string
  live?: boolean  // запись пришла живым потоком, пока открыт экран
}

export interface LiveRun { agent: string; minutes: number; total: number; stale: boolean }
