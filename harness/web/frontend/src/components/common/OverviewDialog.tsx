import type { Project } from "../../types";
import { fmtTokens, fmtUsd } from "./ui";

/** Обзор всех проектов и их Stories (портфель верхнего уровня). */
export function OverviewDialog({ projects, onOpenStory, onClose }: {
  projects: Project[];
  onOpenStory: (project: string, fnr: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ width: "min(680px, 94vw)" }}>
        <h3>Проекты и Stories</h3>
        {projects.map((prj) => (
          <div key={prj.name} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span className="fnr mono" style={{ color: "var(--acc)", fontWeight: 700 }}>{prj.name}</span>
              <span className="meta">{prj.stories.length} Story · {prj.task_count} задач ·
                🪙 {fmtTokens(prj.usage.tokens_total)} · {fmtUsd(prj.usage.cost_usd)}</span>
            </div>
            {prj.stories.map((s) => {
              const done = (s.counts.DONE || 0) + (s.counts.VERIFIED || 0);
              const pct = s.tasks ? Math.round((100 * done) / s.tasks) : 0;
              return (
                <div className="s-item" key={s.fnr}
                  onClick={() => { onOpenStory(prj.name, s.fnr); onClose(); }}
                  style={{ cursor: "pointer", display: "flex", alignItems: "center",
                    gap: 10, padding: "7px 10px", borderTop: "1px solid var(--line)" }}>
                  <span className="fnr mono" style={{ color: "var(--acc)", fontSize: 11 }}>{s.fnr}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
                  <span className="meta">{done}/{s.tasks}</span>
                  <span className="pbar"><i style={{ width: `${pct}%` }} /></span>
                </div>
              );
            })}
            {prj.stories.length === 0 && <p className="empty">Story пока нет</p>}
          </div>
        ))}
        <div className="mrow"><button onClick={onClose}>Закрыть</button></div>
      </div>
    </div>
  );
}
