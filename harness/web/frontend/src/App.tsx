import { useCallback, useEffect, useRef, useState } from "react";
import type { BoardState, Project, Task, TaskDoc } from "./types";
import { api, pipelineOf, setFnr as setApiFnr, setProject as setApiProject, PIPE_RU } from "./api";
import { Board } from "./components/board/Board";
import { TaskList } from "./components/board/TaskList";
import { TaskPanel } from "./components/task/TaskPanel";
import { cardEditorConfirmClose } from "./components/task/CardEditor";
import { CreateModal } from "./components/create/CreateModal";
import { ProjectModal } from "./components/create/ProjectModal";
import { ReviewPlanModal } from "./components/plan/ReviewPlanModal";
import { AiSettingsModal } from "./components/settings/AiSettingsModal";
import { Header } from "./components/Header";
import { MetricsDialog } from "./components/common/MetricsDialog";
import { OverviewDialog } from "./components/common/OverviewDialog";
import { CommandPalette, type Command } from "./components/common/CommandPalette";
import { Toasts, toast } from "./components/common/toasts";
import { StewardChat } from "./components/common/StewardChat";

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<string | null>(null);   // активный проект
  const [fnr, setFnr] = useState<string | null>(null);           // активная Story
  const [state, setState] = useState<BoardState | null>(null);
  const [taskDoc, setTaskDoc] = useState<TaskDoc | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createType, setCreateType] = useState<"story" | "task">("story");
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [editProject, setEditProject] = useState<Project | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [metricsOpen, setMetricsOpen] = useState(false);
  const [overviewOpen, setOverviewOpen] = useState(false);
  const [view, setView] = useState<"board" | "list">("board");
  const [conn, setConn] = useState("…");
  const [justMoved, setJustMoved] = useState<string | null>(null);
  const prevAttention = useRef<Map<string, string>>(new Map());
  const bootedRef = useRef(false);
  // refs для SSE-насоса (замыкание живёт между рендерами)
  const fnrRef = useRef(fnr);
  fnrRef.current = fnr;
  const boardPumpRef = useRef<() => void>(() => {});
  boardPumpRef.current = () => {
    refresh();
    const cur = fnrRef.current;
    if (cur) api.state(cur).then(setState).catch(() => {});
  };

  const activeProject = projects.find((x) => x.name === project) || null;
  const stories = activeProject?.stories ?? [];

  const refresh = useCallback(() => {
    api.projects().then((d) => {
      setProjects(d.projects);
      if (!bootedRef.current && d.projects.length) {
        bootedRef.current = true;
        const prj = d.projects[0];
        setProject(prj.name);
        setApiProject(prj.name);
        const story = prj.stories[0];
        if (story) { setFnr(story.fnr); setApiFnr(story.fnr); }
      }
    }).catch(() => {});
  }, []);

  const loadBoard = useCallback((p: string, id: string) => {
    setProject(p); setApiProject(p);
    setFnr(id); setApiFnr(id);
    api.state(id).then(setState).catch(() => setState(null));
  }, []);

  const openStory = useCallback((prj: string, id: string) => loadBoard(prj, id), [loadBoard]);

  const openTask = useCallback((id: string) => {
    api.task(id).then(setTaskDoc).catch(() => {});
  }, []);

  const reloadAll = useCallback(() => {
    refresh();
    if (project && fnr) loadBoard(project, fnr);
    if (taskDoc) api.task(taskDoc.task.id).then(setTaskDoc);
  }, [refresh, project, fnr, loadBoard, taskDoc]);

  // SSE: события демона/web (переходы, команды) двигают доску сразу —
  // троттл 1.5с (leading + trailing); 3с-опрос ниже остаётся fallback'ом
  useEffect(() => {
    refresh();
    const es = new EventSource("/events");
    es.onopen = () => setConn("live");
    es.onerror = () => setConn("переподключение…");
    let last = 0;
    let timer: number | undefined;
    const pump = () => {
      const now = Date.now();
      if (now - last >= 1500) { last = now; boardPumpRef.current(); }
      else if (timer === undefined) {
        timer = window.setTimeout(() => {
          timer = undefined; last = Date.now(); boardPumpRef.current();
        }, 1500 - (now - last));
      }
    };
    es.onmessage = pump;
    return () => { es.close(); if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  // опрос активной доски + портфеля
  useEffect(() => {
    const timer = setInterval(() => {
      refresh();
      if (project && fnr) api.state(fnr).then(setState).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [project, fnr, refresh]);

  // тосты «нужен человек»
  useEffect(() => {
    if (!state || !project) return;
    const next = new Map<string, string>();
    for (const t of state.manifest.tasks || []) {
      const p = pipelineOf(t);
      if (p === "NEEDS_HUMAN" || p === "BLOCKED") next.set(`${project}:${t.id}`, p);
    }
    for (const [key, p] of next) {
      if (prevAttention.current.get(key) !== p) {
        const tid = key.split(":")[1];
        toast.warn(`${tid} — ${p === "BLOCKED" ? "заблокирована" : "требует вашего участия"}`,
          () => openTask(tid));
      }
    }
    prevAttention.current = next;
    document.title = next.size ? `(${next.size}) AI Harness` : "AI Harness";
  }, [state, project, openTask]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyK") { e.preventDefault(); setPaletteOpen((v) => !v); }
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyN") { e.preventDefault(); setCreateOpen(true); }
      if (e.key === "Escape") { setPaletteOpen(false);
        if (cardEditorConfirmClose()) setTaskDoc(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const paletteCommands: Command[] = [
    { id: "create", label: "Создать… (Story или Task)", hint: "⌘N", run: () => setCreateOpen(true) },
    { id: "metrics", label: "Метрики расхода", run: () => setMetricsOpen(true) },
    { id: "overview", label: "Обзор проектов и Story", run: () => setOverviewOpen(true) },
    { id: "view:board", label: "Вид: канбан", run: () => setView("board") },
    { id: "view:list", label: "Вид: список", run: () => setView("list") },
    { id: "refresh", label: "Обновить данные", run: reloadAll },
    ...stories.map((s) => ({
      id: `story:${s.fnr}`, label: `${s.fnr} — ${s.title}`, hint: "Story",
      run: () => openStory(project || "", s.fnr),
    })),
    ...(state?.manifest.tasks || []).map((t) => ({
      id: `task:${t.id}`, label: `${t.id} — ${t.title ?? ""}`,
      hint: PIPE_RU[pipelineOf(t)], run: () => openTask(t.id),
    })),
  ];

  return (
    <>
      <Header fnr={fnr} stories={stories} projects={projects}
        activeProject={project} state={state} conn={conn}
        onOpenStory={(id) => project && openStory(project, id)}
        onOpenProject={(name) => {
          setProject(name); setApiProject(name);
          const prj = projects.find((x) => x.name === name);
          if (prj?.stories[0]) openStory(name, prj.stories[0].fnr);
          else { setFnr(null); setState(null); }
        }}
        onAllStories={() => setOverviewOpen(true)}
        onAddProject={() => setProjectModalOpen(true)}
        onOpenTask={openTask}
        onCreate={() => setCreateOpen(true)} onMetrics={() => setMetricsOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onEditProject={(name) => {
          const prj = projects.find((x) => x.name === name) || null;
          setEditProject(prj);
          setProjectModalOpen(true);
        }}
        onDeleteProject={(name) => {
          const prj = projects.find((x) => x.name === name) || null;
          setEditProject(prj);
          setProjectModalOpen(true);
        }}
        onOpenReview={() => setReviewOpen(true)}
        view={view} setView={setView}
        onFlag={(name, method) => {
          if (project && fnr) api.setFlag(name, method)
            .then(() => loadBoard(project, fnr))
            .catch((e) => toast.err(`Команда не выполнена: ${e.message}`));
        }} />

      {!state
        ? <div className="page"><p className="empty">
            {projects.length === 0
              ? "Проектов нет — добавьте проект кнопкой «＋» в шапке (пустая папка инициализируется автоматически)"
              : "загрузка Story…"}</p></div>
        : view === "board"
          ? <Board state={state} onOpenTask={openTask} justMovedId={justMoved}
              onAddTask={() => { setCreateType("task"); setCreateOpen(true); }}
              onMove={(id, to) => {
                // С2: оптимистичный перенос — карточка уезжает сразу,
                // откат по снапшоту при ошибке (409 живой сессии и т.п.)
                const snapshot = state;
                if (snapshot) {
                  const tasks = (snapshot.manifest.tasks || []).map((t) =>
                    t.id === id ? { ...t, pipeline: to as Task["pipeline"] } : t);
                  setState({ ...snapshot, manifest: { ...snapshot.manifest, tasks } });
                }
                setJustMoved(id);
                window.setTimeout(() => setJustMoved((v) => (v === id ? null : v)), 1400);
                api.move(id, to)
                  .then((r) => {
                    reloadAll();
                    if (r.noop) toast.info("Задача уже в целевом статусе");
                  })
                  .catch((e) => {
                    if (snapshot) setState(snapshot);
                    toast.err(`Перемещение не выполнено: ${e.message}`);
                  });
              }}
              onFlag={(_id, flag) => api.setFlag(flag)
                .then(reloadAll)
                .catch((e) => toast.err(`Команда не выполнена: ${e.message}`))} />
          : <TaskList state={state} onOpenTask={openTask}
              onAddTask={() => { setCreateType("task"); setCreateOpen(true); }} />}

      <TaskPanel doc={taskDoc} onClose={() => setTaskDoc(null)} onAction={reloadAll} />

      {createOpen && (
        <CreateModal initialType={createType} onClose={() => setCreateOpen(false)}
          onCreated={reloadAll} stories={stories} preselectedFnr={fnr} />
      )}
      {projectModalOpen && (
        <ProjectModal project={editProject ?? undefined}
          onClose={() => { setProjectModalOpen(false); setEditProject(null); }}
          onAdded={() => refresh()} />
      )}
      {reviewOpen && state && (
        <ReviewPlanModal state={state}
          onOpenTask={openTask}
          onAddTask={() => { setCreateType("task"); setCreateOpen(true); }}
          onChanged={reloadAll}
          onClose={() => setReviewOpen(false)} />
      )}
      {settingsOpen && <AiSettingsModal onClose={() => setSettingsOpen(false)} />}
      {metricsOpen && (
        <MetricsDialog stories={stories} fnr={fnr} onClose={() => setMetricsOpen(false)} />
      )}
      {overviewOpen && (
        <OverviewDialog projects={projects}
          onOpenStory={(prj, story) => openStory(prj, story)} onClose={() => setOverviewOpen(false)} />
      )}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        state={state} stories={stories} actions={paletteCommands} />
      <Toasts />
      <StewardChat />
    </>
  );
}
