# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-sweep.spec.ts >> 13 Status-flow: поповер добавления перехода с «Кто запускает»
- Location: e2e/full-sweep.spec.ts:143:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('.tr-pop')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" locator('.tr-pop') with timeout 5000ms
  - waiting for locator('.tr-pop')

```

```yaml
- complementary:
  - img
  - text: AI-Harness конвейер задач
  - button "Доска"
  - button "Список"
  - text: Проекты
  - button "AH AI Harness"
  - text: Демон · тик 30 с · агенты на своих статусах
  - button "⚙ Настройки"
- main:
  - heading "Настройки" [level=1]
  - tablist "Вид":
    - button "Доска"
    - button "Список"
  - img
  - searchbox "Поиск задач"
  - text: поиск Подключение не настроено
  - group:
    - img
    - text: "54"
  - button "Переключить тему": ☾
  - text: "⚠ Конвейер приостановлен — Путь проекта AH недоступен: конвейер приостановлен"
  - button "Перейти в настройки"
  - tablist:
    - button "Status-flow"
    - button "Проекты"
    - button "ИИ-провайдеры"
    - button "Агенты и матрица"
    - button "Очередь автомата"
    - button "Журнал настроек"
  - text: v3 · черновик
  - button "Сохранить черновик" [disabled]
  - button "Проверить"
  - button "Опубликовать"
  - button "Сбросить"
  - button "Истории"
  - button "Задачи"
  - button "QA"
  - button "Баги"
  - button "Анализ"
  - button "Граф"
  - button "Таблица"
  - button "＋ статус"
  - text: 11 статусов · 29 переходов
  - table:
    - rowgroup:
      - row "Статус Что происходит на этапе Чеклист-гейт Возможные переходы Alias-колонка":
        - columnheader "Статус"
        - columnheader "Что происходит на этапе"
        - columnheader "Чеклист-гейт"
        - columnheader "Возможные переходы"
        - columnheader "Alias-колонка"
        - columnheader
    - rowgroup:
      - row "В бэклоге backlog — → К работе ✕ → Отменено ✕ ＋ Бэклог ✕":
        - cell "В бэклоге backlog"
        - cell
        - cell "—"
        - cell "→ К работе ✕ → Отменено ✕ ＋":
          - text: → К работе
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "Бэклог"
        - cell "✕":
          - button "✕"
      - row "Заблокировано blocked — → В работе ✕ → На ревью ✕ → На тестировании ✕ → Отменено ✕ ＋ Заблокировано ✕":
        - cell "Заблокировано blocked"
        - cell
        - cell "—"
        - cell "→ В работе ✕ → На ревью ✕ → На тестировании ✕ → Отменено ✕ ＋":
          - text: → В работе
          - button "✕"
          - text: → На ревью
          - button "✕"
          - text: → На тестировании
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "Заблокировано"
        - cell "✕":
          - button "✕"
      - row "Отменено canceled — ＋ Отменено ✕":
        - cell "Отменено canceled"
        - cell
        - cell "—"
        - cell "＋":
          - button "＋" [disabled]
        - cell "Отменено"
        - cell "✕":
          - button "✕"
      - row "Готово done — ＋ Готово ✕":
        - cell "Готово done"
        - cell
        - cell "—"
        - cell "＋":
          - button "＋" [disabled]
        - cell "Готово"
        - cell "✕":
          - button "✕"
      - row "В работе in_progress чеклист разработчика → Готово к ревью ✕ → Заблокировано ✕ → Отменено ✕ ＋ В работе ✕":
        - cell "В работе in_progress"
        - cell
        - cell "чеклист разработчика"
        - cell "→ Готово к ревью ✕ → Заблокировано ✕ → Отменено ✕ ＋":
          - text: → Готово к ревью
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "В работе"
        - cell "✕":
          - button "✕"
      - row "На ревью in_review чеклист ревьюера → В работе ✕ → Готово к тестированию ✕ → Заблокировано ✕ → Отменено ✕ ＋ На ревью ✕":
        - cell "На ревью in_review"
        - cell
        - cell "чеклист ревьюера"
        - cell "→ В работе ✕ → Готово к тестированию ✕ → Заблокировано ✕ → Отменено ✕ ＋":
          - text: → В работе
          - button "✕"
          - text: → Готово к тестированию
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "На ревью"
        - cell "✕":
          - button "✕"
      - row "На тестировании in_testing чеклист тестировщика → Готово ✕ → В работе ✕ → Заблокировано ✕ → Отменено ✕ ＋ На тестировании ✕":
        - cell "На тестировании in_testing"
        - cell
        - cell "чеклист тестировщика"
        - cell "→ Готово ✕ → В работе ✕ → Заблокировано ✕ → Отменено ✕ ＋":
          - text: → Готово
          - button "✕"
          - text: → В работе
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "На тестировании"
        - cell "✕":
          - button "✕"
      - row "На рассмотрении pending — → В бэклоге ✕ → Отменено ✕ ＋ На рассмотрении ✕":
        - cell "На рассмотрении pending"
        - cell
        - cell "—"
        - cell "→ В бэклоге ✕ → Отменено ✕ ＋":
          - text: → В бэклоге
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "На рассмотрении"
        - cell "✕":
          - button "✕"
      - row "Готово к тестированию qa_ready — → На тестировании ✕ → Заблокировано ✕ → Отменено ✕ ＋ На тестировании ✕":
        - cell "Готово к тестированию qa_ready"
        - cell
        - cell "—"
        - cell "→ На тестировании ✕ → Заблокировано ✕ → Отменено ✕ ＋":
          - text: → На тестировании
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "На тестировании"
        - cell "✕":
          - button "✕"
      - row "Готово к ревью review_ready — → На ревью ✕ → Заблокировано ✕ → Отменено ✕ ＋ На ревью ✕":
        - cell "Готово к ревью review_ready"
        - cell
        - cell "—"
        - cell "→ На ревью ✕ → Заблокировано ✕ → Отменено ✕ ＋":
          - text: → На ревью
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - text: → Отменено
          - button "✕"
          - button "＋"
        - cell "На ревью"
        - cell "✕":
          - button "✕"
      - row "К работе todo — → В работе ✕ → В бэклоге ✕ → Отменено ✕ → Заблокировано ✕ ＋ К работе ✕":
        - cell "К работе todo"
        - cell
        - cell "—"
        - cell "→ В работе ✕ → В бэклоге ✕ → Отменено ✕ → Заблокировано ✕ ＋":
          - text: → В работе
          - button "✕"
          - text: → В бэклоге
          - button "✕"
          - text: → Отменено
          - button "✕"
          - text: → Заблокировано
          - button "✕"
          - button "＋"
        - cell "К работе"
        - cell "✕":
          - button "✕"
