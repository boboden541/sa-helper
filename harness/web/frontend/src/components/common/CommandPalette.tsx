import { useEffect, useMemo, useRef, useState } from "react";
import type { BoardState, Story } from "../../types";
import { PIPE_RU } from "../../api";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

/** Командная палитра (⌘K): переходы по задачам/Stories и команды. */
export function CommandPalette({ open, onClose, state, stories, actions }: {
  open: boolean;
  onClose: () => void;
  state: BoardState | null;
  stories: Story[];
  actions: Command[];
}) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) { setQuery(""); setSel(0); setTimeout(() => inputRef.current?.focus(), 0); }
  }, [open]);

  const items = useMemo(() => {
    const list: Command[] = [];
    for (const s of stories) {
      list.push({ id: `story:${s.fnr}`, label: `${s.fnr} — ${s.title}`, hint: "Story",
        run: () => actions.find((a) => a.id === "open:stories")?.run === undefined
          ? undefined : undefined });
    }
    if (state) {
      for (const t of state.manifest.tasks || []) {
        list.push({ id: `task:${t.id}`, label: `${t.id} — ${t.title ?? ""}`,
          hint: PIPE_RU[state.manifest.tasks.find((x) => x.id === t.id)
            ? (state.manifest.tasks.find((x) => x.id === t.id)!.pipeline ?? "") : ""] || undefined,
          run: () => actions.find((a) => a.id === `task:${t.id}`)?.run() });
      }
    }
    list.push(...actions);
    const ql = query.trim().toLowerCase();
    const filtered = ql
      ? list.filter((c) => c.label.toLowerCase().includes(ql) || (c.hint ?? "").toLowerCase().includes(ql))
      : list;
    return filtered.slice(0, 12);
  }, [query, state, stories, actions]);

  if (!open) return null;
  return (
    <div className="modal-bg" style={{ alignItems: "flex-start" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ marginTop: "12vh" }}>
        <input type="text" ref={inputRef} value={query} autoFocus
          placeholder="Поиск задач, Stories, команд…"
          onChange={(e) => { setQuery(e.target.value); setSel(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            if (e.key === "Enter" && items[sel]) { items[sel].run(); onClose(); }
            if (e.key === "Escape") onClose();
          }} />
        <div style={{ marginTop: 8 }}>
          {items.map((c, i) => (
            <div key={c.id} className={`pick-item ${i === sel ? "sel" : ""}`}
              style={i === sel ? { background: "var(--chip)" } : undefined}
              onMouseEnter={() => setSel(i)}
              onClick={() => { c.run(); onClose(); }}>
              {c.label}{c.hint && <span className="meta" style={{ marginLeft: 8 }}>{c.hint}</span>}
            </div>
          ))}
          {items.length === 0 && <div className="pick-item empty">ничего не найдено</div>}
        </div>
        <div className="hint">↑↓ — выбор · Enter — выполнить · Esc — закрыть</div>
      </div>
    </div>
  );
}

export interface Toast { id: number; text: string; onClick?: () => void; }

export function Toasts({ toasts, onDismiss }: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div className="toast" key={t.id} onClick={() => onDismiss(t.id)}>{t.text}</div>
      ))}
    </div>
  );
}
