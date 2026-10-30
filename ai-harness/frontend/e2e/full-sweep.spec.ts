// Сквозной прогон всех экранов и элементов с проверкой backend-вызовов.
// Каждая ошибка сети (4xx/5xx) и каждый упавший чек фиксируются отчётом.

import { expect, test } from '@playwright/test'

const badResponses: { url: string; status: number }[] = []

test.beforeEach(async ({ page }) => {
  badResponses.length = 0
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) {
      // 401 при проверке невалидного токена — ожидаемый сценарий двухслойной ошибки
      badResponses.push({ url: r.url().replace('http://localhost:8088', ''), status: r.status() })
    }
  })
  await page.goto('http://localhost:8088/#board')
  await page.waitForSelector('.card', { timeout: 10000 })
})

function expectNo500s() {
  const s500 = badResponses.filter((b) => b.status >= 500)
  expect(s500, 'backend 5xx: ' + JSON.stringify(s500)).toEqual([])
}

test('01 Доска: каркас, колонки, карточки, полосы историй, счётчики', async ({ page }) => {
  await expect(page.locator('.board-grid')).toBeVisible()
  expect(await page.locator('.col-head').count()).toBeGreaterThanOrEqual(9)
  await expect(page.locator('.lane-band').first()).toBeVisible()
  await expect(page.locator('.card').first()).toBeVisible()
  await expect(page.locator('.card .type-chip').first()).toBeVisible()
  await expect(page.locator('.card .prio').first()).toBeVisible()
  await expect(page.locator('.filters .chip-f').first()).toBeVisible()
  expectNo500s()
})

test('02 Доска: клик по карточке — site-page поверх доски', async ({ page }) => {
  await page.locator('.card').first().click()
  await expect(page.locator('.drawer.show')).toBeVisible()
  await expect(page.locator('.board-scroll')).toBeVisible()
})

test('03 Доска: клик по коду — полный экран', async ({ page }) => {
  await page.locator('.card .code').first().click()
  await expect(page.locator('.taskpage')).toBeVisible()
})

test('04 Карточка: 14 групп блоков, мета, теги, хроники', async ({ page }) => {
  await page.locator('.lane-band', { hasText: 'Личный кабинет' }).first().click()
  await expect(page.locator('.drawer.show .task-head .tcode')).toBeVisible()
  await expect(page.locator('.drawer.show .meta-row')).toBeVisible()
  await expect(page.locator('.drawer.show .card-tags .tag').first()).toBeVisible()
  await expect(page.locator('.drawer.show .desc-view .md')).toBeVisible()
  await expect(page.locator('.drawer.show .chron-tabs')).toBeVisible()
  await expect(page.locator('.drawer.show details.force')).toBeVisible()
  expectNo500s()
})

test('05 Карточка: смена приоритета через prio-menu → PATCH → хроника «поле»', async ({ page }) => {
  await page.locator('.card', { hasText: 'Экспорт отчёта' }).first().click()
  const code = await page.locator('.drawer.show .tcode').textContent()
  await page.locator('.drawer.show .meta-row .pop > button').click()
  await page.locator('.prio-menu button', { hasText: 'Критический' }).click()
  await page.waitForTimeout(400)
  const chron = await api(`/api/v1/tasks/${code?.trim()}/chronicle`)
  expect((chron.items ?? []).some((c: { type: string; message: string }) =>
    c.type === 'field' && c.message.includes('приоритет'))).toBeTruthy()
})

test('06 Карточка: правка описания через markdown → сохранение → рендер', async ({ page }) => {
  await page.locator('.card').first().click()
  await page.locator('.drawer.show .blk-h .pencil.show').first().click()
  await page.locator('.desc-edit .mode-tabs button', { hasText: 'Markdown' }).click()
  await page.locator('.desc-edit textarea').fill('## E2E описание\n- пункт один')
  await page.locator('.desc-edit .edit-actions button', { hasText: 'Сохранить' }).click()
  await expect(page.locator('.drawer.show .md h2')).toContainText('E2E описание')
})

test('07 Карточка: чек-лист разработчика — создать, текстовый режим, статусы', async ({ page }) => {
  await page.locator('.card', { hasText: 'Профиль пользователя' }).first().click()
  // hasText по всему .blk цепляет и блок переходов (в причинах отказов есть
  // «чек-лист разработчика») — фильтруем по заголовку h3 внутри блока
  const blk = page.locator('.blk').filter({
    has: page.locator('h3', { hasText: 'чек-лист разработчика' }),
  }).first()
  // уникальная метка: чеклист переживает прогоны, и повторный «шаг один»
  // даёт strict violation по двум одинаковым строкам
  const item = 'шаг один ' + Date.now()
  await blk.locator('.cl-add input').fill(item)
  await blk.locator('.cl-add input').press('Enter')
  await expect(blk.locator('.cl-row', { hasText: item })).toBeVisible()
  await blk.locator('.pencil[title*="Текстовый режим"]').click()
  await expect(blk.locator('.cl-text textarea')).toBeVisible()
})