- button "E Eve · помощник"
- region "Чат с Eve":
  - text: E Eve максимальные права, всё — с аудитом
  - button "Свернуть чат": —
  - text: "Контекст: доска — вижу, какой экран открыт Я Eve. Спросите или дайте задание: «переведи AH-3 на ревью», «почему AH-8 встала?», «создай задачу «Название»»."
  - button "Почему встала?"
  - button "Сводка по проекту"
  - textbox "Спросите или дайте задание… (Enter — отправить)"
  - button "Отправить":
    - img
```

# Test source

```ts
  49  |   await expect(page.locator('.drawer.show .task-head .tcode')).toBeVisible()
  50  |   await expect(page.locator('.drawer.show .meta-row')).toBeVisible()
  51  |   await expect(page.locator('.drawer.show .card-tags .tag').first()).toBeVisible()
  52  |   await expect(page.locator('.drawer.show .desc-view .md')).toBeVisible()
  53  |   await expect(page.locator('.drawer.show .chron-tabs')).toBeVisible()
  54  |   await expect(page.locator('.drawer.show details.force')).toBeVisible()
  55  |   expectNo500s()
  56  | })
  57  | 
  58  | test('05 Карточка: смена приоритета через prio-menu → PATCH → хроника «поле»', async ({ page }) => {
  59  |   await page.locator('.card', { hasText: 'Экспорт отчёта' }).first().click()
  60  |   const code = await page.locator('.drawer.show .tcode').textContent()
  61  |   await page.locator('.drawer.show .meta-row .pop > button').click()
  62  |   await page.locator('.prio-menu button', { hasText: 'Критический' }).click()
  63  |   await page.waitForTimeout(400)
  64  |   const chron = await api(`/api/v1/tasks/${code?.trim()}/chronicle`)
  65  |   expect((chron.items ?? []).some((c: { type: string; message: string }) =>
  66  |     c.type === 'field' && c.message.includes('приоритет'))).toBeTruthy()
  67  | })
  68  | 
  69  | test('06 Карточка: правка описания через markdown → сохранение → рендер', async ({ page }) => {
  70  |   await page.locator('.card').first().click()
  71  |   await page.locator('.drawer.show .blk-h .pencil.show').first().click()
  72  |   await page.locator('.desc-edit .mode-tabs button', { hasText: 'Markdown' }).click()
  73  |   await page.locator('.desc-edit textarea').fill('## E2E описание\n- пункт один')
  74  |   await page.locator('.desc-edit .edit-actions button', { hasText: 'Сохранить' }).click()
  75  |   await expect(page.locator('.drawer.show .md h2')).toContainText('E2E описание')
  76  | })
  77  | 
  78  | test('07 Карточка: чек-лист разработчика — создать, текстовый режим, статусы', async ({ page }) => {
  79  |   await page.locator('.card', { hasText: 'Профиль пользователя' }).first().click()
  80  |   const blk = page.locator('.blk', { hasText: 'разработчика' }).first()
  81  |   await blk.locator('.cl-add input').fill('шаг один')
  82  |   await blk.locator('.cl-add input').press('Enter')
  83  |   await expect(blk.locator('.cl-row', { hasText: 'шаг один' })).toBeVisible()
  84  |   await blk.locator('.pencil[title*="Текстовый режим"]').click()
  85  |   await expect(blk.locator('.cl-text textarea')).toBeVisible()
  86  | })
  87  | 
  88  | test('08 Карточка: форс-переход без причины невозможен, с причиной — работает', async ({ page }) => {
  89  |   const created = await api('/api/v1/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  90  |     body: JSON.stringify({ projectId: 'AH', type: 'common_task', title: 'E2E форс ' + Date.now(),
  91  |       priority: 'medium', authorTag: 'by_human' }) })
  92  |   const code = created.code ?? created.code
  93  |   await page.goto(`http://localhost:8088/#${code}`)
  94  |   await page.waitForSelector('.drawer.show .force')
  95  |   await page.locator('.drawer.show .force summary').click()
  96  |   await expect(page.locator('.drawer.show .force .fr button')).toBeDisabled()
  97  |   await page.locator('.drawer.show .force textarea').fill('e2e форс')
  98  |   await page.locator('.drawer.show .force select').selectOption('blocked')
  99  |   await page.locator('.drawer.show .force .fr button').click()
  100 |   await expect(page.locator('.drawer.show .callout.bad')).toBeVisible()
  101 | })
  102 | 
  103 | test('09 Диалог создания: создание задачи → pending + уведомление', async ({ page }) => {
  104 |   await page.locator('.filters button', { hasText: '＋ Задача' }).click()
  105 |   await page.locator('.modal-card input').first().fill('AH')
  106 |   await page.locator('.modal-card input').nth(1).fill('E2E созданная задача')
  107 |   await page.locator('.modal-card select').nth(1).selectOption('high')
  108 |   await page.locator('.modal-card button', { hasText: 'Создать' }).click()
  109 |   await expect(page.locator('.modal-card')).toBeHidden()
  110 |   await page.locator('.icon-btn[aria-label="Уведомления"]').click()
  111 |   await expect(page.locator('.notif', { hasText: 'модерации' }).first()).toBeVisible()
  112 | })
  113 | 
  114 | test('10 Список: таблица задач, клик открывает карточку', async ({ page }) => {
  115 |   await page.locator('.seg button', { hasText: 'Список' }).click()
  116 |   await expect(page.locator('table.tasks tbody tr').first()).toBeVisible()
  117 | })
  118 | 
  119 | test('11 Eve: фраза → намерение → «да» → переход применён', async ({ page }) => {
  120 |   await page.locator('.eve-btn').click()
  121 |   await page.locator('.eve-input textarea').fill('переведи AH-7 в бэклог')
  122 |   await page.locator('.eve-input textarea').press('Enter')
  123 |   await expect(page.locator('.intent')).toBeVisible({ timeout: 8000 })
  124 |   await page.locator('.intent .ia button', { hasText: 'Да' }).click()
  125 |   await page.waitForTimeout(600)
  126 |   const card = await api('/api/v1/tasks/AH-7')
  127 |   expect(card.statusKey).toBe('backlog')
  128 | })
  129 | 
  130 | test('12 Настройки Status-flow: граф (fs-card), переключение на таблицу (6 колонок)', async ({ page }) => {
  131 |   await page.goto('http://localhost:8088/#settings/flow')
  132 |   await page.waitForSelector('.set-tabs')
  133 | 
  134 |   await expect(page.locator('.fs-card').first()).toBeVisible()
  135 |   await expect(page.locator('.flow-toolbar .seg button.active')).toContainText('Задачи')
  136 |   await page.locator('.mode-tabs button', { hasText: 'Таблица' }).click()
  137 |   await expect(page.locator('.flow-canvas.flow-table table th', { hasText: 'Кто работает' })).toBeVisible()
  138 |   await expect(page.locator('.flow-canvas.flow-table table th', { hasText: 'Alias-колонка' })).toBeVisible()
  139 |   const chip = page.locator('.tr-chip').first()
  140 |   await expect(chip).toContainText('→')
  141 | })
  142 | 
  143 | test('13 Status-flow: поповер добавления перехода с «Кто запускает»', async ({ page }) => {
  144 |   await page.goto('http://localhost:8088/#settings/flow')
  145 |   await page.waitForSelector('.set-tabs')
  146 | 
  147 |   await page.locator('.mode-tabs button', { hasText: 'Таблица' }).click()
  148 |   await page.locator('.tr-cell button.btn.small').first().click()
> 149 |   await expect(page.locator('.tr-pop')).toBeVisible()
      |                                         ^ Error: expect(locator).toBeVisible() failed
  150 |   await expect(page.locator('.tr-pop select').nth(1)).toBeVisible()
  151 |   await page.locator('.tr-pop button', { hasText: 'Отмена' }).click()
  152 | })
  153 | 
  154 | test('14 Настройки Проекты: создание, архив, удаление — полный цикл', async ({ page }) => {
  155 |   await page.goto('http://localhost:8088/#settings/projects')
  156 |   await page.waitForSelector('.set-tabs')
  157 | 
  158 |   await page.locator('button', { hasText: '＋ Проект' }).click()
  159 |   await page.locator('.agent-editor input').nth(0).fill('E2E Проект')
  160 |   await page.locator('.agent-editor input').nth(1).fill('E2' + String(Date.now()).slice(-4))
  161 |   await page.locator('.agent-editor input').nth(2).fill('/tmp')
  162 |   await page.locator('.agent-editor button', { hasText: 'Сохранить' }).click()
  163 |   await expect(page.locator('.prov-row', { hasText: 'E2E Проект' })).toBeVisible()
  164 |   const row = page.locator('.prov-row', { hasText: 'E2E Проект' })
  165 |   await row.locator('button', { hasText: 'В архив' }).click()
  166 |   await expect(page.locator('.prov-row', { hasText: 'E2E Проект' })).toContainText('в архиве')
  167 |   await row.locator('button', { hasText: 'Удалить' }).click()
  168 |   await page.waitForTimeout(400)
  169 |   expect(await page.locator('.prov-row', { hasText: 'E2E Проект' }).count()).toBe(0)
  170 | })
  171 | 
  172 | test('15 Провайдеры: пресеты подставляют URL; check невалидного токена — двухслойная ошибка', async ({ page }) => {
  173 |   await page.goto('http://localhost:8088/#settings/providers')
  174 |   await page.waitForSelector('.prov-form')
  175 | 
  176 |   const presetSelect = page.locator('.prov-form select').first()
  177 |   await presetSelect.selectOption('OpenAI')
  178 |   await expect(page.locator('.prov-form input').nth(1)).toHaveValue('https://api.openai.com/v1')
  179 |   await page.locator('.prov-form input[placeholder="название"]').fill('e2e-conn')
  180 |   await page.locator('.prov-form input[placeholder="модель"]').fill('gpt-4o-mini')
  181 |   await page.locator('.prov-form input[placeholder="API-токен"]').fill('sk-invalid-e2e')
  182 |   await page.locator('.prov-form button', { hasText: 'Проверить' }).click()
  183 |   await expect(page.locator('.check-row.err')).toBeVisible({ timeout: 20000 })
  184 | })
  185 | 
  186 | test('16 Провайдеры: сохранение подключения с валидным токеном', async ({ page }) => {
  187 |   await page.goto('http://localhost:8088/#settings/providers')
  188 |   await page.waitForSelector('.prov-form')
  189 | 
  190 |   const uniq = String(Date.now()).slice(-6)
  191 |   await page.locator('.prov-form input[placeholder="название"]').fill('e2e-anthropic-' + uniq)
  192 |   await page.locator('.prov-form select').first().selectOption('anthropic')
  193 |   await page.locator('.prov-form input[placeholder="URL"]').fill('https://api.anthropic.com')
  194 |   await page.locator('.prov-form input[placeholder="модель"]').fill('claude-sonnet-5')
  195 |   await page.locator('.prov-form input[placeholder="API-токен"]').fill('sk-e2e-save-' + uniq)
  196 |   await page.locator('.prov-form button', { hasText: 'Сохранить' }).click()
  197 |   await expect(page.locator('.prov-row').filter({ hasText: uniq })).toBeVisible()
  198 | })
  199 | 
  200 | test('17 Агенты: сетка 7 предустановленных, клонирование', async ({ page }) => {
  201 |   await page.goto('http://localhost:8088/#settings/agents')
  202 |   await page.waitForSelector('.agents-grid')
  203 | 
  204 |   await expect(page.locator('.agent-card').nth(6)).toBeVisible()
  205 |   await page.locator('.agent-card button', { hasText: 'клонировать' }).first().click()
  206 |   await expect(page.locator('.agent-card', { hasText: '(копия)' }).first()).toBeVisible()
  207 | })
  208 | 
  209 | test('18 Матрица: чекбоксы-поповер, человек на backlog → 200', async ({ page }) => {
  210 |   await page.goto('http://localhost:8088/#settings/agents')
  211 |   await page.waitForSelector('table.mx')
  212 | 
  213 |   await page.locator('.q-sec', { hasText: 'Матрица' }).waitFor()
  214 |   const cell = page.locator('table.mx .ag-cell').nth(1)
  215 |   await cell.locator('button', { hasText: 'назначить' }).click()
  216 |   await expect(cell.locator('.ag-pop')).toBeVisible()
  217 |   const checkboxes = cell.locator('.ag-pop input[type="checkbox"]')
  218 |   expect(await checkboxes.count()).toBeGreaterThanOrEqual(5)
  219 | })
  220 | 
  221 | test('19 Очередь и Журнал: рендерятся', async ({ page }) => {
  222 |   await page.goto('http://localhost:8088/#settings/queue')
  223 |   await page.waitForSelector('.q-sec')
  224 | 
  225 |   await expect(page.locator('.set-body .q-sec').first()).toBeVisible()
  226 |   await page.goto('http://localhost:8088/#settings/journal')
  227 |   await page.waitForSelector('.set-body')
  228 |   await expect(page.locator('.set-tab.active')).toContainText('Журнал')
  229 | })
  230 | 
  231 | test('20 Deep links и темы: #list, #dark, #settings/flow, #eve', async ({ page }) => {
  232 |   await page.goto('http://localhost:8088/#list')
  233 |   await expect(page.locator('table.tasks')).toBeVisible()
  234 |   await page.goto('http://localhost:8088/#dark')
  235 |   await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  236 |   await page.goto('http://localhost:8088/#settings/flow')
  237 |   await expect(page.locator('.set-tab.active')).toContainText('Status-flow')
  238 | })
  239 | 
  240 | test('21 Полный прогон без 5xx от backend', async ({ page }) => {
  241 |   for (const tab of ['flow', 'projects', 'providers', 'agents', 'queue', 'journal']) {
  242 |     await page.goto(`http://localhost:8088/#settings/${tab}`)
  243 |     await page.waitForSelector('.set-body')
  244 |     await page.waitForTimeout(400)
  245 |   }
  246 |   expectNo500s()
  247 | })
  248 | 
  249 | async function api(path: string): Promise<Record<string, unknown>> {
```