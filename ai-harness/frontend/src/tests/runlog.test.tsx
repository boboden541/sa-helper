// Vitest: панель «Прогоны» (RunLogPanel) честно различает «лог удалён
// хранением» и «Лог пуст.» — регресс бага 26.11.2026: чипы прогонов старше
// окна retention читались как сломанные (VITRINA-35).

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

// Первый vi.mock в тестах фронтенда: RunLogPanel ходит в api-клиент.
// jsdom без EventSource и scrollIntoView — панель без активного прогона
// поток не создаёт, но клик по чипу зовёт scrollIntoView через rAF.
vi.stubGlobal('EventSource', class {})
window.HTMLElement.prototype.scrollIntoView = () => {}
vi.stubGlobal('requestAnimationFrame', (cb: (t: number) => void) =>
  setTimeout(() => cb(0), 0) as unknown as number)

vi.mock('../api/client', () => {
  const mk = (id: string, logPruned: boolean) => ({
    id, attempt: 1, running: false, stale: false, outcome: 'success', agent: 'Тестировщик',
    startedAt: '2026-10-30T07:00:09.592282+00:00', heartbeatAt: null,
    finishedAt: '2026-10-30T07:41:11.057698+00:00', statusKey: 'in_testing',
    input: 1, output: 2, cache: 3, tokens: 6, logPruned, logRetentionDays: 7,
  })
  return {
    api: {
      runs: async () => [mk('old-run', true), mk('new-run', false)],
      runLog: async () => ({ items: [], last: 0 }),
      interrupt: async () => ({ ok: true }),
    },
  }
})

import { RunLogPanel } from '../features/task-card/RunLogPanel'

beforeEach(() => cleanup())

describe('RunLogPanel: лог удалён хранением ≠ Лог пуст', () => {
  it('прогон старше окна — тултип чипа и честное сообщение вместо «Лог пуст.»', async () => {
    render(<RunLogPanel code="VITRINA-35" />)
    // старый прогон выбран по умолчанию (последний в списке)
    expect(
      await screen.findByText('Лог удалён хранением: сырые строки хранятся 7 дн. Итог прогона — в хронике задачи.'),
    ).toBeTruthy()
    const chip = screen.getByTitle('Лог удалён хранением (7 дн.) — итог прогона в хронике задачи')
    expect(chip.className).toContain('rl-run')
  })

  it('свежий прогон без строк — по-прежнему «Лог пуст.»', async () => {
    render(<RunLogPanel code="VITRINA-35" />)
    await screen.findByText(/Лог удалён хранением/)
    fireEvent.click(screen.getByTitle('Показать лог прогона'))
    expect(await screen.findByText('Лог пуст.')).toBeTruthy()
    expect(screen.queryByText(/Лог удалён хранением/)).toBeNull()
  })
})
