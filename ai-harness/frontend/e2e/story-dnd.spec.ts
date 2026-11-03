import { test, expect } from '@playwright/test';

// Карточка САМОЙ истории должна быть на доске в своём лейне и ходить по flow
// (замечание владельца 03.11.2026, AH-138: история была только полосой-лейна —
// перетащить её по статусам было нечем; рёбра у истории при этом были).
const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8088';

test('DnD: карточка истории ходит по flow — «В работе» → «На рассмотрении»', async ({ page }) => {
  const res = await page.request.post(`${BASE}/api/v1/tasks`, {
    data: { projectId: 'AH', type: 'story', title: 'E2E story dnd ' + Date.now(),
      priority: 'medium', authorTag: 'by_human' },
  })
  const { code } = await res.json()
  // pending → todo → in_progress через API (рёбра story.yaml, человек)
  for (const to of ['todo', 'in_progress']) {
    const r = await page.request.post(`${BASE}/api/v1/tasks/${code}/transitions`, {
      data: { to },
    })
    expect((await r.json()).applied, `переход в ${to}`).toBeTruthy()
  }

  await page.goto(`${BASE}/`);
  await page.waitForSelector('.card', { timeout: 15000 });
  await page.waitForTimeout(1000);

  const card = page.locator(`.lane-cells .card[data-code="${code}"]`);
  await expect(card, 'карточка истории видна в своём лейне').toBeVisible();
  const target = page.locator('.lane', { has: page.locator(`.card[data-code="${code}"]`) })
    .locator('.cell[data-drop="На рассмотрении"]');
  await expect(target).toBeVisible();

  await card.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  let sb = await card.boundingBox();
  if (sb.y < 80) {
    // карточка под липким топбаром — крутим колесо над доской (грабля 03.11.2026)
    await page.mouse.move(sb.x + sb.width / 2, Math.max(sb.y + 120, 200));
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(300);
    sb = await card.boundingBox();
  }
  const tb = await target.boundingBox();
  // dnd-kit: промежуточные pointermove ≥ 4px (драйф сида, 30.10.2026)
  await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2);
  await page.mouse.down();
  await page.mouse.move(sb.x + sb.width / 2 + 10, sb.y + sb.height / 2, { steps: 3 });
  await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2, { steps: 10 });
  await page.waitForTimeout(200);
  await page.mouse.up();

  await expect.poll(async () => {
    const r = await page.request.get(`${BASE}/api/v1/tasks/${code}`);
    return (await r.json()).statusKey;
  }, { timeout: 8000 }).toBe('pending');
});
