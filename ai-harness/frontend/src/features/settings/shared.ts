// Общее для вкладок настроек: реестр вкладок, хук текущего таба из хэша
// (#settings/<tab>) и пресеты типов задач для seg-переключателей flow/матрицы.

export const TABS: [string, string][] = [
  ['providers', 'ИИ-провайдеры'], ['tools', 'Инструменты'], ['projects', 'Проекты'],
  ['flow', 'Status-flow'], ['agents', 'Агенты и матрица'], ['queue', 'Очередь автомата'],
  ['journal', 'Журнал настроек'],
]

// Типы задач для seg-переключателей: нужен и редактору flow, и матрице назначений.
export const FLOW_TYPES: [string, string][] = [
  ['story', 'Истории'], ['common_task', 'Задачи'], ['qa_task', 'QA'],
  ['bug', 'Баги'], ['analyse_task', 'Анализ'],
]

export function useSettingsTab(): string {
  const m = window.location.hash.match(/settings\/(\w+)/)
  return m ? m[1] : 'providers'
}
