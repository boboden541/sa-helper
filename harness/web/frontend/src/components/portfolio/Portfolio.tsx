import type { Story } from "../../types";
import { UsageBadge, sumUsage } from "../common/ui";

function StoryCard({ s, onOpen }: { s: Story; onOpen: (fnr: string) => void }) {
  const done = (s.counts.DONE || 0) + (s.counts.VERIFIED || 0);
  const pct = s.tasks ? Math.round((100 * done) / s.tasks) : 0;
  const cls = s.handoff_failed ? "bad" : s.handoff_pending ? "wait" : "";
  const badge = s.handoff_failed ? <span className="badge bad">gap-report</span>
    : s.handoff_pending ? <span className="badge warn">строится план…</span>
    : s.tasks ? <span className="badge" style={{ color: "var(--ok)" }}>{pct}%</span> : null;
  const counts = Object.entries(s.counts).map(([k, v]) => `${k}:${v}`).join(" · ") || "задач ещё нет";
  return (
    <div className={`story ${cls}`} onClick={() => onOpen(s.fnr)}>
      <div className="top">
        <span className="fnr">{s.fnr}</span>
        <span className="st">{s.status}</span>
        {badge}
      </div>
      <div className="title">{s.title}</div>
      <div className="meta">{counts}</div>
      <UsageBadge usage={sumUsage(s.task_list)} />
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export function Portfolio({ stories, onOpen }: {
  stories: Story[];
  onOpen: (fnr: string) => void;
}) {
  return (
    <div className="page">
      <div className="page-head">
        <h2>Stories</h2>
        <span className="meta">{stories.length ? `${stories.length} шт.` : ""}</span>
      </div>
      <div className="stories">
        {stories.length === 0
          ? <p className="empty">Stories пока нет — нажмите «+ Создать».</p>
          : stories.map((s) => <StoryCard key={s.fnr} s={s} onOpen={onOpen} />)}
      </div>
    </div>
  );
}
