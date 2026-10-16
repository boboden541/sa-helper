import { useCallback, useEffect, useRef, useState } from "react";
import type { BoardState, Story, TaskDoc } from "./types";
import { api, pipelineOf, setFnr as setApiFnr, PIPE_RU } from "./api";
import { Portfolio } from "./components/portfolio/Portfolio";
import { Board } from "./components/board/Board";
import { TaskPanel } from "./components/task/TaskPanel";
import { CreateModal } from "./components/create/CreateModal";
import { CommandPalette, Toasts, type Command, type Toast } from "./components/common/CommandPalette";

export function App() {
  const [fnr, setFnr] = useState<string | null>(null);   // null = портфель
  const [stories, setStories] = useState<Story[]>([]);
  const [state, setState] = useState<BoardState | null>(null);
  const [taskDoc, setTaskDoc] = useState<TaskDoc | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createType, setCreateType] = useState<"story" | "task">("story");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [conn, setConn] = useState("…");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(1);
  const prevAttention = useRef<Map<string, string>>(new Map());

  const refreshStories = useCallback(() => {
    api.stories().then((d) => setStories(d.stories)).catch(() => {});
  }, []);

  const loadBoard = useCallback((id: string) => {
    api.state(id).then(setState).catch(() => setState(null));
  }, []);

  const openStory = useCallback((id: string) => {
    setFnr(id);
    setApiFnr(id);
    loadBoard(id);
  }, [loadBoard]);

  const backToStories = useCallback(() => {
    setFnr(null);
    setApiFnr(null);
    setState(null);
    setTaskDoc(null);
    refreshStories();
  }, [refreshStories]);

  const openTask = useCallback((id: string) => {
    api.task(id).then(setTaskDoc).catch(() => {});
  }, []);

  // портфель: первичная загрузка + SSE
  useEffect(() => {
    refreshStories();
    const es = new EventSource("/events");
    es.onopen = () => setConn("live");
    es.onerror = () => setConn("переподключение…");
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.stories) setStories(data.stories);
      else if (data.manifest) setState(data); // одиночный режим (--harness)
    };
    return () => es.close();
  }, [refreshStories]);

  // доска активной Story: опрос (SSE в workspace-режиме стримит портфель)
  useEffect(() => {
    if (!fnr) return;
    loadBoard(fnr);
    const timer = setInterval(() => loadBoard(fnr), 3000);
    return () => clearInterval(timer);
  }, [fnr, loadBoard]);

  // тосты «нужен человек» — дифф снапшотов
  useEffect(() => {
    if (!state) return;
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
            onClick: () => { if (fnr) { openStory(fnr); openTask(tid); } } }]);
        setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), 10000);
      }
    }
    prevAttention.current = next;
    document.title = next.size
      ? `(${next.size}) AI Harness — ждут человека`
      : "AI Harness";
  }, [state, fnr, openStory]);

  // горячие клавиши
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyK") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyN") {
        e.preventDefault();
        setCreateOpen(true);
      }
      if (e.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const paletteCommands: Command[] = [
    { id: "create", label: "Создать… (Story или Task)", hint: "⌘N", run: () => setCreateOpen(true) },
    { id: "open:stories", label: "Открыть портфель Stories", run: backToStories },
    { id: "refresh", label: "Обновить данные", run: () => { refreshStories(); if (fnr) loadBoard(fnr); } },
    ...(fnr ? [{ id: "task:reload", label: `Перезагрузить ${fnr}`, run: () => loadBoard(fnr) }] : []),
    // переходы по задачам активной Story
    ...(state?.manifest.tasks || []).map((t) => ({
      id: `task:${t.id}`,
      label: `${t.id} — ${t.title ?? ""}`,
      hint: PIPE_RU[pipelineOf(t)],
      run: () => openTask(t.id),
    })),
  ];

  return (
    <>
      <header>
        <button id="back-btn" className="ghost" style={{ display: fnr ? "" : "none" }}
          onClick={backToStories}>← Stories</button>
        <span className="brand"><span className="dot" />Harness</span>
        <span className="crumb">
          {fnr ? <>Stories / <b>{stories.find((s) => s.fnr === fnr)?.title ?? fnr}</b></> : <b>Stories</b>}
        </span>
        <span className="spacer" />
        <span id="flags">
          {(state?.flags || []).filter((f) => !f.startsWith("TASK_")).map((f) => (
            <span className="flag-chip" key={f}>{f === "APPROVE_PLAN" ? "ждёт утверждения плана" : f}</span>
          ))}
        </span>
        {fnr && (
          <button id="approve" className="ghost"
            disabled={(state?.flags || []).includes("APPROVE_PLAN")}
            onClick={() => api.setFlag("APPROVE_PLAN").then(() => loadBoard(fnr))}>✓ План</button>
        )}
        {fnr && (
          <button id="pause" className="ghost"
            onClick={() => api.setFlag("PAUSE",
              (state?.flags || []).includes("PAUSE") ? "DELETE" : "POST")
              .then(() => loadBoard(fnr))}>
            {(state?.flags || []).includes("PAUSE") ? "▶" : "⏸"}
          </button>
        )}
        <button className="primary" onClick={() => { setCreateType("story"); setCreateOpen(true); }}>+ Создать</button>
        <span className={`conn ${conn === "live" ? "on" : ""}`}>{conn}</span>
      </header>

      {fnr === null
        ? <Portfolio stories={stories} onOpen={openStory} />
        : (state
          ? <Board state={state} onOpenTask={openTask}
              onAddTask={() => { setCreateType("task"); setCreateOpen(true); }} />
          : <div className="page"><p className="empty">загрузка Story…</p></div>)}

      <TaskPanel doc={taskDoc} onClose={() => { setTaskDoc(null); if (fnr) loadBoard(fnr); }}
        onAction={() => {
          if (fnr) loadBoard(fnr);
          if (taskDoc) api.task(taskDoc.task.id).then(setTaskDoc);
        }} />

      {createOpen && (
        <CreateModal initialType={createType}
          onClose={() => setCreateOpen(false)} onCreated={() => {
            refreshStories();
            if (fnr) loadBoard(fnr);
          }} stories={stories} preselectedFnr={fnr} />
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        state={state} stories={stories} actions={paletteCommands} />
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((l) => l.filter((x) => x.id !== id))} />
    </>
  );
}
