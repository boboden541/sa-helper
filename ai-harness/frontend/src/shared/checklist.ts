// Чеклисты: текстовый режим `- ~ x + !` и заголовки `#`–`#####` (ФТ-ah-9)

export interface ChecklistLine {
  kind: 'heading' | 'item'
  level?: number
  text: string
  status?: 'todo' | 'in_progress' | 'closed' | 'done' | 'failed'
}

export const STATUS_SYMBOL: Record<string, string> = {
  todo: '-', in_progress: '~', closed: 'x', done: '+', failed: '!',
}
export const SYMBOL_STATUS: Record<string, string> = {
  '-': 'todo', '~': 'in_progress', x: 'closed', '+': 'done', '!': 'failed',
}

export function parseChecklist(source: string): ChecklistLine[] {
  return source.split(/\r?\n/).filter((l) => l.trim()).map((line) => {
    const heading = line.match(/^(#{1,5})\s+(.*)$/)
    if (heading) {
      return { kind: 'heading' as const, level: heading[1].length, text: heading[2] }
    }
    const item = line.match(/^\s*([~+x!\-])\s+(.*)$/)
    if (item) {
      return { kind: 'item' as const, text: item[2], status: SYMBOL_STATUS[item[1]] as ChecklistLine['status'] }
    }
    return { kind: 'item' as const, text: line.trim(), status: 'todo' as const }
  })
}

export function serializeChecklist(lines: ChecklistLine[]): string {
  return lines
    .map((l) => l.kind === 'heading'
      ? `${'#'.repeat(l.level ?? 1)} ${l.text}`
      : `${STATUS_SYMBOL[l.status ?? 'todo']} ${l.text}`)
    .join('\n')
}
