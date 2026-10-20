import { useEffect, useRef, useState } from "react";
import type { ChecklistItemModel, ChecklistSectionModel } from "../../types";
import { api } from "../../api";

const STATES: Array<{ key: ChecklistItemModel["state"]; label: string }> = [
  { key: "todo", label: "Todo" },
  { key: "inprog", label: "In Progress" },
  { key: "done", label: "Done" },
  { key: "review", label: "Review" },
  { key: "blocked", label: "Blocked" },
  { key: "failed", label: "Failed" },
  { key: "skipped", label: "Skipped" },
];
const CHIP_LABEL: Record<string, string> = Object.fromEntries(
  STATES.map((s) => [s.key, s.label]));

/** Структурный редактор чек-листа (модель БД). Подзаголовки depth 1–4,
 *  инлайн-добавление сверху, переключение Визуально|Текст. */
export function ChecklistEditor({ tid, checklist, onChange }: {
  tid: string;
  checklist: ChecklistSectionModel[];
  onChange: () => void;
}) {
  const [mode, setMode] = useState<"visual" | "text">("visual");
  const [textDraft, setTextDraft] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [menuId, setMenuId] = useState<number | null>(null);

  const addInputRef = useRef<HTMLInputElement>(null);

  const total = checklist.reduce((a, s) => a + s.items.length, 0);
  const done = checklist.reduce(
    (a, s) => a + s.items.filter((i) => i.state === "done").length, 0);
  const pct = total ? Math.round((100 * done) / total) : 0;

  const importText = () => {
    api.checklistImport(tid, textDraft ?? "").then(() => {
      setTextDraft(null); setMode("visual"); onChange();
    }).catch((e) => {
      window.alert(`Не удалось применить: ${e.message || e}`);
    });
  };

  // Единственное поле ввода: последовательно добавляет строки в чек-лист.
  // # текст → секция · ## текст → подзаголовок · обычный текст → пункт
  // в последнюю секцию. После каждого Enter — фокус возвращается в поле.
  const addSmart = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const after = () => { onChange(); addInputRef.current?.focus(); };

    // ## – ##### = подзаголовок (depth 1–4) в последнюю секцию
    const depthMatch = trimmed.match(/^(#{2,5})\s+(.*)$/);
    if (depthMatch) {
      const depth = depthMatch[1].length - 1;
      const text = depthMatch[2];
      const target = checklist.length > 0 ? checklist[checklist.length - 1] : null;
      if (target) {
        api.checklistItemAdd(tid, target.id, text, "todo", false, depth)
          .then(after).catch(() => {});
      } else {
        api.checklistSectionAdd(tid, "Чек-лист").then((r: any) => {
          api.checklistItemAdd(tid, r.section_id, text, "todo", false, depth)
            .then(after).catch(() => {});
        }).catch(() => {});
      }
      return;
    }

    // # текст = новая секция (в конец)
    const secMatch = trimmed.match(/^#\s+(.*)/);
    if (secMatch) {
      api.checklistSectionAdd(tid, secMatch[1]).then(after).catch(() => {});
      return;
    }

    // обычный текст → пункт в последнюю секцию
    const target = checklist.length > 0 ? checklist[checklist.length - 1] : null;
    if (target) {
      api.checklistItemAdd(tid, target.id, trimmed)
        .then(after).catch(() => {});
    } else {
      api.checklistSectionAdd(tid, "Чек-лист").then((r: any) => {
        api.checklistItemAdd(tid, r.section_id, trimmed)
          .then(after).catch(() => {});
      }).catch(() => {});
    }
  };

  return (
    <div>
      <div className="cl-progress">
        <div className="cl-bar"><i style={{ width: `${pct}%` }} /></div>
        <span className="cl-count">{done}/{total}</span>
      </div>

      <div className="cl-modes">
        <button className={`cl-mode ${mode === "visual" ? "on" : ""}`}
          onClick={() => { setTextDraft(null); setMode("visual"); }}>Визуально</button>
        <button className={`cl-mode ${mode === "text" ? "on" : ""}`}
          onClick={() => {
            setTextDraft(serializeFromModel(checklist));
            setMode("text");
          }}>Текст</button>
      </div>

      {mode === "text" ? (
        <div className="cl-textwrap">
          <textarea className="cl-textarea" value={textDraft ?? ""}
            onChange={(e) => setTextDraft(e.target.value)}
            rows={Math.max(10, (textDraft ?? "").split("\n").length + 1)}
            placeholder={"# Секция\n## Подзаголовок\n+ сделано !\n~ в работе\n- сделать\n[x] пропущено"} />
          <div className="cl-texthint">
            <b>#</b> секция · <b>##</b>–<b>#####</b> подзаголовки ·
            <b> +</b> done · <b>~</b> в работе · <b>-</b> todo ·
            <b> [r]/[b]/[f]</b> · <b>[x]</b> skipped · суффикс <b>!</b> = обязательный
          </div>
          <button className="primary" style={{ marginTop: 6 }}
            onClick={importText}>Применить</button>
        </div>
      ) : (
        <>
          {/* поле добавления — СВЕРХУ, всегда доступно без скролла */}
          <div className="cl-additem">
            <input ref={addInputRef} placeholder="Текст, # секция, ## подзаголовок…"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  addSmart((e.target as HTMLInputElement).value);
                  (e.target as HTMLInputElement).value = "";
                }
              }} />
          </div>

          {checklist.length === 0 && (
            <p className="empty">Введите «# Название» выше и нажмите Enter — создастся секция</p>
          )}

          {checklist.map((sec) => (
            <div className="cl-sec" key={sec.id}>
              {sec.title !== "" && (
              <div className="cl-sec-h">
                <span className="cl-sec-t">{sec.title}</span>
                <span className={`cl-kind cl-kind-${sec.kind}`}>
                  {sec.kind === "plan" ? "агент" : sec.kind === "review" ? "ревьюер" : "своя"}
                </span>
                <span className="cl-dots" title="Удалить секцию"
                  onClick={() => { if (window.confirm(`Удалить секцию «${sec.title}»?`)) {
                    api.checklistSectionDelete(sec.id).then(onChange).catch(() => {});
                  } }}>···</span>
              </div>
              )}
              {sec.items.map((it) => (
                <ItemRow key={it.id} it={it} onChange={onChange}
                  editingId={editingId} setEditingId={setEditingId}
                  editDraft={editDraft} setEditDraft={setEditDraft}
                  menuId={menuId} setMenuId={setMenuId} />
              ))}
            </div>
          ))}


        </>
      )}
    </div>
  );
}

