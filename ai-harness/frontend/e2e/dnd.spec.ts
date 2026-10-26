// DnD: перетаскивание карточки меняет статус (HTML5 drag, как в макете)
import { expect, test } from '@playwright/test'

test('DnD: карточка из «На рассмотрении» в «Бэклог» меняет статус', async ({ page }) => {
  // самодостаточно: создаём задачу в pending через API
  const res = await page.request.post('http://localhost:8088/api/v1/tasks', {
    data: { projectId: 'AH', type: 'common_task', title: 'E2E DnD ' + Date.now(),
      priority: 'medium', authorTag: 'by_human' },
  })
  const { code } = await res.json()
  await page.goto('http://localhost:8088/#board')
  const card = page.locator(`.lane-cells .card[data-code="${code}"]`)
  await expect(card).toBeVisible()
  const sourceCell = page.locator('.cell', { has: card })
  await expect(sourceCell).toHaveAttribute('data-drop', 'На рассмотрении')

  await card.dragTo(page.locator('.cell[data-drop="Бэклог"]').last())

  // статус применился (разрешённый переход backlog)
  await expect.poll(async () => {
    const r = await page.request.get(`http://localhost:8088/api/v1/tasks/${code}`)
    return (await r.json()).statusKey
  }, { timeout: 5000 }).toBe('backlog')
})

test('DnD: запрещённая колонка не принимает карточку', async ({ page }) => {
  const res = await page.request.post('http://localhost:8088/api/v1/tasks', {
    data: { projectId: 'AH', type: 'common_task', title: 'E2E DnD deny ' + Date.now(),
      priority: 'medium', authorTag: 'by_human' },
  })
  const { code } = await res.json()
  await page.goto('http://localhost:8088/#board')
  const card = page.locator(`.lane-cells .card[data-code="${code}"]`)
  await expect(card).toBeVisible()
  // pending → Готово запрещено (нет ребра)
  await card.dragTo(page.locator('.cell[data-drop="Готово"]').last())
  await expect.poll(async () => {
    const r = await page.request.get(`http://localhost:8088/api/v1/tasks/${code}`)
    return (await r.json()).statusKey
  }, { timeout: 5000 }).toBe('pending')
})
