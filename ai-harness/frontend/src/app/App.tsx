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
import { currentToasts, subscribeToasts, toast } from '../shared/toast'
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
  const [createPrefill, setCreatePrefill] = useState<{ title?: string; descriptionMd?: string } | undefined>()
  const [cmdOpen, setCmdOpen] = useState(false)
  const [cmds, setCmds] = useState<{ name: string; description?: string | null }[]>([])
  const toggleCmds = () => {
    if (!cmdOpen && cmds.length === 0) {
      void fetch('/api/v1/tools').then((r) => r.json()).then((d) => {
        setCmds((d.items ?? []).filter((i: { kind: string }) => i.kind === 'command').map(
          (i: { name: string; description?: string | null }) => ({ name: i.name, description: i.description })))
      }).catch(() => {})
    }
    setCmdOpen((v) => !v)
  }
  const runCommand = (name: string, description?: string | null) => {
    setCmdOpen(false)
    void api.toolContent('command', name).then((t) => {
      setCreatePrefill({ title: name, descriptionMd: t.content })
      setCreateOpen(true)
    }).catch((err: Error) => toast(err.message, 'bad'))
  }
  const [undoLabel, setUndoLabel] = useState<string | null>(null)
  const [projects, setProjects] = useState<{ mnemonic: string; name: string; isArchived: boolean; openCount?: number }[]>([])
  const [needLogin, setNeedLogin] = useState(false)
  const [boardEdit, setBoardEdit] = useState(false)
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
  const project = useApp((s) => s.project)
  const setProject = useApp((s) => s.setProject)
  const reload = () => {
    // лимит 200: доска/список не должны терять открытые задачи из-за
    // усечения выборки очередью (приоритет → баги → старые выше)
    void api.tasks({
      q: query || undefined,
      type: typeFilter || undefined,
      project: project ?? undefined,
      limit: '200',
    }).then((r) => setTasks(r.items)).catch(on401)
    void api.notifications().then((r) => setNotifications(r.items)).catch(on401)
  }
  useEffect(reload, [query, typeFilter, view, project])
  const [projCounts, setProjCounts] = useState<Record<string, number>>({})
  useEffect(() => {
    void api.projects().then((list) => {
      setProjects(list)
      setProjCounts(Object.fromEntries(list.map((x) => [x.mnemonic, x.openCount ?? 0])))
    }).catch(() => {})
  }, [view])
  const [warnings, setWarnings] = useState<{ level: string; message: string; goto?: string }[]>([])
  const [pipelinePaused, setPipelinePaused] = useState(false)
  const [connInfo, setConnInfo] = useState<{ name: string; model: string } | null | undefined>(undefined)
  useEffect(() => {
    void api.pipelineStatus().then((r) => {
      setWarnings(r.warnings)
      setPipelinePaused(Boolean((r as { paused?: boolean }).paused))
    }).catch(() => {})
    void api.requestProviders().then((list) => {
      const a = list.find((c) => c.isActive)
      setConnInfo(a ? { name: a.name, model: a.model } : null)
    }).catch(() => setConnInfo(null))
  }, [view])

  const togglePipeline = () => {
    const to = !pipelinePaused
    const label = to ? 'Остановить конвейер?' : 'Возобновить конвейер?'
    const detail = to
      ? 'Агенты будут остановлены (разработка, ревью, тестирование…). Новые запуски не выполняются. Чат Eve продолжит работать.'
      : 'Демон снова возьмёт задачи из очереди.'
    if (!window.confirm(`${label}\n\n${detail}`)) return
    void api.pipelinePause(to).then(() => setPipelinePaused(to))
      .catch((err: Error) => { toast(err.message, 'bad') })
  }

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
      {view === 'board' && (
        <button className={`btn small ${boardEdit ? 'primary' : ''}`}
          title="Создавайте колонки, меняйте названия, цвета и порядок"
          onClick={() => setBoardEdit(!boardEdit)}>✎ Правка доски</button>
      )}
      <button className="btn small primary" onClick={() => setCreateOpen(true)}>+ Задача</button>
      <div style={{ position: 'relative' }}>
        <button className="btn small" onClick={toggleCmds} title="Команды из папки инструментов">⚡ Команда</button>
        {cmdOpen && (
          <div className="proj-drop" style={{ right: 0 }}>
            {cmds.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Реестр пуст — просканируйте папку в «Настройки → Инструменты»</div>}
            {cmds.map((c) => (
              <div key={c.name} className="rel" onClick={() => runCommand(c.name, c.description)}>
                <span className="code">/{c.name}</span>
                <span className="rt">{(c.description ?? '').slice(0, 70)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
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
          <button key={p.mnemonic}
            className={`proj ${project === p.mnemonic ? 'active' : ''}`}
            title={project === p.mnemonic ? 'Показаны все проекты' : `Доска проекта ${p.name}`}
            onClick={() => setProject(project === p.mnemonic ? null : p.mnemonic)}>
            <span className="mn">{p.mnemonic}</span><span className="nm">{p.name}</span>
            <span className="badge num">{projCounts[p.mnemonic] ?? 0}</span>
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
          {connInfo !== null ? (
            <span className="conn" title={`Активное ИИ-подключение: ${connInfo?.name} (${connInfo?.model})`}>
              <span className="dot" style={{ background: '#25935b' }} /> {connInfo?.name}
            </span>
          ) : (
            <button className="conn off" title="Активное ИИ-подключение не выбрано — нажмите, чтобы перейти к настройкам"
              onClick={() => navigate('#settings/providers')}>
              <span className="dot" style={{ background: '#c07d1e' }} /> Подключение не настроено
            </button>
          )}
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
          <button className={`icon-btn pipeline-btn ${pipelinePaused ? 'paused' : ''}`}
            onClick={togglePipeline}
            title={pipelinePaused ? 'Конвейер на паузе — возобновить работу агентов'
              : 'Конвейер работает — остановить агентов (разработка, ревью, тестирование). Чат Eve продолжит работать.'}
            aria-label="Рубильник конвейера">
            {pipelinePaused ? (
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M4 2.5v9l7.5-4.5z" fill="currentColor" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <rect x="3" y="2.5" width="3" height="9" rx="1" fill="currentColor" />
                <rect x="8" y="2.5" width="3" height="9" rx="1" fill="currentColor" />
              </svg>
            )}
            <span className="dot" style={{ background: pipelinePaused ? '#cf4436' : '#25935b' }} />
          </button>
          <button className="icon-btn" onClick={toggleTheme} aria-label="Переключить тему">
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </header>

        {warnings.map((w, i) => (
          <div key={i} className="warnbar">
            <span className="wi">⚠</span>
            <span><b>{w.level === 'danger' ? 'Конвейер приостановлен' : 'Предупреждение'}</b> — {w.message}</span>
            {w.goto && <button className="btn small" onClick={() => navigate(w.goto!)}>Перейти в настройки</button>}
          </div>
        ))}
        {view !== 'settings' && !isTaskPage && filters}
        {view !== 'settings' && !isTaskPage && project && (
          <div className="proj-active">
            Проект <b>{project}</b>
            <button className="btn small" onClick={() => setProject(null)}>✕ все проекты</button>
          </div>
        )}
        {(view === 'board' || (view === 'task' && !isTaskPage)) && (
          <Board tasks={tasks} reload={reload} boardEdit={boardEdit} />
        )}
        {view === 'list' && <ListView tasks={tasks} />}
        {view === 'task' && <TaskView />}
        {view === 'settings' && <Settings reload={reload} />}
      </main>

      {createOpen && <CreateDialog onClose={() => { setCreateOpen(false); setCreatePrefill(undefined); reload() }} prefill={createPrefill} />}
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
