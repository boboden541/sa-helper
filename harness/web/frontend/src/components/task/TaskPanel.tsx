import { useCallback, useEffect, useRef, useState } from "react";
import type { Task, TaskDoc } from "../../types";
import { api, pipelineOf, PIPE_RU } from "../../api";
import { ChecklistView, Chip, inline, md, parseComments, UsageBadge } from "../common/ui";

type Tab = "card" | "comments" | "log" | "history" | "clk";

const ACTION_LABELS: Record<string, string> = {
  REQUEST_CHANGES: "Вернуть на доработку",
  FORCE_APPROVE: "Принять (force)",
  RETRY: "Повторить",
  RESUME_WORK: "Возобновить",
  PAUSE: "Пауза",
  ABORT: "Остановить",
};

function Comments({ raw }: { raw: string }) {
  const comments = parseComments(raw);
  return (
    <div className="md">
      {comments.length === 0 && <p className="empty">комментариев пока нет</p>}
      {comments.map((c, i) => (
        <div className={`comment ${c.author}`} key={i}>
          <div className="cmeta">{c.ts} · {c.author}</div>
          <div dangerouslySetInnerHTML={{ __html: inline(c.text).replace(/\n/g, "<br>") }} />
        </div>
      ))}
    </div>
  );
}

function Attachments({ taskId }: { taskId: string }) {
  const [files, setFiles] = useState<string[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const load = useCallback(() =>
    api.attachments(taskId).then((d) => setFiles(d.files)).catch(() => {}), [taskId]);
  useEffect(() => { load(); }, [load]);
  return (
    <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
      <div className="meta">Файлы</div>
      {(files || []).length === 0 && <p className="empty">вложений нет</p>}
      {(files || []).map((f) => (
        <div key={f} style={{ padding: "2px 0" }}>
          <a href={api.attachmentUrl(taskId, f)} target="_blank" rel="noreferrer"
            style={{ color: "var(--acc)" }}>📎 {f}</a>
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
      <button className="ghost" style={{ marginTop: 4 }}
        onClick={() => fileRef.current?.click()}>+ прикрепить файл</button>
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

export function TaskPanel({ doc, onClose, onAction }: {
  doc: TaskDoc | null;
  onClose: () => void;
  onAction: (flag: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("card");
  const [editing, setEditing] = useState(false);
  const [descDraft, setDescDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const cInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setEditing(false); setTab("card"); }, [doc?.task?.id]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const t: Task | null = doc?.task ?? null;
  if (!doc || !t) return null;
  const p = pipelineOf(t);

  const send = useCallback(() => {
    const text = cInputRef.current?.value.trim();
    if (!text || !t.id) return;
    const isIntervention = p === "NEEDS_HUMAN" || p === "BLOCKED";
    const isDone = p === "DONE";
    api.comment(t.id, text).then(() => {
      if (cInputRef.current) cInputRef.current.value = "";
      if (isIntervention) return api.setFlag(`TASK_${t.id}_RETRY`);
      if (isDone) return api.setFlag(`TASK_${t.id}_REQUEST_CHANGES`);
      return undefined;
    }).then(() => onAction(`TASK_${t.id}_RELOAD`));
  }, [t, p, onAction]);

  const saveDescription = () => {
    api.editTaskDescription(t.id, descDraft).then(() => {
      setEditing(false);
      onAction(`TASK_${t.id}_RELOAD`);
    });
  };

  const tabs: Array<[Tab, string]> = [
    ["card", "Карточка"], ["comments", `Комментарии`], ["log", "Лог"],
    ["history", "История"], ["clk", "Чек-лист"],
  ];

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="panel">
        <div className="phead">
          <span className="tid">{t.id}</span>
          <span className="meta">{t.title}</span>
          <span className="spacer" />
          {tabs.map(([key, label]) => (
            <button key={key} className={`tabbtn ${tab === key ? "active" : ""}`}
              onClick={() => setTab(key)}>
              {key === "comments"
                ? `Комментарии (${parseComments(doc.comments_md).length})` : label}
            </button>
          ))}
          <button className="ghost" onClick={onClose}>✕</button>
        </div>

        {(p === "NEEDS_HUMAN" || p === "BLOCKED") && (
          <div style={{ padding: "10px 18px 0" }}>
            <div id="p-banner">
              <span className="btitle">{p === "BLOCKED" ? "⛔ Задача заблокирована"
                : "⏸ Требуется ваше участие"}</span>
              — отчёт: в комментариях ниже.
            </div>
          </div>
        )}

        <div className="pbody">
          {tab === "card" && (
            <>
              <div className="meta" style={{ marginBottom: 8 }}>
                <Chip pipeline={p} /> · {t.system || ""} · AC{" "}
                {(t.acceptance_criteria || []).filter((a) => a.status === "PASSED").length}/
                {(t.acceptance_criteria || []).length}
                {!!t.review_iterations && ` · ревью: ${t.review_iterations}/3`}{" "}
                <UsageBadge usage={t.usage} />
              </div>
              <div id="p-actions">
                {(t.actions || []).map((flag) => {
                  const key = flag.split("_").slice(2).join("_");
                  const label = key === "RESUME_WORK" ? (t.paused ? "Продолжить" : "Возобновить")
                    : ACTION_LABELS[key];
                  if (!label) return null;
                  return (
                    <button key={flag}
                      style={key === "ABORT" ? { color: "var(--bad)" } : undefined}
                      onClick={() => onAction(flag)}>{label}</button>
                  );
                })}
                {!editing && (
                  <button style={{ color: "var(--acc)" }}
                    onClick={() => { setDescDraft(t.description || ""); setEditing(true); }}>
                    ✎ Описание
                  </button>
                )}
              </div>
              {editing ? (
                <div style={{ marginTop: 8 }}>
                  <textarea className="pedit" style={{ width: "100%", minHeight: 90,
                    background: "var(--chip)", color: "var(--text)", border: "1px solid var(--line2)",
                    borderRadius: 8, padding: 9, font: "inherit" }}
                    value={descDraft}
                    onChange={(e) => setDescDraft(e.target.value)} />
                  <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                    <button className="primary" onClick={saveDescription}>Сохранить</button>
                    <button className="ghost" onClick={() => setEditing(false)}>Отмена</button>
                  </div>
                </div>
              ) : (
                <div className="md" dangerouslySetInnerHTML={{ __html: md(doc.card_md) }} />
              )}
              <Attachments taskId={t.id} />
            </>
          )}
          {tab === "comments" && <Comments raw={doc.comments_md} />}
          {tab === "log" && <SessionLog taskId={t.id} />}
          {tab === "history" && <History taskId={t.id} />}
          {tab === "clk" && <ChecklistView sections={doc.checklist_sections || []} />}
        </div>

        <div className="pfoot">
          <input ref={cInputRef}
            placeholder={
              p === "NEEDS_HUMAN" || p === "BLOCKED" ? "Ваш ответ задаче… (вернёт её в работу)"
              : p === "DONE" ? "Что переделать… (задание доработки)"
              : "Ваш комментарий к задаче…"}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
          <button className={
            p === "NEEDS_HUMAN" || p === "BLOCKED" || p === "DONE" ? "primary" : ""}
            onClick={send}>
            {p === "NEEDS_HUMAN" || p === "BLOCKED" ? "Ответить и вернуть в работу"
              : p === "DONE" ? "Вернуть на доработку" : "Отправить"}
          </button>
          {t.can_ask && (
            <button className="quiet" title="Уйдёт в сессию задачи; ответ появится в журнале"
              onClick={() => {
                const text = cInputRef.current?.value.trim();
                if (!text) return;
                api.ask(t.id, text).then(() => {
                  if (cInputRef.current) cInputRef.current.value = "";
                });
              }}>спросить агента</button>
          )}
        </div>
      </div>
    </>
  );
}

export { PIPE_RU };
