import React from "react";
import { renderToString } from "react-dom/server";
import { TaskPanel } from "./src/components/task/TaskPanel";

const doc = {
  task: { id: "T4", title: "X", system: "core", status: "DONE", pipeline: "DONE",
    acceptance_criteria: [], checklist: { total: 3, done: 1, in_progress: 0 },
    usage: { tokens_total: 100, cost_usd: 0.01 }, actions: ["TASK_T4_REQUEST_CHANGES"],
    can_ask: true, live: { hb_age_s: 30, running: true, last_action: "x" },
    pipeline_since: "2026-10-17T10:00:00Z", branch: "b", review_iterations: 1 },
  card_md: "# T4\n\nкарточка",
  comments_md: "- [2026-10-17 | agent] запись\n- [2026-10-17 | reviewer] замечание\n",
  checklist_sections: [{ title: "План", items: [{ state: "done", text: "a" }], done: 1, wip: 0, total: 1 }],
  attachments: [],
};

try {
  const html = renderToString(React.createElement(TaskPanel, { doc, onClose: () => {}, onAction: () => {} }));
  console.log("RENDER OK, длина:", html.length);
  console.log("содержит заголовок:", html.includes("T4"));
} catch (e) {
  console.log("RENDER CRASH:", (e as Error).message);
  console.log((e as Error).stack?.split("\n").slice(0, 6).join("\n"));
}
