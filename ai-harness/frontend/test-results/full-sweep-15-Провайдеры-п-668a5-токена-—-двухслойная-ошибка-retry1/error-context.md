# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-sweep.spec.ts >> 15 Провайдеры: пресеты подставляют URL; check невалидного токена — двухслойная ошибка
- Location: e2e/full-sweep.spec.ts:172:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.fill: Test timeout of 30000ms exceeded.
Call log:
  - waiting for locator('.prov-form input[placeholder="название"]')

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - complementary [ref=e4]:
    - 'generic "Сборка: a54ce8b" [ref=e5]':
      - generic [ref=e9]:
        - generic [ref=e10]: AI-Harness
        - generic [ref=e11]: конвейер задач
    - button "Доска" [ref=e12] [cursor=pointer]
    - button "Список" [ref=e13] [cursor=pointer]
    - generic [ref=e14]: Проекты
    - button "AH AI Harness" [ref=e15] [cursor=pointer]:
      - generic [ref=e16]: AH
      - generic [ref=e17]: AI Harness
    - generic [ref=e18]:
      - generic [ref=e19]: Демон · тик 30 с · агенты на своих статусах
      - button "⚙ Настройки" [ref=e21] [cursor=pointer]
  - main [ref=e22]:
    - generic [ref=e23]:
      - heading "Настройки" [level=1] [ref=e24]
      - tablist "Вид" [ref=e25]:
        - button "Доска" [ref=e26] [cursor=pointer]
        - button "Список" [ref=e27] [cursor=pointer]
      - generic [ref=e28]:
        - searchbox "Поиск задач" [ref=e32]
        - generic [ref=e33]: поиск
      - generic "Активное подключение к ИИ-провайдеру" [ref=e34]: Подключение не настроено
      - group [ref=e36]:
        - generic "Уведомления" [ref=e37]: "16"
      - button "Переключить тему" [ref=e41] [cursor=pointer]: ☾
    - generic [ref=e42]:
      - generic [ref=e43]: ⚠
      - generic [ref=e44]: "Предупреждение — ИИ-провайдер не подключён: агенты конвейера не запустятся"
      - button "Перейти в настройки" [ref=e45] [cursor=pointer]
    - generic [ref=e46]:
      - generic [ref=e47]: ⚠
      - generic [ref=e48]: "Конвейер приостановлен — Путь проекта AH недоступен: конвейер приостановлен"
      - button "Перейти в настройки" [ref=e49] [cursor=pointer]
    - generic [ref=e50]:
      - tablist [ref=e51]:
        - button "Status-flow" [ref=e52] [cursor=pointer]
        - button "Проекты" [ref=e53] [cursor=pointer]
        - button "ИИ-провайдеры" [ref=e54] [cursor=pointer]
        - button "Агенты и матрица" [ref=e55] [cursor=pointer]
        - button "Очередь автомата" [ref=e56] [cursor=pointer]
        - button "Журнал настроек" [ref=e57] [cursor=pointer]
      - generic [ref=e60]:
        - generic [ref=e61]:
          - generic [ref=e62]: Подключения
          - generic [ref=e63]: Подключений пока нет
        - generic [ref=e64]:
          - generic [ref=e65]: Новое подключение
          - generic [ref=e66]:
            - generic [ref=e67]: Название
            - textbox [ref=e68]
          - generic [ref=e69]:
            - generic [ref=e70]: Пресет провайдера — подставит адрес, поле остаётся редактируемым
            - combobox [ref=e71]:
              - option "— выбрать пресет —" [selected]
              - option "Anthropic"
              - option "Groq"
              - option "Ollama"
              - option "OpenAI"
              - option "OpenRouter"
              - option "vLLM (локальный)"
          - generic [ref=e72]:
            - generic [ref=e73]: Протокол
            - combobox [ref=e74]:
              - option "Anthropic"
              - option "OpenAI-совместимый" [selected]
          - generic [ref=e75]:
            - generic [ref=e76]: URL
            - textbox [ref=e77]: https://api.openai.com/v1
          - generic [ref=e78]:
            - generic [ref=e79]: Модель
            - textbox [ref=e80]
          - generic [ref=e81]:
            - generic [ref=e82]: API-токен
            - textbox [ref=e83]
          - generic [ref=e84]:
            - button "Проверить" [ref=e85] [cursor=pointer]
            - button "Сохранить" [ref=e86] [cursor=pointer]
  - button "E Eve · помощник" [ref=e87] [cursor=pointer]:
    - generic [ref=e88]: E
    - text: Eve · помощник
  - region "Чат с Eve":
    - generic:
      - generic: E
      - generic:
        - generic: Eve
        - text: максимальные права, всё — с аудитом
      - button "Свернуть чат": —
    - generic:
      - text: "Контекст:"
      - generic: доска
      - generic: — вижу, какой экран открыт
    - generic: "Я Eve. Спросите или дайте задание: «переведи AH-3 на ревью», «почему AH-8 встала?», «создай задачу «Название»»."
    - generic:
      - button "Почему встала?"
      - button "Сводка по проекту"
    - generic:
      - textbox "Спросите или дайте задание… (Enter — отправить)"
      - button "Отправить"
```

# Test source

```ts
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
  149 |   await expect(page.locator('.tr-pop')).toBeVisible()
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
> 179 |   await page.locator('.prov-form input[placeholder="название"]').fill('e2e-conn')
      |                                                                  ^ Error: locator.fill: Test timeout of 30000ms exceeded.
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
  250 |   const res = await fetch('http://localhost:8088' + path)
  251 |   return res.json()
  252 | }
  253 | 
```