function ItemRow({ it, onChange, editingId, setEditingId,
                   editDraft, setEditDraft, menuId, setMenuId }: {
  it: ChecklistItemModel;
  onChange: () => void;
  editingId: number | null;
  setEditingId: (v: number | null) => void;
  editDraft: string;
  setEditDraft: (v: string) => void;
  menuId: number | null;
  setMenuId: (v: number | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (menuId !== it.id) return;
    const away = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuId(null);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [menuId, it.id, setMenuId]);

  const doneState = it.state === "done" || it.state === "skipped";
  const isHeader = (it as any).depth > 0;

  const toggle = () => {
    api.checklistItemPatch(it.id, { state: doneState ? "todo" : "done" })
      .then(onChange).catch(() => {});
  };
  const saveEdit = () => {
    if (editDraft.trim() && editDraft !== it.text) {
      api.checklistItemPatch(it.id, { text: editDraft }).then(onChange).catch(() => {});
    }
    setEditingId(null);
  };

  if (isHeader) {
    return (
      <div className={`cl-item cl-header cl-header-${(it as any).depth}`}
        ref={ref}
        style={{ paddingLeft: `${((it as any).depth - 1) * 16}px` }}>
        <span className="cl-header-text">{it.text}</span>
        <span className="cl-dots" onClick={() => setMenuId(menuId === it.id ? null : it.id)}>⋮</span>
        {menuId === it.id && (
          <div className="cl-menu">
            <div className="cl-danger" onClick={() => {
              api.checklistItemDelete(it.id).then(onChange).catch(() => {});
              setMenuId(null);
            }}>Удалить заголовок</div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`cl-item ${doneState ? "cl-done" : ""}`} ref={ref}>
      <span className={`cl-box ${it.state}`} onClick={toggle}
        title={doneState ? "Вернуть в todo" : "Отметить выполненным"}>
        {doneState ? "✓" : it.state === "inprog" ? "⟳" : ""}
      </span>
      {editingId === it.id ? (
        <input className="cl-edit" autoFocus value={editDraft}
          onChange={(e) => setEditDraft(e.target.value)}
          onBlur={saveEdit}
          onKeyDown={(e) => { if (e.key === "Enter") saveEdit();
                              if (e.key === "Escape") setEditingId(null); }} />
      ) : (
        <span className="cl-text" onDoubleClick={() => { setEditingId(it.id); setEditDraft(it.text); }}
          title="Двойной клик — редактировать">
          {it.text}
        </span>
      )}
      {it.mandatory === 1 && <span className="cl-mand" title="Обязательный пункт">!</span>}
      <span className={`st ${it.state === "skipped" ? "skipped" : it.state}`}>
        {CHIP_LABEL[it.state] || it.state}
      </span>
      <span className="cl-dots" onClick={() => setMenuId(menuId === it.id ? null : it.id)}>⋮</span>
      {menuId === it.id && (
        <div className="cl-menu">
          {STATES.filter((s) => s.key !== it.state).map((s) => (
            <div key={s.key} onClick={() => {
              api.checklistItemPatch(it.id, { state: s.key })
                .then(onChange).catch(() => {});
              setMenuId(null);
            }}>{s.label}</div>
          ))}
          <div onClick={() => {
            api.checklistItemPatch(it.id, { mandatory: it.mandatory !== 1 })
              .then(onChange).catch(() => {});
            setMenuId(null);
          }}>{it.mandatory ? "Снять «обязательный»" : "Сделать обязательным"}</div>
          <div className="cl-danger" onClick={() => {
            if (window.confirm("Удалить пункт?")) {
              api.checklistItemDelete(it.id).then(onChange).catch(() => {});
            }
            setMenuId(null);
          }}>Удалить пункт</div>
        </div>
      )}
    </div>
  );
}

/** Кнопка «+ секция» */
export function AddSection({ onAdd }: { onAdd: (title: string) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const submit = () => {
    if (!title.trim()) return;
    onAdd(title.trim());
    setTitle(""); setOpen(false);
  };
  return (
    <div className="cl-addsec">
      {open ? (
        <>
          <input className="cl-secinput" autoFocus value={title}
            placeholder="Заголовок секции"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit();
                                if (e.key === "Escape") setOpen(false); }} />
          <button className="ced-btn" onClick={submit}>OK</button>
        </>
      ) : (
        <button className="ced-btn" onClick={() => setOpen(true)}>＋ секция</button>
      )}
    </div>
  );
}

/** Сериализация модели → Checkvist-текст */
function serializeFromModel(checklist: ChecklistSectionModel[]): string {
  const out: string[] = [];
  for (const sec of checklist) {
    out.push(`# ${sec.title}`);
    for (const it of sec.items) {
      if ((it as any).depth > 0) {
        out.push(`${"#".repeat((it as any).depth + 1)} ${it.text}`);
        continue;
      }
      const mark = { done: "+", inprog: "~", todo: "-", review: "[r]",
                     blocked: "[b]", failed: "[f]", skipped: "[x]" }[it.state] || "-";
      out.push(`${mark} ${it.text}${it.mandatory ? " !" : ""}`);
    }
    out.push("");
  }
  return out.join("\n");
}
