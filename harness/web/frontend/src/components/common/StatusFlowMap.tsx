
/** Единая карта статусов конвейера (как jira-workflow).
 *  Текущий статус подсвечен; допустимые переходы из него — жирные синие стрелки;
 *  клик по целевой ноде выполняет переход (если передан onMove). */
const NODES: Array<{ key: string; x: number; y: number; w: number }> = [
  { key: "PROPOSED", x: 14, y: 34, w: 96 },
  { key: "BACKLOG", x: 142, y: 34, w: 82 },
  { key: "READY", x: 256, y: 34, w: 84 },
  { key: "IMPLEMENTING", x: 372, y: 34, w: 100 },
  { key: "REVIEW", x: 504, y: 34, w: 76 },
  { key: "DONE", x: 480, y: 128, w: 84 },
  { key: "VERIFIED", x: 596, y: 128, w: 92 },
  { key: "BLOCKED", x: 350, y: 150, w: 180 },
];

const LABEL_RU: Record<string, string> = {
  PROPOSED: "Предложены", BACKLOG: "Бэклог", READY: "Готова к запуску",
  IMPLEMENTING: "В работе", REVIEW: "Ревью", DONE: "Готовы",
  VERIFIED: "Проверены", BLOCKED: "Блок / Нужен человек",
  NEEDS_HUMAN: "Нужен человек", ABORTED: "Снята",
};

/** Рёбра машины состояний: [from, to, подпись]. */
const EDGES: Array<[string, string, string?]> = [
  ["PROPOSED", "BACKLOG", "декомпозиция/accept"],
  ["BACKLOG", "READY", "зависимости"],
  ["READY", "IMPLEMENTING", "запуск"],
  ["IMPLEMENTING", "REVIEW", "на ревью"],
  ["REVIEW", "DONE", "approved"],
  ["DONE", "VERIFIED", "verify"],
  ["IMPLEMENTING", "BLOCKED", "сбой"],
  ["BLOCKED", "IMPLEMENTING", "retry"],
  ["REVIEW", "NEEDS_HUMAN", "stalled"],
  ["NEEDS_HUMAN", "IMPLEMENTING", "resume"],
  ["DONE", "IMPLEMENTING", "request changes"],
];

// координаты центров (по NODES + ручные для особых)
const POS: Record<string, { cx: number; cy: number }> = {
  PROPOSED: { cx: 62, cy: 49 }, BACKLOG: { cx: 183, cy: 49 },
  READY: { cx: 298, cy: 49 }, IMPLEMENTING: { cx: 422, cy: 49 },
  REVIEW: { cx: 542, cy: 49 }, DONE: { cx: 522, cy: 145 },
  VERIFIED: { cx: 642, cy: 145 }, BLOCKED: { cx: 440, cy: 170 },
  NEEDS_HUMAN: { cx: 440, cy: 170 }, ABORTED: { cx: 440, cy: 215 },
};

export function StatusFlowMap({ current, onMove }: {
  current: string;
  onMove?: (to: string) => void;
}) {
  const allowed = new Set(
    EDGES.filter(([f]) => f === current).map(([, t]) => t));
  const alias: Record<string, string> = { NEEDS_HUMAN: "BLOCKED" };
  const posOf = (k: string) => POS[alias[k] ?? k] ?? POS[k] ?? { cx: 20, cy: 20 };

  return (
    <svg width="100%" viewBox="0 0 700 230"
      style={{ maxWidth: 660, display: "block" }}
      fontFamily="ui-monospace, Menlo, monospace" fontSize="11">
      {EDGES.map(([f, t, label], i) => {
        const a = posOf(f), b = posOf(t);
        const fromCurrent = f === current;
        // макет: доступные переходы — сплошные acc, недоступные — пунктир faint
        const stroke = fromCurrent ? "var(--acc)" : "var(--faint)";
        const dash = fromCurrent ? undefined : "4 3";
        const width = fromCurrent ? 1.8 : 1;
        // кривая, чтобы стрелки туда-обратно не слипались
        const dx = b.cx - a.cx, dy = b.cy - a.cy;
        const mx = a.cx + dx / 2 + (i % 2 ? 14 : -6);
        const my = a.cy + dy / 2 - 16;
        return (
          <g key={i}>
            <path d={`M ${a.cx} ${a.cy} Q ${mx} ${my} ${b.cx} ${b.cy}`}
              fill="none" stroke={stroke} strokeWidth={width}
              strokeDasharray={dash} markerEnd={fromCurrent ? "url(#sfn-acc)" : "url(#sfn-dim)"} />
            {label && fromCurrent && (
              <text x={mx} y={my - 4} textAnchor="middle" fill="var(--acc)" fontSize="9.5">
                {label}
              </text>
            )}
          </g>
        );
      })}
      {NODES.map((n) => {
        const isCurrent = n.key === current ||
          (current === "NEEDS_HUMAN" && n.key === "BLOCKED");
        const isTarget = allowed.has(n.key) && n.key !== current;
        const isBlock = n.key === "BLOCKED"; // семантика Блока — всегда warn (макет:508)
        const h = isBlock ? 40 : 30;
        return (
          <g key={n.key} onClick={() => isTarget && onMove?.(n.key)}
            style={isTarget ? { cursor: "pointer" } : undefined}>
            <rect x={n.x} y={n.y} width={n.w} height={h} rx={8}
              fill={isBlock ? "rgba(210,153,34,.08)"
                : isCurrent ? "rgba(88,166,255,.08)" : "var(--surface)"}
              stroke={isBlock ? "var(--warn)"
                : isCurrent ? "var(--acc)" : isTarget ? "var(--acc)" : "var(--line2)"}
              strokeWidth={isBlock ? (isCurrent ? 2.2 : 1.8) : isCurrent ? 1.6 : 1}
              strokeDasharray={n.key === "PROPOSED" && !isCurrent ? "4 3" : undefined} />
            <text x={n.x + n.w / 2} y={isBlock ? n.y + 17 : n.y + 19} textAnchor="middle"
              fontWeight={isBlock || isCurrent ? 650 : undefined}
              fill={isBlock ? "var(--warn)" : isCurrent ? "var(--acc)" : "var(--text)"}>
              {LABEL_RU[n.key] || n.key}
            </text>
            {isBlock && (
              <text x={n.x + n.w / 2} y={n.y + 31} textAnchor="middle"
                fill="var(--warn)" fontSize="9.5">(retry · force · abort)</text>
            )}
            {isTarget && onMove && (
              <text x={n.x + n.w / 2} y={n.y + h + 12} textAnchor="middle"
                fill="var(--acc)" fontSize="9">клик — перевести</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export { LABEL_RU };
