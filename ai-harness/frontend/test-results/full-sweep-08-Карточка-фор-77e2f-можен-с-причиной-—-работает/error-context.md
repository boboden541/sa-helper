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
        - generic "Уведомления" [ref=e37]: "30"
      - button "Переключить тему" [ref=e41] [cursor=pointer]: ☾
    - generic [ref=e42]:
      - generic [ref=e43]: ⚠
      - generic [ref=e44]: "Конвейер приостановлен — Путь проекта AH недоступен: конвейер приостановлен"
      - button "Перейти в настройки" [ref=e45] [cursor=pointer]
    - group "Фильтр по типу задачи" [ref=e46]:
      - button "Все" [ref=e47] [cursor=pointer]
      - button "Истории" [ref=e48] [cursor=pointer]
      - button "Задачи" [ref=e49] [cursor=pointer]
      - button "QA" [ref=e50] [cursor=pointer]
      - button "Баги" [ref=e51] [cursor=pointer]
      - button "Анализ" [ref=e52] [cursor=pointer]
      - generic [ref=e53]: 40 задач
      - button "＋ Задача" [ref=e54] [cursor=pointer]
    - region "Kanban-доска" [ref=e56]:
      - generic [ref=e57]:
        - generic [ref=e58]:
          - generic [ref=e60]: На рассмотрении
          - generic [ref=e61]: "16"
        - generic [ref=e62]:
          - generic [ref=e64]: Бэклог
          - generic [ref=e65]: "4"
        - generic [ref=e66]:
          - generic [ref=e68]: К работе
          - generic [ref=e69]: "1"
        - generic [ref=e70]:
          - generic [ref=e72]: В работе
          - generic [ref=e73]: "7"
        - generic [ref=e74]:
          - generic [ref=e76]: На ревью
          - generic [ref=e77]: "0"
        - generic [ref=e78]:
          - generic [ref=e80]: На тестировании
          - generic [ref=e81]: "0"
        - generic [ref=e82]:
          - generic [ref=e84]: Готово
          - generic [ref=e85]: "0"
        - generic [ref=e86]:
          - generic [ref=e88]: Отменено
          - generic [ref=e89]: "11"
        - generic [ref=e90]:
          - generic [ref=e92]: Заблокировано
          - generic [ref=e93]: "0"
        - generic "История движется автоматически по правилам M1–M6" [ref=e95] [cursor=pointer]:
          - button "Свернуть историю" [ref=e96]
          - generic [ref=e99]: AH-1
          - generic [ref=e100]: Сквозной смок
          - generic [ref=e101]: Отменено
          - generic [ref=e104]: 0/0 задач
          - 'generic "Приоритет: Высокий" [ref=e106]'
        - generic "История движется автоматически по правилам M1–M6" [ref=e120] [cursor=pointer]:
          - button "Свернуть историю" [ref=e121]
          - generic [ref=e124]: AH-2
          - generic [ref=e125]: Личный кабинет клиента
          - generic [ref=e126]: Отменено
          - generic [ref=e129]: 0/0 задач
          - 'generic "Приоритет: Высокий" [ref=e131]'
        - generic [ref=e144]:
          - generic [ref=e145]:
            - generic [ref=e146]: Без истории
            - generic [ref=e147]: 38 задач
          - generic [ref=e148]:
            - generic [ref=e149]:
              - article [ref=e151]:
                - generic [ref=e152]:
                  - generic [ref=e153]: AH-25
                  - generic [ref=e154]: Задача
                  - 'generic "Приоритет: Средний" [ref=e155]'
                - generic [ref=e158]: E2E DnD 1793005422733
              - article [ref=e160]:
                - generic [ref=e161]:
                  - generic [ref=e162]: AH-26
                  - generic [ref=e163]: Задача
                  - 'generic "Приоритет: Средний" [ref=e164]'
                - generic [ref=e167]: E2E DnD deny 1793005428753
              - article [ref=e169]:
                - generic [ref=e170]:
                  - generic [ref=e171]: AH-27
                  - generic [ref=e172]: Задача
                  - 'generic "Приоритет: Средний" [ref=e173]'
                - generic [ref=e176]: E2E DnD 1793005473240
              - article [ref=e178]:
                - generic [ref=e179]:
                  - generic [ref=e180]: AH-28
                  - generic [ref=e181]: Задача
                  - 'generic "Приоритет: Средний" [ref=e182]'
                - generic [ref=e185]: E2E DnD deny 1793005479017
              - article [ref=e187]:
                - generic [ref=e188]:
                  - generic [ref=e189]: AH-29
                  - generic [ref=e190]: Задача
                  - 'generic "Приоритет: Средний" [ref=e191]'
                - generic [ref=e194]: DBG DnD
              - article [ref=e196]:
                - generic [ref=e197]:
                  - generic [ref=e198]: AH-31
                  - generic [ref=e199]: Задача
                  - 'generic "Приоритет: Средний" [ref=e200]'
                - generic [ref=e203]: E2E DnD 1793005669375
              - article [ref=e205]:
                - generic [ref=e206]:
                  - generic [ref=e207]: AH-32
                  - generic [ref=e208]: Задача
                  - 'generic "Приоритет: Средний" [ref=e209]'
                - generic [ref=e212]: E2E DnD deny 1793005675318
              - article [ref=e214]:
                - generic [ref=e215]:
                  - generic [ref=e216]: AH-33
                  - generic [ref=e217]: Задача
                  - 'generic "Приоритет: Средний" [ref=e218]'
                - generic [ref=e221]: E2E DnD 1793006805710
              - article [ref=e223]:
                - generic [ref=e224]:
                  - generic [ref=e225]: AH-34
                  - generic [ref=e226]: Задача
                  - 'generic "Приоритет: Средний" [ref=e227]'
                - generic [ref=e230]: E2E DnD deny 1793006811670
              - article [ref=e232]:
                - generic [ref=e233]:
                  - generic [ref=e234]: AH-35
                  - generic [ref=e235]: Задача
                  - 'generic "Приоритет: Средний" [ref=e236]'
                - generic [ref=e239]: E2E DnD 1793006854952
              - article [ref=e241]:
                - generic [ref=e242]:
                  - generic [ref=e243]: AH-36
                  - generic [ref=e244]: Задача
                  - 'generic "Приоритет: Средний" [ref=e245]'
                - generic [ref=e248]: E2E DnD deny 1793006860833
              - article [ref=e250]:
                - generic [ref=e251]:
                  - generic [ref=e252]: AH-38
                  - generic [ref=e253]: Задача
                  - 'generic "Приоритет: Средний" [ref=e254]'
                - generic [ref=e257]: E2E DnD deny 1793006951440
              - article [ref=e259]:
                - generic [ref=e260]:
                  - generic [ref=e261]: AH-40
                  - generic [ref=e262]: Задача
                  - 'generic "Приоритет: Средний" [ref=e263]'
                - generic [ref=e266]: E2E DnD deny 1793007009631
              - article [ref=e268]:
                - generic [ref=e269]:
                  - generic [ref=e270]: AH-17
                  - generic [ref=e271]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e272]'
                - generic [ref=e275]: E2E созданная задача
              - article [ref=e277]:
                - generic [ref=e278]:
                  - generic [ref=e279]: AH-20
                  - generic [ref=e280]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e281]'
                - generic [ref=e284]: Свип отладка
              - article [ref=e286]:
                - generic [ref=e287]:
                  - generic [ref=e288]: AH-9
                  - generic [ref=e289]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e290]'
                - generic [ref=e293]: E2E созданная задача
            - generic [ref=e294]:
              - article [ref=e296]:
                - generic [ref=e297]:
                  - generic [ref=e298]: AH-30
                  - generic [ref=e299]: Задача
                  - 'generic "Приоритет: Средний" [ref=e300]'
                - generic [ref=e303]: DBG2
              - article [ref=e305]:
                - generic [ref=e306]:
                  - generic [ref=e307]: AH-37
                  - generic [ref=e308]: Задача
                  - 'generic "Приоритет: Средний" [ref=e309]'
                - generic [ref=e312]: E2E DnD 1793006950755
              - article [ref=e314]:
                - generic [ref=e315]:
                  - generic [ref=e316]: AH-39
                  - generic [ref=e317]: Задача
                  - 'generic "Приоритет: Средний" [ref=e318]'
                - generic [ref=e321]: E2E DnD 1793007008508
              - article [ref=e323]:
                - generic [ref=e324]:
                  - generic [ref=e325]: AH-7
                  - generic [ref=e326]: Задача
                  - 'generic "Приоритет: Критический" [ref=e327]'
                - generic [ref=e330]: Экспорт отчёта в Excell
            - article [ref=e333]:
              - generic [ref=e334]:
                - generic [ref=e335]: AH-5
                - generic [ref=e336]: Задача
                - 'generic "Приоритет: Средний" [ref=e337]'
              - generic [ref=e340]: Настройки уведомлений
            - generic [ref=e341]:
              - article [ref=e343]:
                - generic [ref=e344]:
                  - generic [ref=e345]: AH-3
                  - generic [ref=e346]: Задача
                  - 'generic "Приоритет: Средний" [ref=e347]'
                - generic [ref=e350]: Профиль пользователя
              - article [ref=e352]:
                - generic [ref=e353]:
                  - generic [ref=e354]: AH-6
                  - generic [ref=e355]: Баг
                  - 'generic "Приоритет: Критический" [ref=e356]'
                - generic [ref=e359]: Ошибка 500 при сохранении профиля
              - article [ref=e361]:
                - generic [ref=e362]:
                  - generic [ref=e363]: AH-18
                  - generic [ref=e364]: Задача
                  - 'generic "Приоритет: Критический" [ref=e365]'
                - generic [ref=e368]: Sweep переименована
              - article [ref=e370]:
                - generic [ref=e371]:
                  - generic [ref=e372]: AH-19
                  - generic [ref=e373]: Задача
                  - 'generic "Приоритет: Критический" [ref=e374]'
                - generic [ref=e377]: Sweep переименована
              - article [ref=e379]:
                - generic [ref=e380]:
                  - generic [ref=e381]: AH-21
                  - generic [ref=e382]: Задача
                  - 'generic "Приоритет: Критический" [ref=e383]'
                - generic [ref=e386]: Sweep переименована
              - article [ref=e388]:
                - generic [ref=e389]:
                  - generic [ref=e390]: AH-22
                  - generic [ref=e391]: Задача
                  - 'generic "Приоритет: Критический" [ref=e392]'
                - generic [ref=e395]: Sweep переименована
              - article [ref=e397]:
                - generic [ref=e398]:
                  - generic [ref=e399]: AH-23
                  - generic [ref=e400]: Задача
                  - 'generic "Приоритет: Критический" [ref=e401]'
                - generic [ref=e404]: Sweep переименована
              - article [ref=e406]:
                - generic [ref=e407]:
                  - generic [ref=e408]: AH-24
                  - generic [ref=e409]: Задача
                  - 'generic "Приоритет: Критический" [ref=e410]'
                - generic [ref=e413]: Sweep переименована
            - generic [ref=e417]:
              - article [ref=e419]:
                - generic [ref=e420]:
                  - generic [ref=e421]: AH-4
                  - generic [ref=e422]: Задача
                  - 'generic "Приоритет: Средний" [ref=e423]'
                - generic [ref=e426]: История заказов
              - article [ref=e428]:
                - generic [ref=e429]:
                  - generic [ref=e430]: AH-10
                  - generic [ref=e431]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e432]'
                - generic [ref=e435]: E2E созданная задача
              - article [ref=e437]:
                - generic [ref=e438]:
                  - generic [ref=e439]: AH-11
                  - generic [ref=e440]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e441]'
                - generic [ref=e444]: E2E созданная задача
              - article [ref=e446]:
                - generic [ref=e447]:
                  - generic [ref=e448]: AH-12
                  - generic [ref=e449]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e450]'
                - generic [ref=e453]: E2E созданная задача
              - article [ref=e455]:
                - generic [ref=e456]:
                  - generic [ref=e457]: AH-13
                  - generic [ref=e458]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e459]'
                - generic [ref=e462]: E2E созданная задача
              - article [ref=e464]:
                - generic [ref=e465]:
                  - generic [ref=e466]: AH-14
                  - generic [ref=e467]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e468]'
                - generic [ref=e471]: E2E созданная задача
              - article [ref=e473]:
                - generic [ref=e474]:
                  - generic [ref=e475]: AH-15
                  - generic [ref=e476]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e477]'
                - generic [ref=e480]: E2E созданная задача
              - article [ref=e482]:
                - generic [ref=e483]:
                  - generic [ref=e484]: AH-16
                  - generic [ref=e485]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e486]'
                - generic [ref=e489]: E2E созданная задача
              - article [ref=e491]:
                - generic [ref=e492]:
                  - generic [ref=e493]: AH-8
                  - generic [ref=e494]: Задача
                  - 'generic "Приоритет: Высокий" [ref=e495]'
                - generic [ref=e498]: Интеграция платежного шлюза
  - button "E Eve · помощник" [ref=e500] [cursor=pointer]:
    - generic [ref=e501]: E
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