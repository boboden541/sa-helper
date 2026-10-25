# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-sweep.spec.ts >> 08 Карточка: форс-переход без причины невозможен, с причиной — работает
- Location: e2e/full-sweep.spec.ts:88:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: page.waitForSelector: Test timeout of 30000ms exceeded.
Call log:
  - waiting for locator('.drawer.show .force') to be visible

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
      - heading "Доска задач" [level=1] [ref=e24]
      - tablist "Вид" [ref=e25]:
        - button "Доска" [ref=e26] [cursor=pointer]
        - button "Список" [ref=e27] [cursor=pointer]
      - generic [ref=e28]:
        - searchbox "Поиск задач" [ref=e32]
        - generic [ref=e33]: поиск
      - generic "Активное подключение к ИИ-провайдеру" [ref=e34]: Подключение не настроено
      - group [ref=e36]:
        - generic "Уведомления" [ref=e37]: "14"
      - button "Переключить тему" [ref=e41] [cursor=pointer]: ☾
    - group "Фильтр по типу задачи" [ref=e42]:
      - button "Все" [ref=e43] [cursor=pointer]
      - button "Истории" [ref=e44] [cursor=pointer]
      - button "Задачи" [ref=e45] [cursor=pointer]
      - button "QA" [ref=e46] [cursor=pointer]
      - button "Баги" [ref=e47] [cursor=pointer]
      - button "Анализ" [ref=e48] [cursor=pointer]
      - generic [ref=e49]: 15 задач
      - button "＋ Задача" [ref=e50] [cursor=pointer]
    - region "Kanban-доска" [ref=e51]:
      - generic [ref=e52]:
        - generic [ref=e53]:
          - generic [ref=e55]: На рассмотрении
          - generic [ref=e56]: "8"
        - generic [ref=e57]:
          - generic [ref=e59]: Бэклог
          - generic [ref=e60]: "1"
        - generic [ref=e61]:
          - generic [ref=e63]: К работе
          - generic [ref=e64]: "1"
        - generic [ref=e65]:
          - generic [ref=e67]: В работе
          - generic [ref=e68]: "2"
        - generic [ref=e69]:
          - generic [ref=e71]: На ревью
          - generic [ref=e72]: "0"
        - generic [ref=e73]:
          - generic [ref=e75]: На тестировании
          - generic [ref=e76]: "0"
        - generic [ref=e77]:
          - generic [ref=e79]: Готово
          - generic [ref=e80]: "0"
        - generic [ref=e81]:
          - generic [ref=e83]: Отменено
          - generic [ref=e84]: "1"
        - generic [ref=e85]:
          - generic [ref=e87]: Заблокировано
          - generic [ref=e88]: "2"
        - generic "История движется автоматически по правилам M1–M6" [ref=e90] [cursor=pointer]:
          - button "Свернуть историю" [ref=e91]
          - generic [ref=e94]: AH-1
          - generic [ref=e95]: Сквозной смок
          - generic [ref=e96]: На рассмотрении
          - generic [ref=e99]: 0/0 задач
          - 'generic "Приоритет: Высокий" [ref=e101]'
        - generic "История движется автоматически по правилам M1–M6" [ref=e115] [cursor=pointer]:
          - button "Свернуть историю" [ref=e116]
          - generic [ref=e119]: AH-2
          - generic [ref=e120]: Личный кабинет клиента
          - generic [ref=e121]: На рассмотрении
          - generic [ref=e124]: 0/0 задач
          - 'generic "Приоритет: Высокий" [ref=e126]'
        - generic [ref=e139]:
          - generic [ref=e140]:
            - generic [ref=e141]: Без истории
            - generic [ref=e142]: 13 задач
          - generic [ref=e143]:
            - generic [ref=e144]:
              - article [ref=e146]:
                - generic [ref=e147]:
                  - generic [ref=e148]: AH-11
                  - generic [ref=e149]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e150]'
                - generic [ref=e153]: E2E созданная задача
              - article [ref=e155]:
                - generic [ref=e156]:
                  - generic [ref=e157]: AH-12
                  - generic [ref=e158]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e159]'
                - generic [ref=e162]: E2E созданная задача
              - article [ref=e164]:
                - generic [ref=e165]:
                  - generic [ref=e166]: AH-13
                  - generic [ref=e167]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e168]'
                - generic [ref=e171]: E2E созданная задача
              - article [ref=e173]:
                - generic [ref=e174]:
                  - generic [ref=e175]: AH-14
                  - generic [ref=e176]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e177]'
                - generic [ref=e180]: E2E созданная задача
              - article [ref=e182]:
                - generic [ref=e183]:
                  - generic [ref=e184]: AH-15
                  - generic [ref=e185]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e186]'
                - generic [ref=e189]: E2E созданная задача
              - article [ref=e191]:
                - generic [ref=e192]:
                  - generic [ref=e193]: AH-9
                  - generic [ref=e194]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e195]'
                - generic [ref=e198]: E2E созданная задача
            - article [ref=e201]:
              - generic [ref=e202]:
                - generic [ref=e203]: AH-7
                - generic [ref=e204]: Задача
                - 'generic "Приоритет: Критический" [ref=e205]'
              - generic [ref=e208]: Экспорт отчёта в Excell
            - article [ref=e211]:
              - generic [ref=e212]:
                - generic [ref=e213]: AH-5
                - generic [ref=e214]: Задача
                - 'generic "Приоритет: Средний" [ref=e215]'
              - generic [ref=e218]: Настройки уведомлений
            - generic [ref=e219]:
              - article [ref=e221]:
                - generic [ref=e222]:
                  - generic [ref=e223]: AH-3
                  - generic [ref=e224]: Задача
                  - 'generic "Приоритет: Средний" [ref=e225]'
                - generic [ref=e228]: Профиль пользователя
              - article [ref=e230]:
                - generic [ref=e231]:
                  - generic [ref=e232]: AH-6
                  - generic [ref=e233]: Баг
                  - 'generic "Приоритет: Критический" [ref=e234]'
                - generic [ref=e237]: Ошибка 500 при сохранении профиля
            - article [ref=e243]:
              - generic [ref=e244]:
                - generic [ref=e245]: AH-4
                - generic [ref=e246]: Задача
                - 'generic "Приоритет: Средний" [ref=e247]'
              - generic [ref=e250]: История заказов
            - generic [ref=e251]:
              - article [ref=e253]:
                - generic [ref=e254]:
                  - generic [ref=e255]: AH-10
                  - generic [ref=e256]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e257]'
                - generic [ref=e260]: E2E созданная задача
                - generic [ref=e261]: "✕ Требуется человек:"
              - article [ref=e263]:
                - generic [ref=e264]:
                  - generic [ref=e265]: AH-8
                  - generic [ref=e266]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e267]'
                - generic [ref=e270]: Интеграция платежного шлюза
                - generic [ref=e271]: "✕ Требуется человек:"
  - button "E Eve · помощник" [ref=e272] [cursor=pointer]:
    - generic [ref=e273]: E
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
  1   | // Сквозной прогон всех экранов и элементов с проверкой backend-вызовов.
  2   | // Каждая ошибка сети (4xx/5xx) и каждый упавший чек фиксируются отчётом.
  3   | 
  4   | import { expect, test } from '@playwright/test'
  5   | 
  6   | const badResponses: { url: string; status: number }[] = []
  7   | 
  8   | test.beforeEach(async ({ page }) => {
  9   |   badResponses.length = 0
  10  |   page.on('response', (r) => {
  11  |     if (r.url().includes('/api/') && r.status() >= 400) {
  12  |       // 401 при проверке невалидного токена — ожидаемый сценарий двухслойной ошибки
  13  |       badResponses.push({ url: r.url().replace('http://localhost:8088', ''), status: r.status() })
  14  |     }
  15  |   })
  16  |   await page.goto('http://localhost:8088/#board')
  17  |   await page.waitForSelector('.card', { timeout: 10000 })
  18  | })
  19  | 
  20  | function expectNo500s() {
  21  |   const s500 = badResponses.filter((b) => b.status >= 500)
  22  |   expect(s500, 'backend 5xx: ' + JSON.stringify(s500)).toEqual([])
  23  | }
  24  | 
  25  | test('01 Доска: каркас, колонки, карточки, полосы историй, счётчики', async ({ page }) => {
  26  |   await expect(page.locator('.board-grid')).toBeVisible()
  27  |   expect(await page.locator('.col-head').count()).toBeGreaterThanOrEqual(9)
  28  |   await expect(page.locator('.lane-band').first()).toBeVisible()
  29  |   await expect(page.locator('.card').first()).toBeVisible()
  30  |   await expect(page.locator('.card .type-chip').first()).toBeVisible()
  31  |   await expect(page.locator('.card .prio').first()).toBeVisible()
  32  |   await expect(page.locator('.filters .chip-f').first()).toBeVisible()
  33  |   expectNo500s()
  34  | })
  35  | 
  36  | test('02 Доска: клик по карточке — site-page поверх доски', async ({ page }) => {
  37  |   await page.locator('.card').first().click()
  38  |   await expect(page.locator('.drawer.show')).toBeVisible()
  39  |   await expect(page.locator('.board-scroll')).toBeVisible()
  40  | })
  41  | 
  42  | test('03 Доска: клик по коду — полный экран', async ({ page }) => {
  43  |   await page.locator('.card .code').first().click()
  44  |   await expect(page.locator('.taskpage')).toBeVisible()
  45  | })
  46  | 
  47  | test('04 Карточка: 14 групп блоков, мета, теги, хроники', async ({ page }) => {
  48  |   await page.locator('.lane-band', { hasText: 'Личный кабинет' }).first().click()
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
> 94  |   await page.waitForSelector('.drawer.show .force')
      |              ^ Error: page.waitForSelector: Test timeout of 30000ms exceeded.
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
```