// Vitest: parseHash — hash-роутинг deep links (ФТ-ah-17): виды, вкладки настроек,
// Eve, коды задач с /page, темы.

import { describe, expect, it, vi } from 'vitest'

// jsdom не реализует window.matchMedia, а стор вычисляет стартовую тему
// при создании модуля — стаб ставим до первого импорта стора.
// В node localStorage без файла нерабочий и затирает jsdom-овский — даём пустой.
vi.stubGlobal('localStorage', {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
})

vi.stubGlobal('matchMedia', (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
}))

const { parseHash } = await import('../app/store')

describe('parseHash — виды', () => {
  it('#board → доска', () => {
    expect(parseHash('#board')).toMatchObject({ view: 'board' })
  })
  it('#/board — ведущий слэш не мешает', () => {
    expect(parseHash('#/board')).toMatchObject({ view: 'board' })
  })
  it('#list → список', () => {
    expect(parseHash('#list')).toMatchObject({ view: 'list' })
  })
  it('#eve → открыт Eve', () => {
    expect(parseHash('#eve')).toMatchObject({ eveOpen: true })
  })
  it('пустой/чужой хэш — пустой патч (вид не меняется)', () => {
    expect(parseHash('#')).toEqual({})
    expect(parseHash('')).toEqual({})
    expect(parseHash('#что-то-иное')).toEqual({})
  })
})

describe('parseHash — настройки', () => {
  it('#settings/flow → настройки + вкладка flow', () => {
    expect(parseHash('#settings/flow')).toEqual({ view: 'settings', settingsTab: 'flow' })
  })
  it('#settings/projects → вкладка projects', () => {
    expect(parseHash('#settings/projects')).toEqual({ view: 'settings', settingsTab: 'projects' })
  })
  it('#settings/agents → вкладка agents', () => {
    expect(parseHash('#settings/agents')).toEqual({ view: 'settings', settingsTab: 'agents' })
  })
  it('#settings без таба → только вид, tab не трогается', () => {
    expect(parseHash('#settings')).toEqual({ view: 'settings' })
  })
})

describe('parseHash — задачи', () => {
  it('#AH-123 → карточка задачи, drawer', () => {
    expect(parseHash('#AH-123')).toEqual({ view: 'task', taskCode: 'AH-123', taskPage: false })
  })
  it('#AH-123/page → полная страница', () => {
    expect(parseHash('#AH-123/page')).toEqual({ view: 'task', taskCode: 'AH-123', taskPage: true })
  })
  it('строчный код приводится к верхнему регистру', () => {
    expect(parseHash('#ah-42/page')).toEqual({ view: 'task', taskCode: 'AH-42', taskPage: true })
  })
  it('префикс кода — до 10 букв', () => {
    expect(parseHash('#ABCDEFGHIX-1')).toMatchObject({ view: 'task', taskCode: 'ABCDEFGHIX-1' })
  })
})

describe('parseHash — темы', () => {
  it('#dark → тёмная', () => {
    expect(parseHash('#dark')).toMatchObject({ theme: 'dark' })
  })
  it('#light → светлая', () => {
    expect(parseHash('#light')).toMatchObject({ theme: 'light' })
  })
})
