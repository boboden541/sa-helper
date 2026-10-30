// Глобальное состояние: тема, вид, hash-роутинг (deep links, ФТ-ah-17), проектный фильтр.

import { create } from 'zustand'

export type View = 'board' | 'list' | 'settings' | 'task'

interface AppState {
  theme: 'light' | 'dark'
  view: View
  settingsTab: string
  taskCode: string | null
  taskPage: boolean
  project: string | null
  eveOpen: boolean
  toggleTheme: () => void
  navigate: (hash: string) => void
  applyHash: (hash: string) => void
  setProject: (mnemonic: string | null) => void
  setEve: (open: boolean) => void
}

export function parseHash(hash: string): Partial<AppState> {
  const clean = hash.replace(/^#\/?/, '')
  const result: Partial<AppState> = {}
  if (clean.startsWith('dark')) result.theme = 'dark'
  if (clean.startsWith('light')) result.theme = 'light'
  if (clean.includes('eve')) result.eveOpen = true
  if (clean.startsWith('list')) result.view = 'list'
  if (clean.startsWith('board')) result.view = 'board'
  if (clean.startsWith('settings')) {
    result.view = 'settings'
    const tab = clean.split('/')[1]
    if (tab) result.settingsTab = tab
  }
  const taskMatch = clean.match(/^([A-Za-z]{2,10}-\d+)(\/page)?$/)
  if (taskMatch) {
    result.view = 'task'
    result.taskCode = taskMatch[1].toUpperCase()
    result.taskPage = Boolean(taskMatch[2])
  }
  return result
}

const applyTheme = (theme: string) => {
  document.documentElement.dataset.theme = theme
  localStorage.setItem('harness-theme', theme)
}

export const useApp = create<AppState>((set) => ({
  theme: (localStorage.getItem('harness-theme') as 'light' | 'dark') ??
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
  view: 'board',
  settingsTab: 'flow',
  taskCode: null,
  taskPage: false,
  project: null,
  eveOpen: false,
  toggleTheme: () => set((s) => {
    const theme = s.theme === 'dark' ? 'light' : 'dark'
    applyTheme(theme)
    return { theme }
  }),
  navigate: (hash: string) => {
    window.location.hash = hash
    set(parseHash(hash) as Partial<AppState>)
  },
  applyHash: (hash: string) => {
    const patch = parseHash(hash)
    if (patch.theme) applyTheme(patch.theme)
    set(patch)
  },
  setProject: (mnemonic) => set({ project: mnemonic }),
  setEve: (open) => set({ eveOpen: open }),
}))
