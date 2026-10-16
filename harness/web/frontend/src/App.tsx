import { useCallback, useEffect, useRef, useState } from "react";
import type { BoardState, Story, TaskDoc } from "./types";
import { api, pipelineOf, setFnr as setApiFnr, PIPE_RU } from "./api";
import { Board } from "./components/board/Board";
import { TaskList } from "./components/board/TaskList";
import { TaskPanel } from "./components/task/TaskPanel";
import { CreateModal } from "./components/create/CreateModal";
import { Header } from "./components/Header";
import { MetricsDialog } from "./components/common/MetricsDialog";
import { CommandPalette, Toasts, type Command, type Toast } from "./components/common/CommandPalette";
import { StewardChat } from "./components/common/StewardChat";

export function App() {
  const [fnr, setFnr] = useState<string | null>(null);   // активная Story (доска = дом)
  const [stories, setStories] = useState<Story[]>([]);
  const [state, setState] = useState<BoardState | null>(null);
  const [taskDoc, setTaskDoc] = useState<TaskDoc | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createType, setCreateType] = useState<"story" | "task">("story");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [metricsOpen, setMetricsOpen] = useState(false);
  const [view, setView] = useState<"board" | "list">("board");
  const [conn, setConn] = useState("…");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(1);
  const prevAttention = useRef<Map<string, string>>(new Map());

  const refreshStories = useCallback(() => {
    api.stories().then((d) => {
      setStories(d.stories);
      // доска — дом: если ничего не выбрано, берём первую Story
      setFnr((cur) => cur ?? d.stories[0]?.fnr ?? null);
      if (!fnr && d.stories[0]) setApiFnr(d.stories[0].fnr);
    }).catch(() => {});
  }, [fnr]);

  const loadBoard = useCallback((id: string) => {
    api.state(id).then(setState).catch(() => setState(null));
  }, []);

  const openStory = useCallback((id: string) => {
    setFnr(id);
    setApiFnr(id);
    setTaskDoc(null);
    loadBoard(id);
  }, [loadBoard]);

  const openTask = useCallback((id: string) => {
    api.task(id).then(setTaskDoc).catch(() => {});
  }, []);

  const reloadAll = useCallback(() => {
    refreshStories();
    if (fnr) loadBoard(fnr);
    if (taskDoc) api.task(taskDoc.task.id).then(setTaskDoc);
  }, [refreshStories, fnr, loadBoard, taskDoc]);

  // SSE: workspace-режим стримит портфель; одиночный — состояние
  useEffect(() => {
    refreshStories();
    const es = new EventSource("/events");
    es.onopen = () => setConn("live");
    es.onerror = () => setConn("переподключение…");
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.stories) setStories(data.stories);
      else if (data.manifest) setState(data);
    };
    return () => es.close();
  }, [refreshStories]);

  // доска активной Story: опрос
  useEffect(() => {
    if (!fnr) return;
    loadBoard(fnr);
    const timer = setInterval(() => loadBoard(fnr), 3000);
    return () => clearInterval(timer);
  }, [fnr, loadBoard]);

  // тосты «нужен человек»
  useEffect(() => {
    if (!state || !fnr) return;
    const next = new Map<string, string>();
    for (const t of state.manifest.tasks || []) {
      const p = pipelineOf(t);
      if (p === "NEEDS_HUMAN" || p === "BLOCKED") next.set(`${fnr}:${t.id}`, p);
    }
    for (const [key, p] of next) {
      if (prevAttention.current.get(key) !== p) {
        const tid = key.split(":")[1];
        const id = toastId.current++;
        setToasts((list) => [...list,
          { id, text: `${tid} — ${p === "BLOCKED" ? "заблокирована" : "требует вашего участия"}`,
            onClick: () => openTask(tid) }]);
        setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), 10000);
      }
    }
    prevAttention.current = next;
    document.title = next.size ? `(${next.size}) AI Harness` : "AI Harness";
  }, [state, fnr, openTask]);

  // клавиши
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyK") { e.preventDefault(); setPaletteOpen((v) => !v); }
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyN") { e.preventDefault(); setCreateOpen(true); }
      if (e.key === "Escape") { setPaletteOpen(false); setTaskDoc(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const paletteCommands: Command[] = [
    { id: "create", label: "Создать… (Story или Task)", hint: "⌘N", run: () => setCreateOpen(true) },
    { id: "metrics", label: "Метрики расхода", run: () => setMetricsOpen(true) },
    { id: "view:board", label: "Вид: канбан", run: () => setView("board") },
    { id: "view:list", label: "Вид: список", run: () => setView("list") },
    { id: "refresh", label: "Обновить данные", run: reloadAll },
    ...stories.map((s) => ({
      id: `story:${s.fnr}`, label: `${s.fnr} — ${s.title}`, hint: "Story",
      run: () => openStory(s.fnr),
    })),
    ...(state?.manifest.tasks || []).map((t) => ({
      id: `task:${t.id}`, label: `${t.id} — ${t.title ?? ""}`,
      hint: PIPE_RU[pipelineOf(t)], run: () => openTask(t.id),
    })),
  ];

  return (
    <>
      <Header fnr={fnr} stories={stories} state={state} conn={conn}
        onOpenStory={openStory} onAllStories={() => setMetricsOpen(true)}
        onCreate={() => setCreateOpen(true)} onMetrics={() => setMetricsOpen(true)}
        view={view} setView={setView}
        onFlag={(name, method) => { if (fnr) api.setFlag(name, method).then(() => loadBoard(fnr)); }} />

      {!state
        ? <div className="page"><p className="empty">
            {stories.length === 0
              ? "Stories пока нет — нажмите «+ Создать» и добавьте СТ."
              : "загрузка Story…"}</p></div>
        : view === "board"
          ? <Board state={state} onOpenTask={openTask}
              onAddTask={() => { setCreateType("task"); setCreateOpen(true); }} />
          : <TaskList state={state} onOpenTask={openTask}
              onAddTask={() => { setCreateType("task"); setCreateOpen(true); }} />}

      <TaskPanel doc={taskDoc} onClose={() => setTaskDoc(null)} onAction={reloadAll} />

      {createOpen && (
        <CreateModal initialType={createType} onClose={() => setCreateOpen(false)}
          onCreated={reloadAll} stories={stories} preselectedFnr={fnr} />
      )}
      {metricsOpen && (
        <MetricsDialog stories={stories} fnr={fnr} onClose={() => setMetricsOpen(false)} />
      )}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        state={state} stories={stories} actions={paletteCommands} />
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((l) => l.filter((x) => x.id !== id))} />
      <StewardChat />
    </>
  );
}
