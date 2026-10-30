// Сквозные пользовательские сценарии на живом стеке (vite preview + docker backend)
// Воспроизводят замечания владельца: site-page поверх доски, полный экран по коду,
// редактирование описания, текстовый режим чек-листа с карандашом макета.

import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.goto('/#board')
  await page.waitForSelector('.card', { timeout: 10000 })
})

test('клик по карточке — site-page ОТКРЫВАЕТСЯ ПОВЕРХ доски (доска не исчезает)', async ({ page }) => {
  await page.locator('.card').first().click()
  await expect(page.locator('.drawer.show')).toBeVisible()
  await expect(page.locator('.drawer .tcode')).toContainText(/^[A-Z]{2,10}-\d+$/)
  // доска осталась в DOM и видима позади
  await expect(page.locator('.board-scroll')).toBeVisible()
  await expect(page.locator('.col-head').first()).toBeVisible()
})

test('клик по коду задачи — открывается полный экран просмотра', async ({ page }) => {
  await page.locator('.card .code').first().click()
  await expect(page.locator('.taskpage')).toBeVisible()
  await expect(page.locator('.tp-head .crumb')).toContainText('полная страница')
  await expect(page.locator('.task-head .tcode')).toBeVisible()
})

test('редактирование описания: карандаш → правка → сохранение — путь не ломается', async ({ page }) => {
  await page.locator('.card').first().click()
  await page.locator('.drawer.show .blk-h .pencil.show').first().click()
  // markdown-режим: правка через textarea — детерминированно
  await page.locator('.desc-edit .mode-tabs button', { hasText: 'Markdown' }).click()
  const ta = page.locator('.desc-edit textarea')
  await ta.fill('# Проверка пути\n- правка через e2e')
  await page.locator('.desc-edit .edit-actions button', { hasText: 'Сохранить' }).click()
  await expect(page.locator('.drawer.show .md h1')).toContainText('Проверка пути')
  await expect(page.locator('.drawer.show .md li')).toContainText('правка через e2e')
})

test('чек-лист: карандаш макета открывает текстовый режим; строки парсятся', async ({ page }) => {
  // на свежом сиде первая карточка — история: чеклистов разработчика у неё нет
  await page.locator('.card', { hasText: 'Профиль пользователя' }).first().click()
  // фильтр по h3: hasText по .blk цепляет и блок переходов (причины отказов)
  const blk = page.locator('.blk').filter({
    has: page.locator('h3', { hasText: 'чек-лист разработчика' }),
  }).first()
  await blk.locator('.pencil[title*="Текстовый режим"]').click()
  await expect(blk.locator('.cl-text textarea')).toBeVisible()
  await blk.locator('.cl-text textarea').fill('# Этап\n- подготовить окружение\n~ вести тесты\n+ закрыть пункт')
  await blk.locator('.cl-text textarea').blur()
  await expect(blk.locator('.cl-row').first()).toBeVisible()
  await expect(blk.locator('.badge', { hasText: 'in_progress' })).toBeVisible()
})

test('возврат на доску из полной страницы', async ({ page }) => {
  await page.locator('.card .code').first().click()
  await expect(page.locator('.taskpage')).toBeVisible()
  await page.locator('.tp-head button', { hasText: 'К доске' }).click()
  await expect(page.locator('.board-scroll')).toBeVisible()
})
