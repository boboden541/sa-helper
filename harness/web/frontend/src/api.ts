import type { BoardState, Story, TaskDoc } from "./types";

let currentFnr: string | null = null;

/** Активная Story (для параметра ?fnr=); null — портфель. */
export function setFnr(fnr: string | null) { currentFnr = fnr; }
export function getFnr() { return currentFnr; }

function withFnr(path: string): string {
  if (!currentFnr) return path;
  return path + (path.includes("?") ? "&" : "?") + "fnr=" + currentFnr;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  stories: () =>
    fetch("/api/stories").then((r) => json<{ stories: Story[] }>(r)),

  state: (fnr?: string) =>
    fetch(withFnr(fnr ? `/api/state?fnr=${fnr}` : "/api/state")).then((r) =>
      json<BoardState>(r)),

  task: (id: string) =>
    fetch(withFnr(`/api/task/${id}`)).then((r) => json<TaskDoc>(r)),

  log: (id: string) =>
    fetch(withFnr(`/api/log/${id}`)).then((r) =>
      json<{ log: string; file: string | null }>(r)),

  timeline: (id: string) =>
    fetch(withFnr(`/api/timeline/${id}`)).then((r) =>
      json<{ entries: Array<{ ts: string; text: string }> }>(r)),

  setFlag: (name: string, method: "POST" | "DELETE" = "POST") =>
    fetch(withFnr(`/api/flag/${name}`), { method }),

  comment: (id: string, text: string) =>
    fetch(withFnr(`/api/comment/${id}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),

  ask: (id: string, text: string) =>
    fetch(withFnr(`/api/ask/${id}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),

  createStory: (title: string, source: string) =>
    fetch("/api/story", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, source }),
    }).then((r) => json<{ ok: boolean; info: string }>(r)),

  createTask: (fnr: string, payload: Record<string, unknown>) =>
    fetch(`/api/story/${fnr}/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => json<{ ok: boolean }>(r)),

  editTaskDescription: (id: string, description: string) =>
    fetch(withFnr(`/api/flag/TASK_EDIT_${id}.json`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    }),
};

export function pipelineOf(t: {
  pipeline?: string; status?: string;
}): string {
  const m: Record<string, string> = {
    PLANNED: "BACKLOG", APPROVED: "READY", TDD_RED: "IMPLEMENTING",
    TDD_GREEN: "IMPLEMENTING", GATES: "IMPLEMENTING",
    AGENT_REVIEW: "REVIEW", ESCALATED_BLOCKED: "NEEDS_HUMAN",
  };
  return t.pipeline || m[t.status || ""] || "BACKLOG";
}

export const PIPE_RU: Record<string, string> = {
  PROPOSED: "Предложена", BACKLOG: "Бэклог", READY: "Готова к запуску",
  IMPLEMENTING: "В работе", REVIEW: "Ревью", DONE: "Готова",
  VERIFIED: "Проверена", BLOCKED: "Блок", NEEDS_HUMAN: "Нужен человек",
  ABORTED: "Снята",
};

export const PIPE_COLOR: Record<string, string> = {
  DONE: "ok", VERIFIED: "ok", NEEDS_HUMAN: "bad", BLOCKED: "warn",
  IMPLEMENTING: "acc", REVIEW: "acc", PROPOSED: "warn",
};
