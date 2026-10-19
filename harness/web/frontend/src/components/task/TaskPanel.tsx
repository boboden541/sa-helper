import { useCallback, useEffect, useRef, useState } from "react";
import type { Task, TaskDoc } from "../../types";
import { api, pipelineOf, PIPE_RU } from "../../api";
import { ChecklistView, inline, md, parseComments } from "../common/ui";
import { StatusFlowMap } from "../common/StatusFlowMap";

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

function renderComments(list: Array<{ ts: string; author: string; text: string }>) {
  return (
    <div className="md">
      {list.length === 0 && <p className="empty">записей нет</p>}
      {list.map((c, i) => (
        <div key={i} className={`comment ${c.author}`}>
          <div className="cmeta">{c.ts} · {c.author}</div>
          <div dangerouslySetInnerHTML={{ __html: inline(c.text).replace(/\n/g, "<br>") }} />
        </div>
      ))}
    </div>
  );
}

/** Панель задачи — по макету v3: статус крупно и кликабелен (карта переходов),
 *  блок причины сверху только для Блок/Нужен человек, одна колонка
 *  сворачиваемых секций (Постановка первая), Обсуждение — последний, всегда раскрыт. */
export function TaskPanel({ doc, onClose, onAction }: {
  doc: TaskDoc | null;
  onClose: () => void;
  onAction: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [descDraft, setDescDraft] = useState("");
  const [width, setWidth] = useState(() =>
    Number(localStorage.getItem("sheetWidth")) || 1020);
  const [resizeOn, setResizeOn] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const cInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setEditing(false); }, [doc?.task?.id]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizeOn) return;
      setWidth(Math.min(window.innerWidth - 24,
        Math.max(460, window.innerWidth - e.clientX)));
    };
    const onUp = () => {
      if (resizeOn) {
        localStorage.setItem("sheetWidth", String(width));
        setResizeOn(false);
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp); };
  }, [width, resizeOn]);

  const t: Task | null = doc?.task ?? null;
  const p = t ? pipelineOf(t) : "BACKLOG";
  const comments = doc ? parseComments(doc.comments_md) : [];
  const reviewComments = comments.filter((c) => c.author === "reviewer");
  const humanComments = comments.filter((c) => c.author !== "reviewer");


  const applyFlag = useCallback((flag: string) => {
    api.setFlag(flag).then(onAction);
  }, [onAction]);

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

  const problem = doc.problem;
  const options = doc.options?.options || [];
  const isAttention = p === "BLOCKED" || p === "NEEDS_HUMAN";

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="sheet" style={{ width: `min(${width}px, 97vw)` }}>
        <div className="sheet-resize" onMouseDown={() => setResizeOn(true)} />

        {/* ── шапка: статус крупно, клик — карта переходов ── */}
        <div className="sh-head">
          <div className="crumb">vitrina / FNR_8 / {t.id}</div>
          <div className="r1">
            <span className="bignum">{t.id}</span>
            <span className="stbig" onClick={() => setFlowOpen((v) => !v)}
              title="Нажмите — карта возможных переходов">
              {PIPE_RU[p] || p} ▾
            </span>
            <span className="meta">{t.system}</span>
            <span className="actions">
              {isAttention && (
                <button className="primary"
                  onClick={() => applyFlag(`TASK_${t.id}_RETRY`)}>▶ Вернуть в работу</button>
              )}
              {p === "DONE" && (
                <button className="primary"
                  onClick={() => applyFlag(`TASK_${t.id}_REQUEST_CHANGES`)}>Вернуть на доработку</button>
              )}
              <div className="more-wrap">
                <button className="ghost" onClick={() => setMoreOpen((v) => !v)}>Ещё ▾</button>
                {moreOpen && (
                  <div className="more-menu">
                    <div onClick={() => { setFlowOpen(true); setMoreOpen(false); }}>🗺 Карта переходов</div>
                    <div onClick={() => {
                      navigator.clipboard?.writeText(t.branch || ""); setMoreOpen(false);
                    }}>⧉ Скопировать ветку</div>
                    <div onClick={() => {
                      const blob = new Blob([doc.card_md], { type: "text/markdown" });
                      const a = document.createElement("a");
                      a.href = URL.createObjectURL(blob);
                      a.download = `${t.id}.md`; a.click(); setMoreOpen(false);
                    }}>⇩ Экспорт карточки</div>
                  </div>
                )}
              </div>
              <button className="ghost" onClick={onClose}>✕</button>
            </span>
          </div>
          <h1>{t.title}</h1>
          <div className="usage">
            <span>🪙 {fmtTok(t.usage?.tokens_total)}</span>
            <span>{fmtUsd(t.usage?.cost_usd)}</span>
            <span>{t.usage?.sessions ?? 0} сессий</span>
            <span>ветка: {t.branch || "—"}</span>
            {t.checklist && t.checklist.total > 0 &&
              <span>чек-лист: {t.checklist.done}/{t.checklist.total}</span>}
          </div>
        </div>

        {/* ── карта переходов (поповер по клику на статус) ── */}
        {flowOpen && (
          <div className="flowpop" onClick={(e) => e.stopPropagation()}>
            <div className="ft">Карта статусов — допустимые переходы подсвечены</div>
            <StatusFlowMap current={p} onMove={(to) => {
              const flagMap: Record<string, string> = {
                BACKLOG: `TASK_${t.id}_ACCEPT`,
                IMPLEMENTING: `TASK_${t.id}_RETRY`,
                DONE: `TASK_${t.id}_FORCE_APPROVE`,
              };
              const flag = flagMap[to];
              if (flag) applyFlag(flag); else api.move(t.id, to).then(onAction);
              setFlowOpen(false);
            }} />
            <div className="legend">
              <span className="l-acc">сплошная стрелка — допустимый переход</span>
              <span className="l-dim">пунктир — недоступен сейчас</span>
            </div>
          </div>
        )}

        <div className="sh-body">
          {/* ── блок причины: только Блок/Нужен человек ── */}
          {isAttention && (
            <div className="alert">
              <div className="a-head">
                <div className="t">{p === "BLOCKED" ? "⛔ Почему задача заблокирована"
                  : "⏸ Почему задача требует вашего участия"}</div>
              </div>
              <div className="a-body">
                <div className="a-cause">
                  {problem?.reason
                    ? <div className="step">{problem.reason}</div>
                    : <div className="step">Причина уточняется — см. итог последней сессии ниже</div>}
                  {problem?.last_result &&
                    <div className="step">Итог последней сессии: {problem.last_result.slice(0, 300)}</div>}
                  <div className="step">Незакрытые замечания ревью: {
                    (problem?.findings || []).length || "нет"}</div>
                  <div className="step">Лимиты: перезапусков {problem?.retries ?? 0},
                    итераций ревью {problem?.review_iterations ?? 0}/3</div>
                </div>
                <div className="a-hint">Кнопка «Вернуть в работу» в шапке вернёт задачу
                  с места остановки; свободный текст — в «Обсуждении» ниже.</div>
              </div>
            </div>
          )}

          {/* ── Постановка: первый раздел ── */}
          <div className="sect">
            <div className="s-title">Постановка — полная, из СТ
              {!editing && (
                <button className="ghost" style={{ marginLeft: "auto", padding: "0 4px" }}
                  onClick={() => { setDescDraft(t.description || ""); setEditing(true); }}>
                  ✎ править краткое
                </button>
              )}
            </div>
            <div className="md" dangerouslySetInnerHTML={{ __html: md(doc.card_md) }} />
            {editing && (
              <div style={{ marginTop: 8 }}>
                <textarea value={descDraft} onChange={(e) => setDescDraft(e.target.value)}
                  style={{ width: "100%", minHeight: 80, background: "var(--chip)",
                    color: "var(--text)", border: "1px solid var(--line2)",
                    borderRadius: 6, padding: 8, font: "inherit" }} />
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <button className="primary" onClick={saveDescription}>Сохранить</button>
                  <button className="ghost" onClick={() => setEditing(false)}>Отмена</button>
                </div>
              </div>
            )}
          </div>

          {/* ── Варианты Steward (при эскалации) ── */}
          {options.length > 0 && (
            <div className="sect">
              <div className="s-title">Варианты от Steward</div>
              {options.map((o, i) => (
                <div key={i} className="a-opt" style={o.recommended
                  ? { borderColor: "var(--ok)", background: "rgba(63,185,80,.05)" } : undefined}
                  onClick={() => {
                    if (o.flag) { applyFlag(o.flag);
                      api.stewardMessage(`Человек выбрал вариант: «${o.title}»`).catch(() => {});
                    }
                  }}>
                  <span className="num">{o.recommended ? "⭐" : i + 1}</span>
                  <span style={{ flex: 1 }}>
                    <span className="ot">{o.title}</span>
                    {o.explanation && <div className="oe">{o.explanation}</div>}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* ── Чек-лист ── */}
          <div className="sect">
            <div className="s-title">Чек-лист</div>
            <ChecklistView sections={doc.checklist_sections || []} />
            <div className="sess">
              <div className="l">итог последней сессии</div>
              {problem?.last_result || "сессий ещё не было"}
            </div>
          </div>

          {/* ── Ревью ── */}
          <div className="sect collapsed">
            <div className="s-title">Ревью
              {!!t.review_iterations && <span className="cnt">{t.review_iterations}/3</span>}
            </div>
            <div className="sect-b post">
              <p><b>Вердикт:</b> {t.review_verdict || "ещё не проводилось"}</p>
              <ul>
                {(t.findings || []).map((f) => (
                  <li key={f.id}>{f.text} {f.file && <span className="mono">({f.file})</span>}
                    — <i>{f.resolution}</i></li>
                ))}
              </ul>
              {renderComments(reviewComments)}
            </div>
          </div>

          {/* ── Хроники ── */}
          <div className="sect collapsed">
            <div className="s-title">Хроники</div>
            <div className="s-title" style={{ textTransform: "none", letterSpacing: 0,
              fontSize: 12.5, color: "var(--text)" }}>Лог реализации</div>
            <SessionLog taskId={t.id} />
            <div className="s-title" style={{ textTransform: "none", letterSpacing: 0,
              fontSize: 12.5, color: "var(--text)", marginTop: 10 }}>История (таймлайн)</div>
            <History taskId={t.id} />
          </div>

          {/* ── Мета ── */}
          <div className="sect collapsed">
            <div className="s-title">Мета</div>
            <div className="post">
              <p style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--dim)" }}>
                система: {t.system} · ветка: {t.branch} · origin: {t.origin} ·
                сессия: {t.session_id || "—"}</p>
            </div>
            <Attachments taskId={t.id} />
          </div>
        </div>

        {/* ── Обсуждение: последний, всегда раскрыт ── */}
        <div className="discuss">
          <div className="d-head">
            <div className="t">💬 Обсуждение</div>
            <div className="s">Человек, Steward, агенты, демон. При блокировке свободный
              текст = четвёртый вариант действий.</div>
          </div>
          <div className="d-list">
            {humanComments.length === 0 && <p className="empty" style={{ padding: "4px 16px" }}>
              записей нет</p>}
            {humanComments.map((c, i) => (
              <div key={i} className={`cmt ${c.author}`}>
                <div className="who">{c.ts} · {c.author}</div>
                <div dangerouslySetInnerHTML={{ __html: inline(c.text).replace(/\n/g, "<br>") }} />
              </div>
            ))}
          </div>
          <div className="d-input">
            <input ref={cInputRef} placeholder="Напишите Steward или команде…"
              onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
            <button className={
              isAttentionState(p) || p === "DONE" ? "primary" : ""} onClick={send}>
              {isAttentionState(p) ? "Ответить и вернуть в работу"
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
      </div>
    </>
  );
}

function isAttentionState(p: string) {
  return p === "NEEDS_HUMAN" || p === "BLOCKED";
}
function fmtTok(n?: number) {
  if (!n) return "0";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
function fmtUsd(n?: number) {
  if (n == null) return "—";
  return n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`;
}
