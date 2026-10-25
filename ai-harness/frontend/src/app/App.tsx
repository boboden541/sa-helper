// Каркас — точная DOM-структура design_mockup/index.html:11-128:
// side (logo/nav/proj/daemon/settings) + main (topbar/warnbar/filters/эраны)
// + scrim/drawer + eve-btn/eve-panel + modal + undo-chip + toasts.

import { useEffect, useState } from 'react'
declare const __APP_BUILD__: string
import { api, type TaskCard } from '../api/client'
import { Board } from '../features/board/Board'
import { CreateDialog } from '../features/task-create/CreateDialog'
import { ListView } from '../features/task-list/ListView'
import { Settings } from '../features/settings/Settings'
import { TaskView } from '../features/task-card/TaskView'
import { EveChat } from '../features/assistant/Eve'
import { Login } from './Login'
import { useApp } from './store'
import { currentToasts, subscribeToasts } from '../shared/toast'
import { installUndoHotkey, lastUndoLabel, subscribeUndo, undoLast } from '../shared/undo'

const TYPE_FILTERS = [
  ['', 'Все'], ['story', 'Истории'], ['common_task', 'Задачи'],
  ['qa_task', 'QA'], ['bug', 'Баги'], ['analyse_task', 'Анализ'],
] as const

export function App() {
  const { view, theme, toggleTheme, applyHash, navigate, eveOpen, setEve } = useApp()
  const isTaskPage = view === 'task' && window.location.hash.endsWith('/page')
  const [tasks, setTasks] = useState<TaskCard[]>([])
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [notifications, setNotifications] = useState<{ id: string; code: string; message: string }[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [undoLabel, setUndoLabel] = useState<string | null>(null)
  const [projects, setProjects] = useState<{ mnemonic: string; name: string; isArchived: boolean }[]>([])
  const [needLogin, setNeedLogin] = useState(false)
  const [, force] = useState(0)

  useEffect(() => {
    applyHash(window.location.hash)
    const onHash = () => applyHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    const off = installUndoHotkey()
    return () => { window.removeEventListener('hashchange', onHash); off() }
  }, [applyHash])
  useEffect(() => subscribeUndo(() => setUndoLabel(lastUndoLabel())), [])
  useEffect(() => subscribeToasts(() => force((n) => n + 1)), [])

  const on401 = (err: Error & { status?: number }) => {
    if (err.status === 401) setNeedLogin(true)
    throw err
  }
  const reload = () => {
    void api.tasks({
      q: query || undefined,
      type: typeFilter || undefined,
      project: useApp.getState().project ?? undefined,
    }).then((r) => setTasks(r.items)).catch(on401)
    void api.notifications().then((r) => setNotifications(r.items)).catch(on401)
  }
  useEffect(reload, [query, typeFilter, view])
  useEffect(() => {
    void api.projects().then(setProjects).catch(() => {})
  }, [])

  const onEveCreate = () => setCreateOpen(true)
  useEffect(() => {
    const h = () => setCreateOpen(true)
    window.addEventListener('eve-open-create', h)
    return () => window.removeEventListener('eve-open-create', h)
  }, [])

  if (needLogin) return <Login onDone={() => { setNeedLogin(false); reload() }} />

  const filters = (
    <div className="filters" role="group" aria-label="Фильтр по типу задачи">
      {TYPE_FILTERS.map(([key, label]) => (
        <button key={key} className={`chip-f ${typeFilter === key ? 'active' : ''}`}
          onClick={() => setTypeFilter(key)}>{label}</button>
      ))}
      <span className="cnt">{tasks.length} задач</span>
      <button className="chip-f" style={{ marginLeft: 'auto', color: 'var(--accent-text)', borderColor: 'var(--accent)' }}
        onClick={() => setCreateOpen(true)}>＋ Задача</button>
    </div>
  )

  return (
    <div className="app">
      <aside className="side">
        <div className="logo" title={`Сборка: ${__APP_BUILD__ ?? 'dev'}`}>
          <span className="logo-mark">
            <svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 10.5L8 3l5 7.5M5.5 13l2.5-4 2.5 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </span>
          <div><b>AI-Harness</b><span>конвейер задач</span></div>
        </div>
        <button className={`nav-btn ${view === 'board' ? 'active' : ''}`} onClick={() => navigate('#board')}>Доска</button>
        <button className={`nav-btn ${view === 'list' ? 'active' : ''}`} onClick={() => navigate('#list')}>Список</button>
        <div className="side-h">Проекты</div>
        {projects.filter((p) => !p.isArchived).map((p) => (
          <button key={p.mnemonic} className="proj" onClick={() => useApp.getState().setProject(p.mnemonic)}>
            <span className="mn">{p.mnemonic}</span><span className="nm">{p.name}</span>
          </button>
        ))}
        <div className="side-foot">
          <div className="daemon"><span className="dot ok pulse" /> Демон · тик 30 с · агенты на своих статусах</div>
          <button className={`ghost-btn ${view === 'settings' ? 'active' : ''}`} style={{ width: '100%' }}
            onClick={() => navigate('#settings/flow')}>⚙ Настройки</button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1 id="viewTitle">{view === 'list' ? 'Список задач' : view === 'settings' ? 'Настройки' : 'Доска задач'}</h1>
          <div className="seg" role="tablist" aria-label="Вид">
            <button className={view === 'board' ? 'active' : ''} onClick={() => navigate('#board')}>Доска</button>
            <button className={view === 'list' ? 'active' : ''} onClick={() => navigate('#list')}>Список</button>
          </div>
          <label className="search">
            <svg width="14" height="14" viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.5"/><path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            <input type="search" placeholder="Поиск по названию или коду…"
              value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Поиск задач" />
            <kbd>поиск</kbd>
          </label>
          <span className="conn" title="Активное подключение к ИИ-провайдеру">
            <span className="dot ok" /> Подключение не настроено
          </span>
          <details className="pop">
            <summary className="icon-btn" aria-label="Уведомления">
              <svg width="16" height="16" viewBox="0 0 16 16"><path d="M8 2a4.2 4.2 0 014.2 4.2c0 3 .9 4.2 1.5 4.8H2.3c.6-.6 1.5-1.8 1.5-4.8A4.2 4.2 0 018 2zM6.5 13.2a1.6 1.6 0 003 0" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
              {notifications.length > 0 && <span className="badge num">{notifications.length}</span>}
            </summary>
            <div className="pop-body">
              <div className="ph">Система ждёт человека</div>
              {notifications.map((n) => (
                <div key={n.id} className="notif" onClick={() => navigate(`#${n.code}`)}>
                  <div className="nb">
                    <div className="nt">{n.message}</div>
                    <div className="ns">клик — открыть задачу</div>
                  </div>
                  <span className="nc">{n.code}</span>
                </div>
              ))}
              {notifications.length === 0 && (
                <div className="notif"><div className="nb"><div className="nt">Всё разрешено</div></div></div>
              )}
            </div>
          </details>
          <button className="icon-btn" onClick={toggleTheme} aria-label="Переключить тему">
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </header>

        {view !== 'settings' && !isTaskPage && filters}
        {(view === 'board' || (view === 'task' && !isTaskPage)) && (
          <Board tasks={tasks} reload={reload} />
        )}
        {view === 'list' && <ListView tasks={tasks} />}
        {view === 'task' && <TaskView />}
        {view === 'settings' && <Settings reload={reload} />}
      </main>

      {createOpen && <CreateDialog onClose={() => { setCreateOpen(false); reload() }} />}
      <EveChat open={eveOpen} setOpen={setEve} navigate={navigate} onOpenCreate={onEveCreate} />
      {undoLabel && (
        <button className="undo-chip" onClick={() => void undoLast()}>
          ↩ Отменить: {undoLabel} <span className="key">Ctrl+Z</span>
        </button>
      )}
      <div className="toasts">
        {currentToasts().map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} dangerouslySetInnerHTML={{ __html: t.html }} />
        ))}
      </div>
    </div>
  )
}
