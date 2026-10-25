// Минимальный рендер markdown по канонам описания задачи (ФТ-ah-5):
// заголовки 1–5, начертания, списки, цитата, код, ссылки, изображения, таблицы.

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function renderMarkdown(md: string): string {
  const lines = escapeHtml(md ?? '').split(/\r?\n/)
  const out: string[] = []
  let inList: 'ul' | 'ol' | null = null
  let inQuote = false
  let inCode = false
  let tableBuffer: string[] = []

  const inline = (s: string): string => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/___([^_]+)___/g, '<u><s>$1</s></u>')
    .replace(/__([^_]+)__/g, '<u>$1</u>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>')
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img alt="$1" src="$2" />')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')

  const flushTable = () => {
    if (!tableBuffer.length) return
    const rows = tableBuffer.map((r) => r.split('|').map((c) => c.trim()))
    const [head, ...body] = rows
    const html = ['<table><thead><tr>',
      ...head.map((c) => `<th>${inline(c)}</th>`), '</tr></thead><tbody>',
      ...body.filter((r) => !r.every((c) => /^-{2,}$/.test(c) || c === ''))
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`),
      '</tbody></table>']
    out.push(html.join(''))
    tableBuffer = []
  }
  const closeLists = () => {
    if (inList) { out.push(`</${inList}>`); inList = null }
    if (inQuote) { out.push('</blockquote>'); inQuote = false }
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flushTable(); closeLists()
      out.push(inCode ? '</code></pre>' : '<pre><code>')
      inCode = !inCode
      continue
    }
    if (inCode) { out.push(line); continue }
    if (/^\s*\|.+\|\s*$/.test(line)) { tableBuffer.push(line.trim().slice(1, -1)); continue }
    flushTable()
    const heading = line.match(/^(#{1,5})\s+(.*)$/)
    if (heading) {
      closeLists()
      out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`)
      continue
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/)
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (ul || ol) {
      const want = ul ? 'ul' : 'ol'
      if (inList !== want) { closeLists(); out.push(`<${want}>`); inList = want }
      out.push(`<li>${inline((ul ?? ol)![1])}</li>`)
      continue
    }
    const quote = line.match(/^&gt;\s?(.*)$/)
    if (quote) {
      if (!inQuote) { closeLists(); out.push('<blockquote>'); inQuote = true }
      out.push(`<p>${inline(quote[1])}</p>`)
      continue
    }
    closeLists()
    if (line.trim()) out.push(`<p>${inline(line)}</p>`)
  }
  flushTable(); closeLists()
  if (inCode) out.push('</code></pre>')
  return out.join('\n')
}
