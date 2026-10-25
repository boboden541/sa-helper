// Каркас приложения: боковая панель, переключатель видов, поиск, колокольчик,
// тема, deep links без перезагрузки (СТ §5.1, макет index.html:11-82).

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../api/client'
import { Board } from '../features/board/Board'
import { CreateDialog } from '../features/task-create/CreateDialog'
import { ListView } from '../features/task-list/ListView'
import { Settings } from '../features/settings/Settings'
import { TaskPage } from '../features/task-card/TaskPage'
import { EveChat } from '../features/assistant/Eve'
import { Login } from './Login'
import { installUndoHotkey, lastUndoLabel, subscribeUndo, undoLast } from '../shared/undo'
import { useApp } from './store'

export function App() {
  const { view, theme, toggleTheme, applyHash, navigate, eveOpen, setEve } = useApp()
  const [tasks, setTasks] = useState<TaskCard[]>([])
  const [query, setQuery] = useState('')
  const [notifications, setNotifications] = useState<{ id: string; code: string; message: string }[]>([])
  const [bellOpen, setBellOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [undoLabel, setUndoLabel] = useState<string | null>(null)
  const [projects, setProjects] = useState<{ mnemonic: string; name: string }[]>([])
  const [needLogin, setNeedLogin] = useState(false)

  useEffect(() => {
    applyHash(window.location.hash)
    const onHash = () => applyHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    const off = installUndoHotkey()
    return () => { window.removeEventListener('hashchange', onHash); off() }
  }, [applyHash])

  useEffect(() => subscribeUndo(() => setUndoLabel(lastUndoLabel())), [])

  const reload = () => {
    void api.tasks({ q: query || undefined, project: useApp.getState().project ?? undefined })
      .then((r) => setTasks(r.items))
      .catch((err: Error & { status?: number }) => {
        if (err.status === 401) setNeedLogin(true)
      })
    void api.notifications().then((r) => setNotifications(r.items))
      .catch((err: Error & { status?: number }) => {
        if (err.status === 401) setNeedLogin(true)
      })
  }

  useEffect(reload, [query, view])
  useEffect(() => { void api.projects().then((ps) => setProjects(ps.filter((p) => !p.isArchived))) }, [])

  if (needLogin) {
    return <Login onDone={() => { setNeedLogin(false); reload() }} />
  }

  return (
    <div className="app">
      <aside className="side">
        <div className="logo"><b>AI-Harness</b><span>конвейер задач</span></div>
        <button className={`nav-btn ${view === 'board' ? 'active' : ''}`} onClick={() => navigate('#board')}>Доска</button>
        <button className={`nav-btn ${view === 'list' ? 'active' : ''}`} onClick={() => navigate('#list')}>Список</button>
        <div className="side-h">Проекты</div>
        {projects.map((p) => (
          <button key={p.mnemonic} className="nav-btn small"
            onClick={() => useApp.getState().setProject(p.mnemonic)}>{p.mnemonic} · {p.name}</button>
        ))}
        <div className="side-foot">
          <button className={`nav-btn ${view === 'settings' ? 'active' : ''}`}
            onClick={() => navigate('#settings/flow')}>Настройки</button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>{view === 'list' ? 'Список задач' : view === 'settings' ? 'Настройки' : 'Доска задач'}</h1>
          {view !== 'settings' && view !== 'task' && (
            <div className="seg">
              <button className={view === 'board' ? 'active' : ''} onClick={() => navigate('#board')}>Доска</button>
              <button className={view === 'list' ? 'active' : ''} onClick={() => navigate('#list')}>Список</button>
            </div>
          )}
          <label className="search">
            <input type="search" placeholder="Поиск по названию или коду…"
              value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <button className="btn" onClick={() => setCreateOpen(true)}>＋ Задача</button>
          <details className="pop" open={bellOpen} onToggle={(e) => setBellOpen((e.target as HTMLDetailsElement).open)}>
            <summary className="icon-btn">🔔{notifications.length > 0 && <span className="badge">{notifications.length}</span>}</summary>
            <div className="pop-body">
              <div className="ph">Система ждёт человека</div>
              {notifications.map((n) => (
                <div key={n.id} className="notif" onClick={() => navigate(`#${n.code}`)}>
                  <b>{n.code}</b> — {n.message}
                </div>
              ))}
              {notifications.length === 0 && <div className="notif">Всё разрешено ✓</div>}
            </div>
          </details>
          <button className="icon-btn" onClick={toggleTheme} aria-label="Тема">{theme === 'dark' ? '☀' : '☾'}</button>
        </header>

        {view === 'board' && <Board tasks={tasks} reload={reload} />}
        {view === 'list' && <ListView tasks={tasks} />}
        {view === 'task' && <TaskPage />}
        {view === 'settings' && <Settings reload={reload} />}
      </main>

      {createOpen && <CreateDialog onClose={() => { setCreateOpen(false); reload() }} />}
      <EveChat open={eveOpen} setOpen={setEve} navigate={navigate} />
      {undoLabel && (
        <button className="undo-chip" onClick={() => void undoLast()}>
          ↩ Отменить: {undoLabel} (Ctrl+Z)
        </button>
      )}
    </div>
  )
}
