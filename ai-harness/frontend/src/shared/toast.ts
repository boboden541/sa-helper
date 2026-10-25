// Тосты как в макете (app.js toast + app.css .toasts/.toast)

export interface Toast { id: number; html: string; kind: 'ok' | 'auto' | 'bad' }

let seq = 0
const items: Toast[] = []
const listeners = new Set<() => void>()

export function subscribeToasts(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function currentToasts(): Toast[] {
  return items
}

export function toast(html: string, kind: Toast['kind'] = 'ok'): void {
  const t: Toast = { id: ++seq, html, kind }
  items.push(t)
  listeners.forEach((l) => l())
  setTimeout(() => {
    const i = items.indexOf(t)
    if (i > -1) {
      t.html = t.html // триггер анимации .out в DOM-слое не нужен — просто убираем
      items.splice(i, 1)
      listeners.forEach((l) => l())
    }
  }, 4200)
}
