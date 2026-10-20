import { useEffect, useState } from "react";

// Императивные тосты (С2): toast.err/info/ok из любого места — состояние
// живёт в модуле, <Toasts/> монтируется один раз в App.
export type Sev = "info" | "ok" | "warn" | "err";

export interface ToastItem {
  id: number;
  text: string;
  sev: Sev;
  onClick?: () => void;
}

let seq = 1;
let bind: ((t: ToastItem) => void) | null = null;

function push(text: string, sev: Sev, onClick?: () => void): number {
  const item: ToastItem = { id: seq++, text, sev, onClick };
  bind?.(item);
  return item.id;
}

export const toast = {
  push,
  info: (text: string, onClick?: () => void) => push(text, "info", onClick),
  ok: (text: string) => push(text, "ok"),
  warn: (text: string, onClick?: () => void) => push(text, "warn", onClick),
  err: (text: string) => push(text, "err"),
};

export function Toasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    bind = (t) => setItems((l) => [...l, t]);
    return () => { bind = null; };
  }, []);
  const dismiss = (id: number) => setItems((l) => l.filter((x) => x.id !== id));
  return (
    <div className="toasts">
      {items.map((t) => (
        <ToastRow key={t.id} t={t} onDone={() => dismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastRow({ t, onDone }: { t: ToastItem; onDone: () => void }) {
  useEffect(() => {
    const tm = setTimeout(onDone, t.sev === "err" ? 9000 : 6000);
    return () => clearTimeout(tm);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className={`toast ${t.sev}`}
      onClick={() => { t.onClick?.(); onDone(); }}>
      {t.text}
    </div>
  );
}