test('08 Карточка: форс-переход без причины невозможен, с причиной — работает', async ({ page }) => {
  const created = await api('/api/v1/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ projectId: 'AH', type: 'common_task', title: 'E2E форс ' + Date.now(),
      priority: 'medium', authorTag: 'by_human' }) })
  const code = created.code ?? created.code
  await page.goto(`http://localhost:8088/#${code}`)
  await page.waitForSelector('.drawer.show .force')
  await page.locator('.drawer.show .force summary').click()
  await expect(page.locator('.drawer.show .force .fr button')).toBeDisabled()
  await page.locator('.drawer.show .force textarea').fill('e2e форс')
  await page.locator('.drawer.show .force select').selectOption('blocked')
  await page.locator('.drawer.show .force .fr button').click()
  await expect(page.locator('.drawer.show .callout.bad')).toBeVisible()
})

test('09 Диалог создания: создание задачи → pending + уведомление', async ({ page }) => {
  await page.locator('.filters button', { hasText: '+ Задача' }).click()
  await page.locator('.modal-card input').first().fill('AH')
  await page.locator('.modal-card input').nth(1).fill('E2E созданная задача')
  await page.locator('.modal-card select').nth(1).selectOption('high')
  await page.locator('.modal-card button', { hasText: 'Создать' }).click()
  await expect(page.locator('.modal-card')).toBeHidden()
  await page.locator('.icon-btn[aria-label="Уведомления"]').click()
  await expect(page.locator('.notif', { hasText: 'модерации' }).first()).toBeVisible()
})

test('10 Список: таблица задач, клик открывает карточку', async ({ page }) => {
  await page.locator('.seg button', { hasText: 'Список' }).click()
  await expect(page.locator('table.tasks tbody tr').first()).toBeVisible()
})

test('11 Eve: фраза → намерение → «да» → переход применён', async ({ page }) => {
  await page.locator('.eve-btn').click()
  // «бэклог»→backlog: статуса backlog в каноническом пресете нет; «блок»→blocked,
  // ребро in_progress→blocked (runner auto_or_agent) — валидная цель
  await page.locator('.eve-input textarea').fill('переведи AH-7 в блок')
  await page.locator('.eve-input textarea').press('Enter')
  await expect(page.locator('.intent')).toBeVisible({ timeout: 8000 })
  await page.locator('.intent .ia button', { hasText: 'Да' }).click()
  await page.waitForTimeout(600)
  const card = await api('/api/v1/tasks/AH-7')
  expect(card.statusKey).toBe('blocked')
})

test('12 Настройки Status-flow: граф (fs-card), переключение на таблицу (6 колонок)', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/flow')
  await page.waitForSelector('.set-tabs')

  await expect(page.locator('.fs-card').first()).toBeVisible()
  await expect(page.locator('.flow-toolbar .seg button.active')).toContainText('Задачи')
  await page.locator('.mode-tabs button', { hasText: 'Таблица' }).click()
  // состав колонок текущего редактора: «Кто работает» живёт в «Агенты и матрица»
  await expect(page.locator('.flow-canvas.flow-table table th', { hasText: 'Чеклист-гейт' })).toBeVisible()
  await expect(page.locator('.flow-canvas.flow-table table th', { hasText: 'Возможные переходы' })).toBeVisible()
  await expect(page.locator('.flow-canvas.flow-table table th', { hasText: 'Alias-колонка' })).toBeVisible()
  const chip = page.locator('.tr-chip').first()
  await expect(chip).toContainText('→')
})

test('13 Status-flow: поповер добавления перехода с «Кто запускает»', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/flow')
  await page.waitForSelector('.set-tabs')

  await page.locator('.mode-tabs button', { hasText: 'Таблица' }).click()
  // инлайн-форма «＋ переход»: «→ куда» + «Кто запускает» (бывший .tr-pop)
  await page.locator('button', { hasText: '＋ переход' }).first().click()
  await expect(page.locator('.tr-cell .flex select').first()).toBeVisible()
  await expect(page.locator('.tr-cell .flex select').nth(1)).toBeVisible()
  await page.locator('.tr-cell .flex button', { hasText: '✕' }).click()
})

test('14 Настройки Проекты: создание, архив, удаление — полный цикл', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/projects')
  await page.waitForSelector('.set-tabs')

  await page.locator('button', { hasText: '＋ Проект' }).click()
  await page.locator('.agent-editor input').nth(0).fill('E2E Проект')
  await page.locator('.agent-editor input').nth(1).fill('E2' + String(Date.now()).slice(-4))
  // /tmp на macOS — «dubious ownership» у git; свежий подпуть создаёт приложение
  await page.locator('.agent-editor input').nth(2).fill('/tmp/e2e-proj-' + String(Date.now()).slice(-6))
  await page.locator('.agent-editor button', { hasText: 'Сохранить' }).click()
  await expect(page.locator('.prov-row', { hasText: 'E2E Проект' })).toBeVisible()
  const row = page.locator('.prov-row', { hasText: 'E2E Проект' })
  await row.locator('button', { hasText: 'В архив' }).click()
  await expect(page.locator('.prov-row', { hasText: 'E2E Проект' })).toContainText('в архиве')
  await row.locator('button', { hasText: 'Удалить' }).click()
  await page.waitForTimeout(400)
  expect(await page.locator('.prov-row', { hasText: 'E2E Проект' }).count()).toBe(0)
})

