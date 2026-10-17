import { useEffect, useRef, useState } from "react";

interface Msg { ts: string; author: string; text: string; }

/** Чат со Steward — диспетчером конвейера (порция H1). */
export function StewardChat() {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(() => {
    try { return JSON.parse(localStorage.getItem("stewardPos") || "null"); }
    catch { return null; }
  });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  const onHeaderDown = (e: React.MouseEvent) => {
    const el = e.currentTarget.closest(".steward-panel") as HTMLElement;
    const r = el.getBoundingClientRect();
    dragRef.current = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    const move = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const x = Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - dragRef.current.dx));
      const y = Math.max(0, Math.min(window.innerHeight - 80, ev.clientY - dragRef.current.dy));
      setPos({ x, y });
      localStorage.setItem("stewardPos", JSON.stringify({ x, y }));
    };
    const up = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  const [messages, setMessages] = useState<Msg[]>([]);
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const load = () =>
      fetch("/api/steward/chat")
        .then((r) => r.json())
        .then((d) => { setMessages(d.messages || []); setPending(!!d.pending); })
        .catch(() => {});
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [open]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, pending]);

  const send = () => {
    const text = draft.trim();
    if (!text || pending) return;
    setDraft("");
    fetch("/api/steward/message", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then(() => {
      setMessages((m) => [...m, { ts: new Date().toLocaleString("ru-RU", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }),
        author: "human", text }]);
      setPending(true);
    }).catch(() => {});
  };

  return (
    <>
      {!open && (
        <button className="primary" style={{ position: "fixed", bottom: 20, right: 20,
          borderRadius: "999px", padding: "11px 18px", zIndex: 40, boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}
          onClick={() => setOpen(true)}>💬 Steward</button>
      )}
      {open && (
        <div className="steward-panel"
          style={pos ? { position: "fixed", left: pos.x, top: pos.y,
            width: "min(430px, 94vw)", height: "min(560px, 76vh)" } : undefined}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
            padding: "10px 14px", borderBottom: "1px solid var(--line)", cursor: "move" }}
            onMouseDown={onHeaderDown}>
            <b style={{ fontSize: 13 }}>💬 Steward — диспетчер</b>
            <span className="meta">управляет конвейером словами · тяните за шапку</span>
            <span className="spacer" />
            <button className="ghost" onClick={() => setOpen(false)}>✕</button>
          </div>
          <div ref={bodyRef} style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
            {messages.length === 0 && (
              <p className="empty">
                Попросите словами: «что сейчас блокирует проект?», «создай задачу: …»,
                «верни T8 в работу», «почему стоит T4?» — Steward посмотрит данные,
                выполнит действие и отчитается.
              </p>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`comment ${m.author === "human" ? "human" : "daemon"}`}
                style={{ margin: "6px 0" }}>
                <div className="cmeta">{m.ts} · {m.author}</div>
                <div dangerouslySetInnerHTML={{ __html:
                  m.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/\n/g, "<br>") }} />
              </div>
            ))}
            {pending && <div className="meta" style={{ padding: "4px 0" }}>Steward думает…</div>}
          </div>
          <div style={{ borderTop: "1px solid var(--line)", padding: 10, display: "flex", gap: 8 }}>
            <input style={{ flex: 1, background: "var(--chip)", color: "var(--text)",
              border: "1px solid var(--line2)", borderRadius: 8, padding: "8px 12px", font: "inherit" }}
              value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }}
              placeholder="Поручение или вопрос…" />
            <button className="primary" disabled={pending} onClick={send}>→</button>
          </div>
        </div>
      )}
    </>
  );
}
