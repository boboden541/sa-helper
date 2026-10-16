import type { Story } from "../../types";
import { fmtTokens, fmtUsd, sumUsage } from "./ui";

/** Диалог метрик: расход по активной Story и по всему портфелю. */
export function MetricsDialog({ stories, fnr, onClose }: {
  stories: Story[];
  fnr: string | null;
  onClose: () => void;
}) {
  const active = stories.find((s) => s.fnr === fnr);
  const total = sumUsage(stories.map((s) => ({ usage: s.usage })));
  const done = (s: Story) => (s.counts.DONE || 0) + (s.counts.VERIFIED || 0);
  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ width: "min(640px, 94vw)" }}>
        <h3>Метрики {active ? `— ${active.fnr}` : "— весь портфель"}</h3>
        {active && (
          <>
            <div className="metrics">
              <div className="metric"><div className="v">{done(active)}/{active.tasks}</div>
                <div className="l">задач закрыто</div></div>
              <div className="metric"><div className="v">{fmtTokens(active.usage?.tokens_total)}</div>
                <div className="l">токенов</div></div>
              <div className="metric"><div className="v">{fmtUsd(active.usage?.cost_usd)}</div>
                <div className="l">стоимость</div></div>
            </div>
            <table className="tasks" style={{ marginTop: 12 }}>
              <thead><tr><th>Задача</th><th style={{ width: 110 }}>Токены</th>
                <th style={{ width: 90 }}>Стоимость</th></tr></thead>
              <tbody>
                {active.task_list.filter((t) => t.usage?.tokens_total).map((t) => (
                  <tr key={t.id}>
                    <td>{t.id} — {t.title}</td>
                    <td className="mono">{fmtTokens(t.usage?.tokens_total)}</td>
                    <td className="mono">{fmtUsd(t.usage?.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <h3 style={{ marginTop: 16 }}>Портфель</h3>
        <div className="metrics">
          <div className="metric"><div className="v">{stories.length}</div>
            <div className="l">Stories</div></div>
          <div className="metric"><div className="v">{fmtTokens(total.tokens_total)}</div>
            <div className="l">токенов всего</div></div>
          <div className="metric"><div className="v">{fmtUsd(total.cost_usd)}</div>
            <div className="l">стоимость всего</div></div>
        </div>
        <div className="mrow"><button onClick={onClose}>Закрыть</button></div>
      </div>
    </div>
  );
}
