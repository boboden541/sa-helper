// Round-trip редактора: markdown → HTML → markdown без потерь для набора §14 (AC-5.3.2)

import { describe, expect, it } from 'vitest'
import { htmlToMarkdown } from '../shared/editor/serialize'
import { renderMarkdown } from '../shared/markdown'

describe('md → html → md', () => {
  it('заголовки 1–5 не смещаются за цикл', () => {
    const md = ['# Один', '## Два', '### Три', '#### Четыре', '##### Пять'].join('\n')
    const back = htmlToMarkdown(renderMarkdown(md))
    expect(back.replace(/\n\n+/g, '\n')).toBe(md)
  })
  it('начертания и underline <u> сохраняются', () => {
    const md = '**ж** *к* ~~зач~~ <u>под</u> `код`'
    expect(htmlToMarkdown(renderMarkdown(md))).toContain('<u>под</u>')
    expect(htmlToMarkdown(renderMarkdown(md))).toContain('**ж**')
  })
  it('списки, цитата, таблица', () => {
    const md = '- раз\n- два\n\n> цитата\n\n| a | b |\n| --- | --- |\n| 1 | 2 |'
    const back = htmlToMarkdown(renderMarkdown(md))
    expect(back).toContain('- раз\n- два')
    expect(back).toContain('> цитата')
    expect(back).toContain('| a | b |')
    expect(back).toContain('| 1 | 2 |')
  })
})
