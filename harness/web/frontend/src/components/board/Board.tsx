import { useMemo, useState } from "react";
import type { BoardState, Task } from "../../types";
import { pipelineOf, PIPE_RU } from "../../api";
import { Chip, LiveDot, ProgressBar, UsageBadge } from "../common/ui";

const COLUMNS: Array<{ key: string; title: string; also?: string[] }> = [
  { key: "PROPOSED", title: "Предложены" },
  { key: "BACKLOG", title: "Бэклог" },
  { key: "READY", title: "Готовы к запуску" },
  { key: "IMPLEMENTING", title: "В работе" },
  { key: "REVIEW", title: "Ревью" },
  { key: "DONE", title: "Готовы" },
  { key: "VERIFIED", title: "Проверены" },
  { key: "BLOCKED", title: "Блок / Нужен человек", also: ["NEEDS_HUMAN", "ABORTED"] },
];

const FILTERS = [
  { key: "active", label: "в работе", test: (p: string) => ["IMPLEMENTING", "REVIEW", "READY"].includes(p) },
  { key: "blocked", label: "блок", test: (p: string) => ["BLOCKED", "NEEDS_HUMAN"].includes(p) },
  { key: "proposed", label: "предложены", test: (p: string) => p === "PROPOSED" },
  { key: "manual", label: "ручные", test: (_p: string, t: Task) => t.origin === "manual" },
  { key: "agent", label: "от агента", test: (_p: string, t: Task) => t.origin === "agent" },
  { key: "done", label: "закрытые", test: (p: string) => ["DONE", "VERIFIED"].includes(p) },
];

function LiveLabel({ t }: { t: Task }) {
  const lv = t.live;
  if (!lv) return null;
  const age = lv.hb_age_s < 60 ? `${lv.hb_age_s}с` : `${Math.round(lv.hb_age_s / 60)}мин`;
  if (lv.running && lv.hb_age_s < 180) return <><LiveDot running />агент работает · {age}</>;
  if (lv.running) return <><LiveDot running={false} />без вывода {age}</>;
  return <>завершена {age} назад</>;
}

function TaskCardView({ t, onOpen }: { t: Task; onOpen: (id: string) => void }) {
  const p = pipelineOf(t);
  const acs = t.acceptance_criteria || [];
  const passed = acs.filter((a) => a.status === "PASSED").length;
  const inner = t.status && !["PLANNED", "APPROVED"].includes(t.status) ? t.status : null;
  return (
    <div className={`tcard st-${p}`} onClick={() => onOpen(t.id)}>
      <div className="row1">
        <span className="tid">{t.id}</span>
        <span className="pipeline-label">{PIPE_RU[p] || p}</span>
        {inner && <span>· {inner}</span>}
        {t.paused && <span style={{ color: "var(--warn)" }}>⏸</span>}
        <span className="sys">{t.system}</span>
      </div>
      <div className="ttitle">{t.title}</div>
      {t.description && <div className="desc">{t.description}</div>}
      <div className="foot">
        {!!t.review_iterations && <span>ревью: {t.review_iterations}/3</span>}
        {t.checklist && t.checklist.total > 0 &&
          <span className="chkline">☑ {t.checklist.done}/{t.checklist.total}</span>}
        <span className="grow" />
        <UsageBadge usage={t.usage} />
        {acs.length > 0 && <span>AC {passed}/{acs.length}</span>}
      </div>
      {t.live && <div className="meta" style={{ marginTop: 4 }}><LiveLabel t={t} /></div>}
    </div>
  );
}

export function Board({ state, onOpenTask }: {
  state: BoardState;
  onOpenTask: (id: string) => void;
}) {
  const [view, setView] = useState<"board" | "list">("board");
  const [active, setActive] = useState<string[]>([]);
  const [query, setQuery] = useState("");

  const tasks = state.manifest.tasks || [];
  const visible = useMemo(() => tasks.filter((t) => {
    const p = pipelineOf(t);
    for (const f of active) {
      const def = FILTERS.find((x) => x.key === f);
      if (def && !def.test(p, t)) return false;
    }
    if (query && !`${t.id} ${t.title} ${t.description || ""}`.toLowerCase().includes(query.toLowerCase()))
      return false;
    return true;
  }), [tasks, active, query]);

  const toggle = (key: string) =>
    setActive((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));

  const controls = (
    <div className="filterbar">
      <input placeholder="Поиск задачи…" value={query}
        onChange={(e) => setQuery(e.target.value)} />
      {FILTERS.map((f) => (
        <button key={f.key}
          className={`fchip ${active.includes(f.key) ? "active" : ""}`}
          onClick={() => toggle(f.key)}>{f.label}</button>
      ))}
      <span className="spacer" />
      <div className="seg">
        <button className={view === "board" ? "active" : ""} onClick={() => setView("board")}>Доска</button>
        <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>Список</button>
      </div>
    </div>
  );

  const kanban = (
    <div className="board">
      {COLUMNS.map((col) => {
        const list = visible.filter((t) => pipelineOf(t) === col.key || (col.also || []).includes(pipelineOf(t)));
        return (
          <div className="col" key={col.key}>
            <h2>{col.title}<span className="count">{list.length}</span></h2>
            {list.length === 0 && <div className="empty">—</div>}
            {list.map((t) => <TaskCardView key={t.id} t={t} onOpen={onOpenTask} />)}
          </div>
        );
      })}
    </div>
  );

  const list = (
    <div className="page">
      <table className="tasks">
        <thead><tr>
          <th style={{ width: 56 }}>ID</th><th>Задача</th><th style={{ width: 150 }}>Статус</th>
          <th style={{ width: 120 }}>Система</th><th style={{ width: 150 }}>Прогресс</th>
        </tr></thead>
        <tbody>
          {visible.length === 0 && <tr><td colSpan={5}><p className="empty">Задач нет</p></td></tr>}
          {visible.map((t) => (
            <tr key={t.id} onClick={() => onOpenTask(t.id)}>
              <td><b style={{ color: "var(--acc)" }}>{t.id}</b></td>
              <td>{t.title}</td>
              <td>{chipWithLive(t)}</td>
              <td>{t.system || "—"}</td>
              <td>{t.checklist && t.checklist.total > 0
                ? <ProgressBar done={t.checklist.done} total={t.checklist.total} /> : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <>
      {controls}
      {view === "board" ? kanban : list}
    </>
  );
}

function chipWithLive(t: Task) {
  const live = t.live && t.live.running;
  return (
    <>
      <Chip pipeline={pipelineOf(t)} />
      {live && <LiveDot running />}
    </>
  );
}
