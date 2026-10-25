// HTML → markdown для сериализации TipTap (подчёркнутый → <u>, ФТ-ah-5/14)

export function htmlToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return block(doc.body).replace(/\n{3,}/g, '\n\n').trim()
}

function inline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? ''
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const el = node as HTMLElement
  const children = Array.from(el.childNodes).map(inline).join('')
  switch (el.tagName) {
    case 'STRONG': case 'B': return `**${children}**`
    case 'EM': case 'I': return `*${children}*`
    case 'S': case 'DEL': return `~~${children}~~`
    case 'U': return `<u>${children}</u>`
    case 'CODE': return `\`${children}\``
    case 'A': return `[${children}](${el.getAttribute('href') ?? ''})`
    case 'IMG': return `![${el.getAttribute('alt') ?? ''}](${el.getAttribute('src') ?? ''})`
    case 'BR': return '\n'
    default: return children
  }
}

function block(el: HTMLElement, level = 0): string {
  return Array.from(el.childNodes).map((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const t = node.textContent ?? ''
      return t.trim() ? t.trim() : ''
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return ''
    const e = node as HTMLElement
    switch (e.tagName) {
      case 'H1': case 'H2': case 'H3': case 'H4': case 'H5': {
        const n = Number(e.tagName[1])
        return `${'#'.repeat(n)} ${inline(e)}`
      }
      case 'P': return inline(e)
      case 'BLOCKQUOTE': return block(e, level).split('\n').map((l) => `> ${l}`).join('\n')
      case 'PRE': return '```\n' + (e.textContent ?? '') + '\n```'
      case 'UL': return Array.from(e.children).map((li) => `- ${inline(li)}`).join('\n')
      case 'OL': return Array.from(e.children).map((li, i) => `${i + 1}. ${inline(li)}`).join('\n')
      case 'TABLE': {
        const rows = Array.from(e.querySelectorAll('tr'))
        return rows.map((tr, i) => {
          const cells = Array.from(tr.children).map((td) => inline(td))
          const line = `| ${cells.join(' | ')} |`
          if (i === 0 && rows.length > 1) {
            return line + '\n| ' + cells.map(() => '---').join(' | ') + ' |'
          }
          return line
        }).join('\n')
      }
      default: return block(e, level)
    }
  }).filter((s) => s.trim() !== '').join('\n\n')
}
