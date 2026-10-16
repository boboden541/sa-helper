import { useMemo, useState } from "react";
import type { BoardState } from "../../types";
import { pipelineOf } from "../../api";
import { Chip } from "../common/ui";

function timeStr(iso?: string): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString("ru-RU");
}

/** Список задач в формате aif-handoff: поиск, сортировка, 5 колонок. */
export function TaskList({ state, onOpenTask, onAddTask }: {
  state: BoardState;
  onOpenTask: (id: string) => void;
  onAddTask: () => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("updated");

  const rows = useMemo(() => {
    const tasks = [...(state.manifest.tasks || [])];
    const ql = query.trim().toLowerCase();
    const filtered = ql
      ? tasks.filter((t) => `${t.id} ${t.title} ${t.description || ""} ${t.status || ""}`
          .toLowerCase().includes(ql))
      : tasks;
    const order: Record<string, number> = { IMPLEMENTING: 0, REVIEW: 1, READY: 2,
      BLOCKED: 3, NEEDS_HUMAN: 3, PROPOSED: 4, BACKLOG: 5, DONE: 6, VERIFIED: 7, ABORTED: 8 };
    if (sort === "updated") {
      filtered.sort((a, b) => (Number(Date.parse(b.pipeline_since || "")) || 0) - (Number(Date.parse(a.pipeline_since || "")) || 0));
    } else if (sort === "status") {
      filtered.sort((a, b) => (order[pipelineOf(a)] ?? 9) - (order[pipelineOf(b)] ?? 9));
    }
    return filtered;
  }, [state, query, sort]);

  return (
    <div className="tasklist-page">
      <button className="addtask-top" onClick={onAddTask}>＋ Add task</button>
      <div className="list-tools">
        <input placeholder="Search by title, description, id, status"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="updated">Updated: newest first</option>
          <option value="status">Status</option>
        </select>
      </div>
      <table className="tasks">
        <thead><tr>
          <th>Задача</th><th style={{ width: 140 }}>Статус</th>
          <th style={{ width: 100 }}>Приоритет</th><th style={{ width: 90 }}>Владелец</th>
          <th style={{ width: 190 }}>Обновлено</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5}><p className="empty">Задач нет</p></td></tr>}
          {rows.map((t) => (
            <tr key={t.id} onClick={() => onOpenTask(t.id)}>
              <td>
                <div className="t-title">{t.title || t.id}</div>
                {t.description && <div className="t-desc">{t.description}</div>}
              </td>
              <td><Chip pipeline={pipelineOf(t)} />
                {t.live?.running && <span className="live-dot" style={{ marginLeft: 6 }} />}</td>
              <td className="mono">—</td>
              <td className="mono">{t.origin === "manual" ? "Human" : "AI"}</td>
              <td className="mono">{timeStr(t.pipeline_since)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
