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

  // Канонический пресет: статуса backlog в flow нет — перетаскиваем
  // «На рассмотрении» → «К работе» (ребро pending→todo, runner human)
  const target = page.locator('.cell[data-drop="К работе"]').last()
  // dnd-kit PointerSensor требует промежуточные pointermove с дистанцией ≥ 4px;
  // карточка может быть ниже вьюпорта — page.mouse работает в координатах
  // окна, без скролла pointerdown уходит мимо страницы (драйф сида, 30.10.2026)
  await card.scrollIntoViewIfNeeded()
  await target.scrollIntoViewIfNeeded()
  const sb = await card.boundingBox()
  const tb = await target.boundingBox()
  await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2)
  await page.mouse.down()
  await page.mouse.move(sb.x + sb.width / 2 + 10, sb.y + sb.height / 2, { steps: 3 })
  await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2, { steps: 10 })
  await page.waitForTimeout(200)
  await page.mouse.up()
  await expect.poll(async () => {
    const r = await page.request.get(`http://localhost:8088/api/v1/tasks/${code}`)
    return (await r.json()).statusKey
  }, { timeout: 8000 }).toBe('todo')
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
  // pending → Готово запрещено (нет ребра); скролл обязателен — см. выше
  await card.scrollIntoViewIfNeeded()
  const done = page.locator('.cell[data-drop="Готово"]').last()
  await done.scrollIntoViewIfNeeded()
  await card.dragTo(done)
  await expect.poll(async () => {
    const r = await page.request.get(`http://localhost:8088/api/v1/tasks/${code}`)
    return (await r.json()).statusKey
  }, { timeout: 5000 }).toBe('pending')
})
