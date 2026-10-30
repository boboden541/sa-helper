// XSS-регрессии markdown-рендера (анализ 30.10.2026): ссылки/картинки без
// валидации схемы + кавычка не экранировалась — вырывание из href/src.
import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../shared/markdown'

describe('renderMarkdown — безопасность ссылок и картинок', () => {
  it('javascript: не становится ссылкой', () => {
    const html = renderMarkdown('[клик](javascript:alert(1))')
    expect(html).not.toContain('<a ')
    expect(html).toContain('клик')
  })

  it('data: и vbscript: тоже отсечены', () => {
    expect(renderMarkdown('[x](data:text/html,<b>)')).not.toContain('<a ')
    expect(renderMarkdown('[x](vbscript:x)')).not.toContain('<a ')
    expect(renderMarkdown('![x](javascript:alert(1))')).not.toContain('<img ')
  })

  it('кавычка в URL не вырывает атрибут (onclick-инъекция)', () => {
    const html = renderMarkdown('[x](https://a.example/" onmouseover="alert(1))')
    // кавычка экранирована: onmouseover остался ТЕКСТОМ внутри значения href,
    // отдельным атрибутом он не стал
    expect(html).toContain('onmouseover=&quot;')
    expect(html).not.toMatch(/" onmouseover="/)
  })

  it('безопасные схемы и относительные пути работают', () => {
    expect(renderMarkdown('[ок](https://example.com)')).toContain('href="https://example.com"')
    expect(renderMarkdown('[ок](http://example.com)')).toContain('href="http://example.com"')
    expect(renderMarkdown('[ок](mailto:a@b.c)').toLowerCase()).toContain('href="mailto:a@b.c"')
    expect(renderMarkdown('[ок](/api)')).toContain('href="/api"')
    expect(renderMarkdown('[ок](#раздел)')).toContain('href="#раздел"')
    expect(renderMarkdown('![п](./img.png)')).toContain('src="./img.png"')
  })

  it('конвенция <u> и прочая разметка не сломаны', () => {
    expect(renderMarkdown('<u>подчёркнуто</u>')).toContain('<u>подчёркнуто</u>')
    expect(renderMarkdown('**жирный**')).toContain('<strong>жирный</strong>')
    expect(renderMarkdown('~~зачёркнутый~~')).toContain('<s>зачёркнутый</s>')
    expect(renderMarkdown('`код`')).toContain('<code>код</code>')
    expect(renderMarkdown('<script>alert(1)</script>')).not.toContain('<script>')
  })
})
