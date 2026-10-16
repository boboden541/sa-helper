import { useEffect, useRef, useState } from "react";
import type { BoardState, Story } from "../types";
import { fmtTokens, fmtUsd, sumUsage } from "./common/ui";

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}с назад`;
  return `${Math.round(s / 60)}м назад`;
}

/** Шапка-пульт: лого, селектор Story (обзор внутри), вид, метрики, действия. */
export function Header({ fnr, stories, state, conn = "…", onOpenStory, onAllStories,
  onCreate, onMetrics, view, setView, onFlag }: {
  fnr: string | null;
  stories: Story[];
  state: BoardState | null;
  conn?: string;
  onOpenStory: (fnr: string) => void;
  onAllStories: () => void;
  onCreate: () => void;
  onMetrics: () => void;
  view: "board" | "list";
  setView: (v: "board" | "list") => void;
  onFlag: (name: string, method?: "POST" | "DELETE") => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const flags = state?.flags || [];
  const attention = (state?.manifest.tasks || [])
    .filter((t) => ["NEEDS_HUMAN", "BLOCKED"].includes(t.pipeline || "")).length;

  return (
    <header>
      <span className="logo">{">"}</span>

      <div className="story-select" ref={menuRef}>
        <button onClick={() => setMenuOpen((v) => !v)}>
          📋 {fnr ? (stories.find((s) => s.fnr === fnr)?.title || fnr) : "Все Stories"} ▾
        </button>
        {menuOpen && (
          <div className="story-menu">
            <div className="s-head meta">Stories воркспейса</div>
            {stories.length === 0 && <div className="s-item empty">пока нет Stories</div>}
            {stories.map((s) => {
              const done = (s.counts.DONE || 0) + (s.counts.VERIFIED || 0);
              const pct = s.tasks ? Math.round((100 * done) / s.tasks) : 0;
              const u = sumUsage(s.task_list);
              return (
                <div className="s-item" key={s.fnr}
                  onClick={() => { onOpenStory(s.fnr); setMenuOpen(false); }}>
                  <span className="fnr">{s.fnr}</span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: "block", overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
                    <span className="meta">{done}/{s.tasks} · 🪙 {fmtTokens(u.tokens_total)} · {fmtUsd(u.cost_usd)}</span>
                  </span>
                  <span className="bar"><i style={{ width: `${pct}%` }} /></span>
                </div>
              );
            })}
            <div className="s-item" onClick={() => { onAllStories(); setMenuOpen(false); }}>
              <span className="meta">📊 Обзор всех Story (метрики)</span>
            </div>
            <div className="s-item" onClick={() => { onCreate(); setMenuOpen(false); }}>
              <span className="meta">＋ Новая Story…</span>
            </div>
          </div>
        )}
      </div>

      {fnr && (
        <span className="meta mono">
          {timeAgo(state?.manifest.tasks?.find((t) => t.live)?.pipeline_since)}
        </span>
      )}

      <span className="spacer" />
      <span className="kbd">⌘K</span>

      <div className="seg" style={fnr ? undefined : { display: "none" }}>
        <button className={view === "board" ? "active" : ""} onClick={() => setView("board")}>KANBAN</button>
        <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>LIST</button>
      </div>

      <button onClick={onMetrics} title="Метрики расхода">📊 METRICS</button>
      <button title="Нужные действия" style={attention ? { color: "var(--warn)", borderColor: "var(--warn)" } : undefined}>
        🔔 {attention || ""}
      </button>

      <span id="flags">
        {flags.filter((f) => !f.startsWith("TASK_")).map((f) => (
          <span className="flag-chip" key={f}>{f === "APPROVE_PLAN" ? "ждёт утверждения плана" : f}</span>
        ))}
      </span>
      {fnr && (
        <>
          <button className="ghost" disabled={flags.includes("APPROVE_PLAN")}
            onClick={() => onFlag("APPROVE_PLAN")}>✓ План</button>
          <button className="ghost" onClick={() => onFlag("PAUSE",
            flags.includes("PAUSE") ? "DELETE" : "POST")}>
            {flags.includes("PAUSE") ? "▶" : "⏸"}
          </button>
        </>
      )}
      <button className="primary" onClick={onCreate}>+ Создать</button>
      <span className={`conn ${conn === "live" ? "on" : ""}`}>{conn}</span>
    </header>
  );
}

export { timeAgo };
