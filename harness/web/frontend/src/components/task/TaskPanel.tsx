import { useCallback, useEffect, useRef, useState } from "react";
import type { Task, TaskDoc } from "../../types";
import { api, pipelineOf, PIPE_ICON, PIPE_RU } from "../../api";
import { inline, md, parseComments } from "../common/ui";
import { StatusFlowMap } from "../common/StatusFlowMap";
import { CardEditor, cardEditorConfirmClose } from "./CardEditor";
import { ChecklistEditor } from "./ChecklistEditor";
import { toast } from "../common/toasts";


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
    <div>
      <div className="meta" style={{ margin: "10px 0 4px" }}>Вложения</div>
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

/** Секция панели по канону макета (.sect-h: caret + заголовок + cnt + свернуть).
 *  Без своих хуков; содержимое монтируется только в раскрытом состоянии,
 *  поэтому хуки детей (SessionLog/History/Attachments) не нарушают порядок. */
function Sect({ collapsed, onToggle, title, cnt, headExtra, bodyClass, children }: {
  collapsed: boolean;
  onToggle: () => void;
  title: string;
  cnt?: React.ReactNode;
  headExtra?: React.ReactNode;
  bodyClass?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`sect ${collapsed ? "collapsed" : ""}`}>
      <div className="sect-h" onClick={onToggle}>
        <span className="caret">▾</span>
        <span className="t">{title}</span>
        {cnt}
        {headExtra}
        <span className="tog">{collapsed ? "развернуть" : "свернуть"}</span>
      </div>
      {!collapsed && <div className={`sect-b ${bodyClass || ""}`}>{children}</div>}
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
  const [width, setWidth] = useState(() =>
    Number(localStorage.getItem("sheetWidth")) || 760);
  const [resizeOn, setResizeOn] = useState(false);
  // карта переходов: позиция у кликнутого статуса (макет:549–556)
  const [flowAt, setFlowAt] = useState<{ left: number; top: number } | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  // свёртывание секций (макет: Хроники/Ревью/Мета по умолчанию свернуты)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({
    review: true, chronicles: true, meta: true,
  });
  const cInputRef = useRef<HTMLInputElement>(null);
  const moreWrapRef = useRef<HTMLDivElement>(null);
  const flowRef = useRef<HTMLDivElement>(null);
  const stbigRef = useRef<HTMLSpanElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const attachRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setEditing(false); }, [doc?.task?.id]);

  // закрытие more-menu и карты переходов по клику вне (макет:557–560)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const el = e.target as Node;
      if (moreWrapRef.current && !moreWrapRef.current.contains(el)) setMoreOpen(false);
      if (flowRef.current && !flowRef.current.contains(el)
          && stbigRef.current && !stbigRef.current.contains(el)) setFlowAt(null);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // карта у кликнутого .stbig: clamp по краям окна (макет:553–554)
  const openFlow = useCallback(() => {
    const r = stbigRef.current?.getBoundingClientRect();
    setFlowAt(r
      ? { left: Math.max(8, Math.min(window.innerWidth - 672, r.left - 40)),
          top: Math.max(8, r.bottom + 8) }
      : { left: Math.max(8, window.innerWidth / 2 - 330), top: 90 });
  }, []);

  const toggleSect = useCallback(
    (k: string) => setCollapsed((c) => ({ ...c, [k]: !c[k] })), []);
  // пункт меню → раскрыть секцию и доскроллить до блока
  const reveal = useCallback((sect: string, ref: React.RefObject<HTMLDivElement | null>) => {
    setCollapsed((c) => ({ ...c, [sect]: false }));
    setMoreOpen(false);
    window.setTimeout(() => ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }, []);
  const sessionsLabel = (n?: number) => {
    const v = n ?? 0;
    const m10 = v % 10, m100 = v % 100;
    const word = m10 === 1 && m100 !== 11 ? "сессия"
      : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? "сессии" : "сессий";
    return `${v} ${word}`;
  };

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


  // С2: выбранный вариант подсвечивается, кнопки блокируются на время запроса
  const [busyFlag, setBusyFlag] = useState<string | null>(null);
  const [selOpt, setSelOpt] = useState<number | null>(null);
  const applyFlag = useCallback((flag: string) => {
    if (busyFlag) return;
    setBusyFlag(flag);
    api.setFlag(flag)
      .then(onAction)
      .catch((e) => toast.err(`Не выполнено: ${e.message}`))
      .finally(() => setBusyFlag(null));
  }, [onAction, busyFlag]);

  const send = useCallback(() => {
    const text = cInputRef.current?.value.trim();
    if (!text || !t?.id) return;
    api.comment(t.id, text).then(() => {
      if (cInputRef.current) cInputRef.current.value = "";
      onAction();
    }).catch((e) => toast.err(`Не отправлено: ${e.message}`));
  }, [t, onAction]);

  if (!doc || !t) return null;

  const problem = doc.problem;
  const options = doc.options?.options || [];
  const isAttention = p === "BLOCKED" || p === "NEEDS_HUMAN";

  return (
    <>
      <div className="backdrop"
        onClick={() => { if (cardEditorConfirmClose()) onClose(); }} />
      <div className="sheet" style={{ width: `min(${width}px, 97vw)` }}>
        <div className="sheet-resize" onMouseDown={() => setResizeOn(true)} />

        {/* ── шапка: статус крупно, клик — карта переходов ── */}
        <div className="sh-head">
          <div className="crumb">vitrina / FNR_8 / {t.id}</div>
          <div className="r1">
            <span className="bignum">{t.id}</span>
            <span className="stbig" ref={stbigRef}
              onClick={() => (flowAt ? setFlowAt(null) : openFlow())}
              title="Нажмите — карта возможных переходов">
              {PIPE_ICON[p] ? `${PIPE_ICON[p]} ` : ""}{PIPE_RU[p] || p} ▾
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
              {t.paused && (
                <button className="primary"
                  onClick={() => applyFlag(`TASK_${t.id}_RESUME_WORK`)}>▶ Снять паузу</button>
              )}
              <div className="more-wrap" ref={moreWrapRef}>
                <button className="ghost" onClick={() => setMoreOpen((v) => !v)}>Ещё ▾</button>
                {moreOpen && (
                  <div className="more-menu">
                    <div onClick={() => reveal("chronicles", historyRef)}>🕘 История (таймлайн)</div>
                    <div onClick={() => reveal("chronicles", logRef)}>📜 Хроники сессий</div>
                    <div onClick={() => reveal("meta", attachRef)}>📎 Вложения</div>
                    <div onClick={() => { openFlow(); setMoreOpen(false); }}>🗺 Карта переходов</div>
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
            <span>🪙 {fmtTok(t.usage?.tokens_total)} токенов</span>
            <span>{fmtUsd(t.usage?.cost_usd)}</span>
            <span>{sessionsLabel(t.usage?.sessions)}</span>
            <span>ветка: {t.branch || "—"}</span>
            {t.checklist && t.checklist.total > 0 &&
              <span>чек-лист: {t.checklist.done}/{t.checklist.total}</span>}
          </div>
        </div>

        {/* ── карта переходов: поповер у кликнутого статуса ── */}
        {flowAt && (
          <div className="flowpop" ref={flowRef}
            style={{ left: flowAt.left, top: flowAt.top }}
            onClick={(e) => e.stopPropagation()}>
            <div className="ft">Карта статусов — единая схема возможных переходов</div>
            <StatusFlowMap current={p} onMove={(to) => {
              const flagMap: Record<string, string> = {
                BACKLOG: `TASK_${t.id}_ACCEPT`,
                IMPLEMENTING: `TASK_${t.id}_RETRY`,
                DONE: `TASK_${t.id}_FORCE_APPROVE`,
              };
              const flag = flagMap[to];
              if (flag) applyFlag(flag); else api.move(t.id, to).then(onAction);
              setFlowAt(null);
            }} />
            <div className="legend" style={{ padding: "4px 0 10px" }}>
              <span className="l-acc">— допустимый переход</span>
              <span className="l-dim">- - недоступен сейчас</span>
              <span>подсвеченный контур — где задача сейчас</span>
            </div>
          </div>
        )}

        <div className="sh-body">
          {/* ── блок причины: только Блок/Нужен человек; варианты Steward
              внутри (макет:303–346) ── */}
          {isAttention && (
            <div className="alert">
              <div className="a-head">
                <div className="t">⏸ Почему задача остановлена</div>
              </div>
              <div className="a-body">
                <div className="a-cause">
                  {problem?.reason
                    ? <div className="step">{problem.reason}</div>
                    : <div className="step">Причина уточняется — см. итог последней сессии ниже</div>}
                  {problem?.last_result &&
                    <div className="step">Итог последней сессии: {problem.last_result.slice(0, 300)}</div>}
                  {problem?.diagnosis &&
                    <div className="step">Диагностика сессии: {problem.diagnosis}</div>}
                  <div className="step">Незакрытые замечания ревью: {
                    (problem?.findings || []).length || "нет"}</div>
                  <div className="step">Лимиты: перезапусков {problem?.retries ?? 0},
                    итераций ревью {problem?.review_iterations ?? 0}/3</div>
                </div>
                {options.length > 0 && (
                  <>
                    <hr className="a-sep" />
                    <div className="a-opt-t">Steward предлагает варианты — выберите один
                      или напишите свой</div>
                    {options.map((o, i) => (
                      <div key={i}
                        className={`a-opt ${o.recommended ? "rec" : ""} ${selOpt === i ? "sel" : ""} ${o.flag && busyFlag === o.flag ? "busy" : ""}`}
                        onClick={() => {
                          setSelOpt(i);
                          if (o.flag) {
                            applyFlag(o.flag);
                            api.stewardMessage(`Человек выбрал вариант: «${o.title}»`)
                              .catch(() => {});
                          }
                        }}>
                        <span className="num">{i + 1}</span>
                        <span style={{ flex: 1 }}>
                          <span className="ot">{o.title}</span>
                          {o.recommended && <span className="orec">рекомендую</span>}
                          {o.explanation && <div className="oe">{o.explanation}</div>}
                        </span>
                      </div>
                    ))}
                  </>
                )}
                <div className="a-hint">Не подошло — напишите свободный текст
                  в «Обсуждении» (внизу страницы), Steward выполнит его как поручение. ·{" "}
                  <span className="flow-link" onClick={openFlow}>Единая карта статусов ↗</span>
                </div>
              </div>
            </div>
          )}

          {/* ── Описание: карточка = единый источник (markdown) ── */}
          <Sect collapsed={!!collapsed.post}
            onToggle={() => { if (!editing) toggleSect("post"); }}
            title="Описание" cnt={<span className="cnt">карточка, markdown</span>}
            headExtra={!editing && (
              <button className="ghost" style={{ padding: "0 4px", fontSize: 11 }}
                onClick={(e) => { e.stopPropagation(); setEditing(true); }}>
                ✎ Редактировать
              </button>
            )}>
            {editing ? (
              <CardEditor key={t.id} cardMd={doc.card_md}
                liveRunning={!!t.live?.running}
                onSave={(mdText, { force }) => {
                  api.saveCard(t.id, mdText, force).then((r) => {
                    if (r.ok) { setEditing(false); onAction(); }
                    else toast.err(r.error || "не удалось сохранить карточку");
                  });
                }}
                onCancel={() => setEditing(false)} />
            ) : (
              <div className="post" dangerouslySetInnerHTML={{ __html: md(doc.card_md) }} />
            )}
          </Sect>

          {/* ── Чек-лист: модель БД, редактор ── */}
          <Sect collapsed={!!collapsed.checklist} onToggle={() => toggleSect("checklist")}
            title="Чек-лист"
            cnt={t.checklist && t.checklist.total > 0 &&
              <span className="cnt">{t.checklist.done}/{t.checklist.total}</span>}>
            <ChecklistEditor tid={t.id} checklist={doc.checklist || []}
              onChange={onAction} />
            <div className="sess">
              <div className="l">итог последней сессии</div>
              {problem?.last_result || "сессий ещё не было"}
            </div>
          </Sect>

          {/* ── Ревью ──
              отклонение от макета: severity замечаний в данных нет
              (Finding без поля severity), поэтому cnt = «N открыто»,
              а не «x существенно · y nit» */}
          <Sect collapsed={!!collapsed.review} onToggle={() => toggleSect("review")}
            title="Ревью"
            cnt={(t.findings || []).length > 0 && <span className="cnt">
              {(t.findings || []).filter((f) => f.resolution !== "resolved").length} открыто</span>}>
            <p><b>Вердикт:</b> {t.review_verdict || "ещё не проводилось"}</p>
            <ul>
              {(t.findings || []).map((f) => (
                <li key={f.id}>{f.text} {f.file && <span className="mono">({f.file})</span>}
                  — <i>{f.resolution}</i></li>
              ))}
            </ul>
            {renderComments(reviewComments)}
          </Sect>

          {/* ── Хроники ── */}
          <Sect collapsed={!!collapsed.chronicles} onToggle={() => toggleSect("chronicles")}
            title="Хроники">
            <div ref={logRef}>
              <div className="meta" style={{ marginBottom: 6 }}>Лог реализации</div>
              <SessionLog taskId={t.id} />
            </div>
            <div ref={historyRef} style={{ marginTop: 12 }}>
              <div className="meta" style={{ marginBottom: 6 }}>История (таймлайн)</div>
              <History taskId={t.id} />
            </div>
          </Sect>

          {/* ── Мета ── */}
          <Sect collapsed={!!collapsed.meta} onToggle={() => toggleSect("meta")}
            title="Мета">
            <p style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--dim)" }}>
              система: {t.system} · ветка: {t.branch || "—"} ·
              worktree: {t.worktree || "—"} · origin: {t.origin} ·
              steward-сессия: {t.session_id || "—"}</p>
            <div ref={attachRef}>
              <Attachments taskId={t.id} />
            </div>
          </Sect>

          {/* ── Обсуждение: последний, всегда раскрыт (в скролле sh-body) ── */}
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
