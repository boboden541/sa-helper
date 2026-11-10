// Vitest: сворачиваемые разделы карточки (Collapsible) — рендер раскрытым,
// клик по шеврону сворачивает и пишет localStorage, кнопки в right-слоте
// раздел не сворачивают, ширина drawer клампится.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Collapsible } from '../features/task-card/parts/Collapsible'
import { clampDrawerWidth } from '../features/task-card/TaskView'

// В node localStorage без файла нерабочий и затирает jsdom-овский — даём
// in-memory подмену (паттерн store.test.ts)
const store: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store[k] ?? null,
  setItem: (k: string, v: string) => { store[k] = v },
  removeItem: (k: string) => { delete store[k] },
})

beforeEach(() => {
  cleanup()
  for (const k of Object.keys(store)) delete store[k]
})

describe('Collapsible', () => {
  it('раскрыт по умолчанию, тело видно', () => {
    render(<Collapsible id="desc" taskId="AH-1" title="Описание"><p>тело описания</p></Collapsible>)
    expect(screen.getByText('тело описания')).toBeTruthy()
    expect(screen.getByText('Описание')).toBeTruthy()
  })

  it('клик по шеврону сворачивает и пишет localStorage ПО ЗАДАЧЕ', () => {
    render(<Collapsible id="psi" taskId="AH-2" title="ПСИ"><p>тело пси</p></Collapsible>)
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть раздел' }))
    expect(screen.queryByText('тело пси')).toBeNull()
    const map = JSON.parse(localStorage.getItem('task-ui:AH-2') ?? '{}') as Record<string, boolean>
    expect(map.psi).toBe(false)
    // другая задача не затронута
    const other = JSON.parse(localStorage.getItem('task-ui:AH-1') ?? '{}') as Record<string, boolean>
    expect(other.psi).toBeUndefined()
  })

  it('состояние восстанавливается из localStorage своей задачи', () => {
    localStorage.setItem('task-ui:AH-3', JSON.stringify({ chronicle: false }))
    render(<Collapsible id="chronicle" taskId="AH-3" title="Хроники"><p>тело хроник</p></Collapsible>)
    expect(screen.queryByText('тело хроник')).toBeNull()
  })

  it('кнопки в right-слоте не сворачивают раздел', () => {
    render(
      <Collapsible id="relations" taskId="AH-4" title="Связи" right={<button onClick={() => {}}>＋ связь</button>}>
        <p>тело связей</p>
      </Collapsible>,
    )
    fireEvent.click(screen.getByText('＋ связь'))
    expect(screen.getByText('тело связей')).toBeTruthy()
  })
})

describe('clampDrawerWidth', () => {
  it('держит ширину в границах [420, окно−80]', () => {
    expect(clampDrawerWidth(300)).toBe(420)
    expect(clampDrawerWidth(1200)).toBe(window.innerWidth - 80)
    expect(clampDrawerWidth(700)).toBe(700)
  })
})
