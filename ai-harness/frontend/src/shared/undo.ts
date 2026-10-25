// Undo правок доски и графа flow (ФТ-ah-71): стек 50, Ctrl+Z, чип; ввод не перехватывается.

export interface UndoEntry { label: string; undo: () => void | Promise<void> }

const stack: UndoEntry[] = []
const MAX = 50
const listeners = new Set<() => void>()

export function pushUndo(entry: UndoEntry): void {
  stack.push(entry)
  if (stack.length > MAX) stack.shift()
  listeners.forEach((l) => l())
}

export async function undoLast(): Promise<string | null> {
  const entry = stack.pop()
  if (!entry) return null
  await entry.undo()
  listeners.forEach((l) => l())
  return entry.label
}

export function lastUndoLabel(): string | null {
  return stack.length ? stack[stack.length - 1].label : null
}

export function subscribeUndo(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function isTextInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName in { INPUT: 1, TEXTAREA: 1 } ||
    target.isContentEditable ||
    target.getAttribute('role') === 'textbox'
}

export function installUndoHotkey(): () => void {
  const handler = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !isTextInput(e.target)) {
      e.preventDefault()
      void undoLast()
    }
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}
