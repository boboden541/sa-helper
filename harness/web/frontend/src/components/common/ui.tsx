import type { Usage } from "../../types";
import { PIPE_COLOR, PIPE_RU } from "../../api";

export function esc(s: unknown): string {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function inline(s: string): string {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    // ссылки — только http(s), без кавычек в URL (экранирование атрибута)
    .replace(/\[([^\]]+)\]\((https?:[^)\s"<>]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer" style="color:var(--acc)">$1</a>')
    // AC-идентификаторы — моно-синие (макет .ac)
    .replace(/\bAC-\d+(?:\.\d+)*\b/g, '<span class="ac">$&</span>');
}

/** Мини-markdown: заголовки, списки, таблицы, код, чекбоксы. */
export function md(src: string | null | undefined): string {
  const lines = (src || "").split("\n");
  let html = "";
  let i = 0;
  let inCode = false;
  let codeBuf: string[] = [];
  let listBuf: string[] = [];
  const flushList = () => {
    if (listBuf.length) {
      html += "<ul>" + listBuf.map((x) => `<li>${inline(x)}</li>`).join("") + "</ul>";
      listBuf = [];
    }
  };
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      flushList();
      if (!inCode) { inCode = true; codeBuf = []; }
      else { html += `<pre>${esc(codeBuf.join("\n"))}</pre>`; inCode = false; }
      i++; continue;
    }
    if (inCode) { codeBuf.push(line); i++; continue; }
    if (/^\|/.test(line.trim())) {
      flushList();
      const rows: string[] = [];
      while (i < lines.length && /^\|/.test(lines[i].trim())) { rows.push(lines[i].trim()); i++; }
      if (rows.length >= 2) {
        const cells = (r: string) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        html += "<table><tr>" + cells(rows[0]).map((c) => `<th>${c}</th>`).join("") + "</tr>";
        for (const r of rows.slice(2)) html += "<tr>" + cells(r).map((c) => `<td>${c}</td>`).join("") + "</tr>";
        html += "</table>";
      }
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flushList(); html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; i++; continue; }
    if (/^---+$/.test(line.trim())) { flushList(); html += "<hr>"; i++; continue; }
    const chk = line.match(/^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$/);
    if (chk) {
      // канон статусов чек-листа: пробел/~/x/r/b/f (server.STATE_NAMES)
      const CHK: Record<string, { cls: string; glyph: string }> = {
        " ": { cls: "todo", glyph: "☐" },
        "~": { cls: "inprog", glyph: "⟳" },
        "x": { cls: "done", glyph: "✓" },
        "r": { cls: "review", glyph: "🔍" },
        "b": { cls: "block", glyph: "⛔" },
        "f": { cls: "failed", glyph: "✗" },
      };
      const st = CHK[chk[1]] || CHK[" "];
      html += `<div class="clk-item ${st.cls}"><span class="box">${st.glyph}</span><span>${inline(chk[2])}</span></div>`;
      i++; continue;
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { listBuf.push(li[1]); i++; continue; }
    if (line.trim().startsWith("Источник:")) {
      // источник постановки — приглушённый блок с пунктиром (макет .src)
      flushList();
      html += `<p class="src">${inline(line.trim())}</p>`;
      i++; continue;
    }
    if (line.trim() === "") { flushList(); i++; continue; }
    flushList();
    html += `<p>${inline(line)}</p>`;
    i++;
  }
  flushList();
  return html;
}

export function parseComments(mdText: string | null | undefined) {
  const out: Array<{ ts: string; author: string; text: string }> = [];
  for (const line of (mdText || "").split("\n")) {
    const m = line.match(/^\s*-\s+\[([^\]]+?)\s*\|\s*([^\]]+?)\s*\]\s*(.*)$/);
    if (m) out.push({ ts: m[1], author: m[2], text: m[3] });
    else if (out.length && line.trim()) out[out.length - 1].text += "\n" + line;
  }
  return out;
}

export function Chip({ pipeline }: { pipeline: string }) {
  const color = PIPE_COLOR[pipeline] || "";
  return <span className={`chip ${color}`}>{PIPE_RU[pipeline] || pipeline || "—"}</span>;
}

export function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <>
      <span className="pbar"><i style={{ width: `${pct}%` }} /></span>
      {done}/{total}
    </>
  );
}

export function LiveDot({ running }: { running: boolean }) {
  return <span className="live-dot" style={running ? undefined : { background: "var(--dim)", animation: "none" }} />;
}

export function fmtTokens(n?: number): string {
  if (!n) return "0";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function fmtUsd(n?: number): string {
  if (n == null) return "—";
  return n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`;
}

export function UsageBadge({ usage }: { usage?: Usage }) {
  if (!usage || !usage.tokens_total) return null;
  return (
    <span className="usage" title={`вход: ${usage.tokens_in ?? 0} · выход: ${usage.tokens_out ?? 0}`}>
      🪙 {fmtTokens(usage.tokens_total)} · {fmtUsd(usage.cost_usd)}
    </span>
  );
}

export function sumUsage(items: Array<{ usage?: Usage }>): Usage {
  const acc: Usage = { tokens_in: 0, tokens_out: 0, tokens_total: 0, cost_usd: 0 };
  for (const it of items) {
    acc.tokens_in! += it.usage?.tokens_in ?? 0;
    acc.tokens_out! += it.usage?.tokens_out ?? 0;
    acc.tokens_total! += it.usage?.tokens_total ?? 0;
    acc.cost_usd! += it.usage?.cost_usd ?? 0;
  }
  return acc;
}
