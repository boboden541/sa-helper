// Тосты как в макете (app.js toast + app.css .toasts/.toast).
// Данные структурированы вместо html-строк: код задачи приходит из API,
// и собирать его в innerHTML — XSS-дыра; рендерит App.tsx React-узлами.

export interface Toast { id: number; kind: 'ok' | 'auto' | 'bad'; text: string; code?: string }

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

// code — код задачи, App выделяет его жирным перед текстом (как прежний <b>${code}</b>)
export function toast(msg: string | { code: string; text: string }, kind: Toast['kind'] = 'ok'): void {
  const t: Toast = typeof msg === 'string'
    ? { id: ++seq, text: msg, kind }
    : { id: ++seq, kind, ...msg }
  items.push(t)
  listeners.forEach((l) => l())
  setTimeout(() => {
    const i = items.indexOf(t)
    if (i > -1) {
      items.splice(i, 1)
      listeners.forEach((l) => l())
    }
  }, 4200)
}
