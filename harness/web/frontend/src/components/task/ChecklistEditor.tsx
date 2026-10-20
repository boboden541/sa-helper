import { useState } from "react";
import type { ChecklistSectionModel, ChecklistItemModel } from "../../types";
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

/** Структурный редактор чек-листа (модель БД). Инлайн: добавление пункта,
 *  toggle чекбоксом, правка текста по клику, ⋮ — статус/обязательность/удаление. */
export function ChecklistEditor({ tid, checklist, onChange }: {
  tid: string;
  checklist: ChecklistSectionModel[];
  onChange: () => void;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [menuId, setMenuId] = useState<number | null>(null);

  const total = checklist.reduce((a, s) => a + s.items.length, 0);
  const done = checklist.reduce(
    (a, s) => a + s.items.filter((i) => i.state === "done").length, 0);
  const pct = total ? Math.round((100 * done) / total) : 0;

  return (
    <div>
      <div className="cl-progress">
        <div className="cl-bar"><i style={{ width: `${pct}%` }} /></div>
        <span className="cl-count">{done}/{total}</span>
      </div>
      {checklist.length === 0 && (
        <p className="empty">чек-лист пуст — добавьте секцию и пункты</p>
      )}
      {checklist.map((sec) => (
        <div className="cl-sec" key={sec.id}>
          <div className="cl-sec-h">
            <span className="cl-sec-t">{sec.title}</span>
            <span className={`cl-kind cl-kind-${sec.kind}`}>
              {sec.kind === "plan" ? "агент" : sec.kind === "review" ? "ревьюер" : "своя"}
            </span>
            <button className="ced-btn" title="Удалить секцию"
              onClick={() => { if (window.confirm(`Удалить секцию «${sec.title}»?`)) {
                api.checklistSectionDelete(sec.id).then(onChange).catch(() => {});
              } }}>✕</button>
          </div>
          {sec.items.map((it) => (
            <ItemRow key={it.id} it={it} onChange={onChange}
              editingId={editingId} setEditingId={setEditingId}
              editDraft={editDraft} setEditDraft={setEditDraft}
              menuId={menuId} setMenuId={setMenuId} />
          ))}
          <AddItem onAdd={(text, mandatory) => {
            api.checklistItemAdd(tid, sec.id, text, "todo", mandatory)
              .then(onChange).catch(() => {});
          }} placeholder="Добавить пункт…" />
        </div>
      ))}
      <AddSection onAdd={(title) => {
        api.checklistSectionAdd(tid, title).then(onChange).catch(() => {});
      }} />
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
  const doneState = it.state === "done" || it.state === "skipped";
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
  return (
    <div className={`cl-item ${doneState ? "cl-done" : ""}`}>
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
        <div className="cl-menu" onMouseLeave={() => setMenuId(null)}>
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

function AddItem({ onAdd, placeholder }: {
  onAdd: (text: string, mandatory: boolean) => void;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const [mand, setMand] = useState(false);
  const submit = () => {
    if (!text.trim()) return;
    onAdd(text.trim(), mand);
    setText(""); setMand(false);
  };
  return (
    <div className="cl-additem">
      <input value={text} placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <button className="ced-btn" title="Обязательный пункт"
        onClick={() => setMand(!mand)}
        style={mand ? { color: "var(--acc)" } : undefined}>!</button>
      <button className="ced-btn" title="Добавить" onClick={submit}>＋</button>
    </div>
  );
}

/** Кнопка «+ секция» (внизу редактора чек-листа). */
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
