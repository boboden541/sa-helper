import { useCallback, useEffect, useRef, useState } from "react";
import type { Task, TaskDoc } from "../../types";
import { api, pipelineOf, PIPE_RU } from "../../api";
import { ChecklistView, Chip, inline, md, parseComments, UsageBadge } from "../common/ui";

type Tab = "impl" | "review" | "comments" | "history";

const ACTION_LABELS: Record<string, string> = {
  REQUEST_CHANGES: "Вернуть на доработку",
  FORCE_APPROVE: "Принять (force)",
  RETRY: "Повторить",
  RESUME_WORK: "Возобновить",
  PAUSE: "Пауза",
  ABORT: "Остановить",
};

function SessionLog({ taskId }: { taskId: string }) {
  const [log, setLog] = useState<{ log: string; file: string | null } | null>(null);
  useEffect(() => {
    const load = () => api.log(taskId).then(setLog).catch(() => {});
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [taskId]);
  if (!log) return <p className="empty">загрузка…</p>;
  return (
    <div>
      <div className="meta" style={{ marginBottom: 6 }}>
        {log.file ? `${log.file} · хроника сессии` : "стадия ещё не запускалась"}
      </div>
      <pre className="plog">{log.log || "лог стадии пока пуст"}</pre>
    </div>
  );
}

function History({ taskId }: { taskId: string }) {
  const [entries, setEntries] = useState<Array<{ ts: string; text: string }> | null>(null);
  useEffect(() => {
    api.timeline(taskId).then((d) => setEntries(d.entries)).catch(() => setEntries([]));
  }, [taskId]);
  if (entries === null) return <p className="empty">загрузка…</p>;
  if (entries.length === 0) return <p className="empty">событий в журнале демона пока нет</p>;
  return (
    <ul className="timeline">
      {entries.map((e, i) => (
        <li key={i}><span className="ts">{e.ts}</span>{e.text}</li>
      ))}
    </ul>
  );
}

function Attachments({ taskId }: { taskId: string }) {
  const [files, setFiles] = useState<string[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const load = useCallback(() =>
    api.attachments(taskId).then((d) => setFiles(d.files)).catch(() => {}), [taskId]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="sect">
      <div className="s-title">Вложения</div>
      {(files || []).length === 0 && <p className="empty">вложений нет</p>}
      {(files || []).map((f) => (
        <div key={f} style={{ padding: "2px 0" }}>
          <a href={api.attachmentUrl(taskId, f)} target="_blank" rel="noreferrer"
            style={{ color: "var(--acc)", fontSize: 12.5 }}>📎 {f}</a>
        </div>
      ))}
      <input ref={fileRef} type="file" style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          f.arrayBuffer().then((buf) =>
            api.uploadAttachment(taskId, f.name, buf)).then(load);
          e.target.value = "";
        }} />
      <button className="ghost" style={{ marginTop: 6 }}
        onClick={() => fileRef.current?.click()}>＋ прикрепить файл</button>
    </div>
  );
}

