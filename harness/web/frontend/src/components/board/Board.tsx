import { useMemo, useState } from "react";
import type { BoardState, Task } from "../../types";
import { pipelineOf } from "../../api";
import { Chip, UsageBadge } from "../common/ui";
import { timeAgo } from "../Header";

const COLUMNS: Array<{ key: string; title: string; also?: string[];
  dot: string; mode: "ai" | "human" | "decision"; modeLabel: string }> = [
  { key: "PROPOSED", title: "Предложены", dot: "var(--amber)",
    mode: "decision", modeLabel: "Human decision" },
  { key: "BACKLOG", title: "Бэклог", dot: "var(--faint)",
    mode: "human", modeLabel: "Human controlled" },
  { key: "READY", title: "Готовы к запуску", dot: "var(--acc)",
    mode: "ai", modeLabel: "AI controlled" },
  { key: "IMPLEMENTING", title: "В работе", dot: "var(--purple)",
    mode: "ai", modeLabel: "AI controlled" },
  { key: "REVIEW", title: "Ревью", dot: "var(--pink)",
    mode: "ai", modeLabel: "AI controlled" },
  { key: "DONE", title: "Готовы", dot: "var(--ok)",
    mode: "decision", modeLabel: "Human decision" },
  { key: "VERIFIED", title: "Проверены", dot: "var(--ok)",
    mode: "human", modeLabel: "Human controlled" },
  { key: "BLOCKED", title: "Блок / Нужен человек", dot: "var(--warn)",
    also: ["NEEDS_HUMAN", "ABORTED"], mode: "decision", modeLabel: "Human decision" },
];

function edgeOf(p: string): string {
  return { IMPLEMENTING: "var(--purple)", REVIEW: "var(--pink)", DONE: "var(--ok)",
    VERIFIED: "var(--ok)", NEEDS_HUMAN: "var(--warn)", BLOCKED: "var(--warn)",
    PROPOSED: "var(--amber)" }[p] || "var(--line2)";
}

function Card({ t, onOpen }: { t: Task; onOpen: (id: string) => void }) {
  const p = pipelineOf(t);
  const acs = t.acceptance_criteria || [];
  const passed = acs.filter((a) => a.status === "PASSED").length;
  return (
    <div className="tcard" style={{ "--edge": edgeOf(p) } as React.CSSProperties}
      onClick={() => onOpen(t.id)}>
      <div className="ttitle">{t.title || t.id}</div>
      {t.description && <div className="tdesc">{t.description}</div>}
      <div className="tagrow">
        <span className="tag">{t.id}</span>
        {t.phase && t.phase !== "regular" && <span className="tag">phase:{t.phase}</span>}
        {t.origin === "agent" && <span className="tag origin-agent">origin:agent</span>}
        {t.origin === "manual" && <span className="tag origin-manual">origin:manual</span>}
        {t.paused && <span className="tag paused">PAUSED</span>}
      </div>
      <div className="tfoot">
        <span>{t.live?.running ? <><span className="live-dot" />работает</> : timeAgo(t.pipeline_since)}</span>
        <span className="grow" />
        {t.review_iterations ? <span>ревью:{t.review_iterations}</span> : null}
        <UsageBadge usage={t.usage} />
        {acs.length > 0 && <span>AC {passed}/{acs.length}</span>}
      </div>
    </div>
  );
}

export function Board({ state, onOpenTask, onAddTask }: {
  state: BoardState;
  onOpenTask: (id: string) => void;
  onAddTask: () => void;
}) {
  const [active, setActive] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const tasks = state.manifest.tasks || [];

  const visible = useMemo(() => tasks.filter((t) => {
    const p = pipelineOf(t);
    for (const key of active) {
      if (key === "active" && !["IMPLEMENTING", "REVIEW", "READY"].includes(p)) return false;
      if (key === "blocked" && !["BLOCKED", "NEEDS_HUMAN"].includes(p)) return false;
      if (key === "proposed" && p !== "PROPOSED") return false;
      if (key === "manual" && t.origin !== "manual") return false;
      if (key === "agent" && t.origin !== "agent") return false;
      if (key === "done" && !["DONE", "VERIFIED"].includes(p)) return false;
    }
    if (query && !`${t.id} ${t.title} ${t.description || ""}`.toLowerCase()
        .includes(query.toLowerCase())) return false;
    return true;
  }), [tasks, active, query]);

  const FILTERS = [
    ["active", "в работе"], ["blocked", "блок"], ["proposed", "предложены"],
    ["manual", "ручные"], ["agent", "от агента"], ["done", "закрытые"],
  ];

  return (
    <>
      <div className="filterbar">
        <span className="mlabel">Фильтры</span>
        {FILTERS.map(([key, label]) => (
          <button key={key} className={`fchip ${active.includes(key) ? "active" : ""}`}
            onClick={() => setActive((prev) =>
              prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key])}>
            {label}
          </button>
        ))}
        <span className="spacer" />
        <input placeholder="поиск по задачам…" value={query}
          onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="board">
        {COLUMNS.map((col) => {
          const list = visible.filter((t) =>
            pipelineOf(t) === col.key || (col.also || []).includes(pipelineOf(t)));
          const done = col.key === "DONE" ? list.length : 0;
          const pct = list.length ? Math.round((100 * done) / list.length) : 0;
          return (
            <div className="col" key={col.key}>
              <div className="col-head">
                <span className="dot" style={{ background: col.dot }} />
                <span className="name">{col.title}</span>
                <span className="count">{list.length}</span>
              </div>
              <div className="col-underline">
                <i style={{ width: `${pct}%`, background: col.dot }} />
              </div>
              <span className={`col-mode mode-${col.mode}`}>{col.modeLabel}</span>
              {col.key === "BACKLOG" && (
                <button className="add-task" onClick={onAddTask}>＋ Add task</button>
              )}
              {list.map((t) => <Card key={t.id} t={t} onOpen={onOpenTask} />)}
              {list.length === 0 && <div className="empty">—</div>}
            </div>
          );
        })}
      </div>
    </>
  );
}

export { Chip };
