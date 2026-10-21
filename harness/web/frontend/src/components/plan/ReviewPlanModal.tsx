import { useState } from "react";
import type { BoardState } from "../../types";
import { api } from "../../api";
import { toast } from "../common/toasts";

/** Экран «Ревью плана» (СТ FNR-11 5.1.2): состав задач Story до апрува —
 *  правка описания (карточка), удаление черновиков, добавление, апрув. */
export function ReviewPlanModal({ state, onOpenTask, onAddTask, onClose, onChanged }: {
  state: BoardState;
  onOpenTask: (tid: string) => void;
  onAddTask: () => void;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const drafts = (state.manifest.tasks || []).filter((t) => t.pipeline === "PROPOSED");
  const others = (state.manifest.tasks || []).filter((t) => t.pipeline !== "PROPOSED");

  const del = (tid: string) => {
    if (!window.confirm(`Удалить черновик ${tid}? Диалог перенесётся в журнал Story.`)) return;
    setBusy(tid);
    api.deleteTask(tid).then((r) => {
      if (r.ok) {
        toast.ok(`Черновик ${tid} удалён (в журнале: ${r.archived_items})`);
        if (r.freed_dependents.length) {
          toast.info(`Зависимости сняты: ${r.freed_dependents.join(", ")}`);
        }
        onChanged();
      } else {
        toast.err(r.error || "Не удалось удалить");
      }
    }).finally(() => setBusy(null));
  };

  const accept = (tid: string) => {
    setBusy(tid);
    api.move(tid, "BACKLOG").then((r) => {
      if (r.ok && !r.noop) toast.ok(`${tid} принят в бэклог досрочно`);
      onChanged();
    }).catch((e) => toast.err(e.message)).finally(() => setBusy(null));
  };

  const reject = (tid: string) => {
    if (!window.confirm(`Отклонить черновик ${tid}? Он уйдёт в снятые.`)) return;
    setBusy(tid);
    api.move(tid, "ABORTED").then((r) => {
      if (r.ok && !r.noop) toast.info(`${tid} отклонён (снят)`);
      onChanged();
    }).catch((e) => toast.err(e.message)).finally(() => setBusy(null));
  };

  const approve = () => {
    setBusy("__approve");
    api.setFlag("APPROVE_PLAN").then(() => {
      toast.ok("План утверждён — черновики в бэклоге, конвейер запускается");
      onChanged();
      onClose();
    }).catch((e) => toast.err(e.message)).finally(() => setBusy(null));
  };

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ width: "min(620px, 94vw)", maxHeight: "90vh", overflow: "auto" }}>
        <h3>Ревью плана — состав до апрува</h3>
        <div className="meta" style={{ marginBottom: 10 }}>
          Задачи-черновики не стартуют, пока план не утверждён. Правьте описания
          (карточка), удаляйте лишнее, добавляйте недостающее — и утверждайте.
        </div>

        {drafts.length === 0 && others.length === 0 && (
          <div className="empty">Состав пуст — добавьте первую задачу.</div>
        )}

        {drafts.map((t) => (
          <div key={t.id} className="s-item" style={{ border: "1px solid var(--line)",
            borderRadius: 8, padding: "8px 10px", marginBottom: 8,
            opacity: busy === t.id ? 0.5 : 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="fnr mono">{t.id}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</span>
              <span className="meta">черновик</span>
            </div>
            {t.depends_on?.length ? (
              <div className="meta" style={{ marginTop: 4 }}>зависит от: {t.depends_on.join(", ")}</div>
            ) : null}
            <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <button onClick={() => onOpenTask(t.id)}>✎ Описание</button>
              <button disabled={busy === t.id} onClick={() => accept(t.id)}>✓ Принять</button>
              <button disabled={busy === t.id} onClick={() => reject(t.id)}>✖ Отклонить</button>
              <button disabled={busy === t.id}
                onClick={() => del(t.id)}
                style={{ color: "var(--bad)" }}>🗑 Удалить</button>
            </div>
          </div>
        ))}

        {others.length > 0 && (
          <div className="meta" style={{ margin: "10px 0 6px" }}>
            Уже в бэклоге/работе: {others.map((t) => t.id).join(", ")}
          </div>
        )}

        <div className="mrow" style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button onClick={onAddTask}>＋ Добавить задачу</button>
          <span style={{ flex: 1 }} />
          {confirmApprove ? (
            <>
              <button className="ghost" onClick={() => setConfirmApprove(false)}>Отмена</button>
              <button className="primary" disabled={busy === "__approve"} onClick={approve}>
                Утвердить {drafts.length} черновик(ов)?
              </button>
            </>
          ) : (
            <button className="primary" disabled={drafts.length === 0 && others.length > 0}
              onClick={() => setConfirmApprove(true)}>
              ✓ Утвердить план
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