/** Панель задачи: 2 колонки (редактируемое | хроники), как в aif-handoff. */
export function TaskPanel({ doc, onClose, onAction }: {
  doc: TaskDoc | null;
  onClose: () => void;
  onAction: () => void;
}) {
  const [tab, setTab] = useState<Tab | "comments">("comments");
  const [pendingFlag, setPendingFlag] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [descDraft, setDescDraft] = useState("");
  const [width, setWidth] = useState(() =>
    Number(localStorage.getItem("sheetWidth")) || 1020);
  const resizing = useRef(false);
  const cInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setEditing(false); setTab("comments"); }, [doc?.task?.id]);

  // ресайз панели за левую кромку (замечание 4)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      setWidth(Math.min(window.innerWidth - 24,
        Math.max(460, window.innerWidth - e.clientX)));
    };
    const onUp = () => {
      if (resizing.current) {
        resizing.current = false;
        localStorage.setItem("sheetWidth", String(width));
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp); };
  }, [width]);

  const t: Task | null = doc?.task ?? null;
  const p = t ? pipelineOf(t) : "BACKLOG";  // при t=null сразу вернём null ниже
  const comments = doc ? parseComments(doc.comments_md) : [];
  const reviewComments = comments.filter((c) => c.author === "reviewer");
  const humanComments = comments.filter((c) => c.author !== "reviewer");

  // ВСЕ хуки — до раннего return: иначе при null→doc меняется их число
  // и React размонтирует приложение («Rendered more hooks…»)
  const send = useCallback(() => {
    const text = cInputRef.current?.value.trim();
    if (!text || !t?.id) return;
    const isIntervention = p === "NEEDS_HUMAN" || p === "BLOCKED";
    const isDone = p === "DONE";
    api.comment(t.id, text).then(() => {
      if (cInputRef.current) cInputRef.current.value = "";
      if (isIntervention) return api.setFlag(`TASK_${t.id}_RETRY`);
      if (isDone) return api.setFlag(`TASK_${t.id}_REQUEST_CHANGES`);
      return undefined;
    }).then(() => onAction());
  }, [t, p, onAction]);

  const saveDescription = () => {
    if (!t) return;
    api.editTaskDescription(t.id, descDraft).then(() => {
      setEditing(false);
      onAction();
    });
  };

  if (!doc || !t) return null;

  const renderComments = (list: typeof comments) => (
    <div className="md">
      {list.length === 0 && <p className="empty">записей нет</p>}
      {list.map((c, i) => (
        <div className={`comment ${c.author}`} key={i}>
          <div className="cmeta">{c.ts} · {c.author}</div>
          <div dangerouslySetInnerHTML={{ __html: inline(c.text).replace(/\n/g, "<br>") }} />
        </div>
      ))}
    </div>
  );

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="sheet" style={{ width: `min(${width}px, 97vw)` }}>
        <div className="sheet-resize" onMouseDown={() => { resizing.current = true; }} />
        <div className="sheet-head">
          <span className="tid">{t.id}</span>
          <Chip pipeline={p} />
          <span className="meta">{PIPE_RU[p] || p}</span>
          {(t.move_targets || []).length > 0 && (
            <select defaultValue="" title="Переместить в допустимый статус"
              style={{ background: "var(--chip)", color: "var(--text)",
                border: "1px solid var(--line2)", borderRadius: 6, padding: "3px 6px",
                font: "11.5px var(--mono)" }}
              onChange={(e) => { const to = e.target.value;
                if (to) { api.move(t.id, to).then(onAction); } e.target.value = ""; }}>
              <option value="">переместить в…</option>
              {(t.move_targets || []).map((to) => (
                <option key={to} value={to}>{PIPE_RU[to] || to}</option>
              ))}
            </select>
          )}
          <UsageBadge usage={t.usage} />
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>✕</button>
        </div>

        {tab === "comments" && (
          <div style={{ padding: "10px 18px 0" }}>
            <div className="pfoot" style={{ border: 0, padding: 0 }}>
              <input ref={cInputRef} placeholder={
                p === "NEEDS_HUMAN" || p === "BLOCKED" ? "Ваш ответ задаче… (вернёт её в работу)"
                : p === "DONE" ? "Что переделать… (задание доработки)"
                : "Комментарий к задаче…"}
                onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
              <button className={
                p === "NEEDS_HUMAN" || p === "BLOCKED" || p === "DONE" ? "primary" : ""}
                onClick={send}>
                {p === "NEEDS_HUMAN" || p === "BLOCKED" ? "Ответить и вернуть в работу"
                  : p === "DONE" ? "Вернуть на доработку" : "Отправить"}
              </button>
              {t.can_ask && (
                <button className="quiet" title="Уйдёт в сессию задачи"
                  onClick={() => {
                    const text = cInputRef.current?.value.trim();
                    if (!text) return;
                    api.ask(t.id, text).then(() => {
                      if (cInputRef.current) cInputRef.current.value = "";
                      onAction();
                    });
                  }}>спросить агента</button>
              )}
            </div>
          </div>
        )}

        <div className="sheet-grid">
          {/* левая колонка: редактируемое */}
          <div className="sheet-col">
            {(doc.options?.options || []).length > 0 && (
              <div className="sect">
                <div className="s-title">Варианты от Steward — выберите один</div>
                {(doc.options?.options || []).map((o, i) => (
                  <div key={i} className="pick-option"
                    style={{ border: o.recommended ? "1px solid var(--ok)"
                      : "1px solid var(--line2)", borderRadius: 8,
                      padding: "8px 10px", margin: "6px 0", cursor: "pointer" }}
                    onClick={() => {
                      if (o.flag) { setPendingFlag(o.flag);
                        api.setFlag(o.flag).then(onAction);
                        api.stewardMessage(`Человек выбрал вариант: «${o.title}»`).catch(() => {});
                      } else {
                        api.stewardMessage("Человек выбрал: разобраться вручную").catch(() => {});
                      }
                    }}>
                    <div style={{ fontWeight: 600 }}>
                      {o.recommended ? "⭐ " : ""}{i + 1}. {o.title}
                    </div>
                    {o.explanation && <div className="meta">{o.explanation}</div>}
                  </div>
                ))}
                <div className="hint">Не подошло ни одно — напишите свой вариант
                  в поле ниже (вкладка «Комментарии»), Steward его увидит.</div>
              </div>
            )}
            <div className="sect">
              <div className="s-title">Карточка задачи</div>
              <div className="md" dangerouslySetInnerHTML={{ __html: md(doc.card_md) }} />
            </div>

            <div className="sect">
              <div className="s-title">Описание (краткое, редактируемое)
                {!editing && (
                  <button className="ghost" style={{ marginLeft: "auto", padding: "0 4px" }}
                    onClick={() => { setDescDraft(t.description || ""); setEditing(true); }}>
                    ✎
                  </button>
                )}
              </div>
              {editing ? (
                <>
                  <textarea value={descDraft} onChange={(e) => setDescDraft(e.target.value)}
                    style={{ width: "100%", minHeight: 80, background: "var(--chip)",
                      color: "var(--text)", border: "1px solid var(--line2)",
                      borderRadius: 6, padding: 8, font: "inherit" }} />
                  <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                    <button className="primary" onClick={saveDescription}>Сохранить</button>
                    <button className="ghost" onClick={() => setEditing(false)}>Отмена</button>
                  </div>
                </>
              ) : (
                <div className="md">{t.description || <span className="empty">—</span>}</div>
              )}
            </div>

            {(p === "NEEDS_HUMAN" || p === "BLOCKED") && (
              <div id="p-banner">
                <span className="btitle">{p === "BLOCKED" ? "⛔ Задача заблокирована"
                  : "⏸ Требуется ваше участие"}</span> — отчёт во вкладке «Комментарии».
              </div>
            )}

            <div className="sect">
              <div className="s-title">Действия</div>
              <div id="p-actions" style={{ marginBottom: 0 }}>
                {(t.actions || []).map((flag) => {
                  const key = flag.split("_").slice(2).join("_");
                  const label = key === "RESUME_WORK" ? (t.paused ? "Продолжить" : "Возобновить")
                    : ACTION_LABELS[key];
                  if (!label) return null;
                  const busy = pendingFlag === flag;
                  return (
                    <button key={flag} disabled={pendingFlag !== null}
                      style={key === "ABORT" ? { color: "var(--bad)" } : undefined}
                      title={busy ? "Команда принята — демон применит её на ближайшем тике (до 5 с)"
                        : "Отправить команду демону"}
                      onClick={() => { setPendingFlag(flag); api.setFlag(flag).then(onAction); }}>
                      {busy ? "⟳ принята, ждём демона…" : label}
                    </button>
                  );
                })}
                {pendingFlag && (
                  <span className="meta" style={{ width: "100%" }}>
                    Команда принята. Доска обновится, как только демон заберёт её (до 5 с).
                  </span>
                )}
                {(t.actions || []).length === 0 && <span className="empty">—</span>}
              </div>
            </div>

            <div className="sect">
              <div className="s-title">Worktree</div>
              <div className="mono" style={{ fontSize: 11.5, wordBreak: "break-all" }}>
                {t.branch || "—"}
              </div>
            </div>

            <div className="sect">
              <div className="s-title">План (чек-лист)</div>
              <ChecklistView sections={doc.checklist_sections || []} />
            </div>

            <Attachments taskId={t.id} />
          </div>

          {/* правая колонка: вкладки-хроники */}
          <div className="sheet-col">
            <div className="sheet-tabs">
              {([["impl", "Лог реализации"], ["review", "Ревью"],
                 ["comments", "Комментарии"], ["history", "История"]] as const).map(([key, label]) => (
                <button key={key} className={`tabbtn ${tab === key ? "active" : ""}`}
                  onClick={() => setTab(key)}>
                  {key === "review" ? `${label} (${reviewComments.length})`
                    : key === "comments" ? `Комментарии (${comments.length})` : label}
                </button>
              ))}
            </div>
            {tab === "impl" && <SessionLog taskId={t.id} />}
            {tab === "review" && renderComments(reviewComments)}
            {tab === "comments" && renderComments(humanComments)}
            {tab === "history" && <History taskId={t.id} />}
          </div>
        </div>
      </div>
    </>
  );
}
