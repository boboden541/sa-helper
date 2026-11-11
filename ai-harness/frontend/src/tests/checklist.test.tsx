// Vitest: чеклист не превращает ошибку загрузки в «пустой список» — правки
// при незагруженном состоянии не сохраняются (раньше PUT затирал реальный
// чеклист, анализ 11.11.2026). Тосты проверяем через состояние модуля
// (currentToasts) — надёжнее подмены модуля.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ChecklistBlock } from '../features/task-card/parts/ChecklistBlock'
import { currentToasts } from '../shared/toast'

const fetchCalls: { url: string; init?: RequestInit }[] = []

function mockFetch(ok: boolean) {
  fetchCalls.length = 0
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    fetchCalls.push({ url, init })
    const isGet = (init?.method ?? 'GET') === 'GET'
    const body = ok && isGet ? JSON.stringify({ items: [{ kind: 'item', text: 'пункт', status: 'todo' }] }) : ''
    return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body ? JSON.parse(body) : {}) })
  })
}

beforeEach(() => {
  cleanup()
  fetchCalls.length = 0
})

describe('ChecklistBlock', () => {
  it('ошибка загрузки → тост, сохранение заблокировано, PUT не уходит', async () => {
    mockFetch(false)
    render(<ChecklistBlock code="AH-1" kind="developer" title="План разработки" />)
    await waitFor(() =>
      expect(currentToasts().some((t) => t.text.includes('не загружен'))).toBe(true),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Текстовый режим' }))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: '- затирающий пункт' } })
    fireEvent.blur(ta)
    await waitFor(() =>
      expect(currentToasts().some((t) => t.text.includes('правки не сохраняются'))).toBe(true),
    )
    expect(fetchCalls.filter((c) => c.init?.method === 'PUT')).toHaveLength(0)
  })

  it('успешная загрузка рендерит пункты, правка сохраняется', async () => {
    mockFetch(true)
    render(<ChecklistBlock code="AH-2" kind="developer" title="План разработки" />)
    await waitFor(() => expect(screen.getByText('пункт')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Текстовый режим' }))
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: '- пункт\nx готовый' } })
    fireEvent.blur(ta)
    await waitFor(() => expect(fetchCalls.some((c) => c.init?.method === 'PUT')).toBe(true))
  })
})