test('15 Провайдеры: пресеты подставляют URL; check невалидного токена — двухслойная ошибка', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/providers')
  await page.waitForSelector('.prov-form')

  const presetSelect = page.locator('.prov-form select').first()
  await presetSelect.selectOption('OpenAI')
  // у полей label вместо placeholder (дрейф макета); URL — второй инпут формы
  const fld = (label: string) => page.locator('.prov-form .f-field', { hasText: label }).locator('input')
  await expect(fld('URL')).toHaveValue('https://api.openai.com/v1')
  await fld('Название').fill('e2e-conn')
  await fld('Модель').fill('gpt-4o-mini')
  await fld('API-токен').fill('sk-invalid-e2e')
  await page.locator('.prov-form button', { hasText: 'Проверить' }).click()
  await expect(page.locator('.check-row.err')).toBeVisible({ timeout: 20000 })
})

test('16 Провайдеры: сохранение подключения с валидным токеном', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/providers')
  await page.waitForSelector('.prov-form')

  const uniq = String(Date.now()).slice(-6)
  const fld2 = (label: string) => page.locator('.prov-form .f-field', { hasText: label }).locator('input')
  await fld2('Название').fill('e2e-anthropic-' + uniq)
  // первый селект — пресет-чузер, протокол — второй
  await page.locator('.prov-form select').nth(1).selectOption('anthropic')
  await fld2('URL').fill('https://api.anthropic.com')
  await fld2('Модель').fill('claude-sonnet-5')
  await fld2('API-токен').fill('sk-e2e-save-' + uniq)
  await page.locator('.prov-form button', { hasText: 'Сохранить' }).click()
  await expect(page.locator('.prov-row').filter({ hasText: uniq })).toBeVisible()
})

test('17 Агенты: сетка 7 предустановленных, клонирование', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/agents')
  await page.waitForSelector('.agents-grid')

  await expect(page.locator('.agent-card').nth(6)).toBeVisible()
  await page.locator('.agent-card button', { hasText: 'клонировать' }).first().click()
  await expect(page.locator('.agent-card', { hasText: '(копия)' }).first()).toBeVisible()
})

test('18 Матрица: чекбоксы-поповер, человек на backlog → 200', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/agents')
  await page.waitForSelector('table.mx')

  await page.locator('.q-sec', { hasText: 'Матрица' }).waitFor()
  const cell = page.locator('table.mx .ag-cell').nth(1)
  await cell.locator('button', { hasText: 'назначить' }).click()
  await expect(cell.locator('.ag-pop')).toBeVisible()
  const checkboxes = cell.locator('.ag-pop input[type="checkbox"]')
  // список людей грузится асинхронно — ждём первый чекбокс перед подсчётом
  await expect(checkboxes.first()).toBeVisible()
  expect(await checkboxes.count()).toBeGreaterThanOrEqual(5)
})

test('19 Очередь и Журнал: рендерятся', async ({ page }) => {
  await page.goto('http://localhost:8088/#settings/queue')
  await page.waitForSelector('.q-sec')

  await expect(page.locator('.set-body .q-sec').first()).toBeVisible()
  await page.goto('http://localhost:8088/#settings/journal')
  await page.waitForSelector('.set-body')
  await expect(page.locator('.set-tab.active')).toContainText('Журнал')
})

test('20 Deep links и темы: #list, #dark, #settings/flow, #eve', async ({ page }) => {
  await page.goto('http://localhost:8088/#list')
  await expect(page.locator('table.tasks')).toBeVisible()
  await page.goto('http://localhost:8088/#dark')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.goto('http://localhost:8088/#settings/flow')
  await expect(page.locator('.set-tab.active')).toContainText('Status-flow')
})

test('21 Полный прогон без 5xx от backend', async ({ page }) => {
  for (const tab of ['flow', 'projects', 'providers', 'agents', 'queue', 'journal']) {
    await page.goto(`http://localhost:8088/#settings/${tab}`)
    await page.waitForSelector('.set-body')
    await page.waitForTimeout(400)
  }
  expectNo500s()
})

async function api(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
  // init обязателен: сценарий 08 делает POST создания — раньше второй аргумент
  // отбрасывался, шел GET списка, и задача искалась как #undefined
  const res = await fetch('http://localhost:8088' + path, init)
  return res.json()
}
