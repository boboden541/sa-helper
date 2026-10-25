// Vitest: round-trip markdown, парсер чеклистов, undo-стек (AC-5.3.2, ФТ-ah-9/71)

import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../shared/markdown'
import { parseChecklist, serializeChecklist } from '../shared/checklist'
import { lastUndoLabel, pushUndo, undoLast } from '../shared/undo'

describe('markdown round-trip', () => {
  it('заголовки 1–5 соответствуют уровням 1:1', () => {
    const md = ['# Один', '## Два', '### Три', '#### Четыре', '##### Пять'].join('\n')
    const html = renderMarkdown(md)
    for (let level = 1; level <= 5; level++) {
      expect(html).toContain(`<h${level}>`)
    }
  })
  it('начертания, списки, таблица, код', () => {
    const html = renderMarkdown('**ж** *к* ~~зач~~ __под__ `код`\n\n- пункт\n\n| a | b |\n| - | - |\n| 1 | 2 |')
    expect(html).toContain('<strong>ж</strong>')
    expect(html).toContain('<em>к</em>')
    expect(html).toContain('<s>зач</s>')
    expect(html).toContain('<u>под</u>')
    expect(html).toContain('<code>код</code>')
    expect(html).toContain('<li>пункт</li>')
    expect(html).toContain('<table>')
  })
})

describe('checklist `- ~ x + !`', () => {
  it('парсит символы статусов и заголовки', () => {
    const lines = parseChecklist('# Заголовок\n- не начат\n~ в работе\nx закрыт\n+ сделан\n! упал')
    expect(lines[0]).toMatchObject({ kind: 'heading', level: 1 })
    expect(lines[1].status).toBe('todo')
    expect(lines[2].status).toBe('in_progress')
    expect(lines[3].status).toBe('closed')
    expect(lines[4].status).toBe('done')
    expect(lines[5].status).toBe('failed')
  })
  it('сериализация обратима', () => {
    const src = '## Раздел\n+ готов'
    expect(serializeChecklist(parseChecklist(src))).toBe(src)
  })
})

describe('undo', () => {
  it('глубина стека 50 и отмена последней', async () => {
    let undone = ''
    for (let i = 0; i < 55; i++) {
      pushUndo({ label: `оп-${i}`, undo: () => { undone = `оп-${i}` } })
    }
    expect(lastUndoLabel()).toBe('оп-54')
    expect(await undoLast()).toBe('оп-54')
    expect(undone).toBe('оп-54')
  })
})
