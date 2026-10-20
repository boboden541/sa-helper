import type { BoardState, Project, Story, TaskDoc } from "./types";

let currentFnr: string | null = null;
let currentProject: string | null = null;

/** Активные проект и Story (параметры ?project=&fnr=). */
export function setFnr(fnr: string | null) { currentFnr = fnr; }
export function setProject(project: string | null) { currentProject = project; }
export function getProject() { return currentProject; }

function withFnr(path: string): string {
  let full = path;
  if (currentProject) full += (full.includes("?") ? "&" : "?") + "project=" + currentProject;
  if (currentFnr) full += (full.includes("?") ? "&" : "?") + "fnr=" + currentFnr;
  return full;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  projects: () =>
    fetch("/api/projects").then((r) => json<{ projects: Project[] }>(r)),

  stories: (project?: string) =>
    fetch(withFnr(`/api/stories${project ? `?project=${project}` : ""}`))
      .then((r) => json<{ stories: Story[] }>(r)),

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
    fetch(withFnr("/api/story"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, source }),
    }).then((r) => json<{ ok: boolean; info: string }>(r)),

  createTask: (fnr: string, payload: Record<string, unknown>) =>
    fetch(withFnr(`/api/story/${fnr}/task`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => json<{ ok: boolean }>(r)),

  addProject: (name: string, path: string) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, path }),
    }).then((r) => json<{ ok: boolean; info: string }>(r)),

  stewardChat: () =>
    fetch(withFnr("/api/steward/chat")).then((r) =>
      json<{ messages: Array<{ ts: string; author: string; text: string }>; pending: boolean }>(r)),

  stewardMessage: (text: string) =>
    fetch(withFnr("/api/steward/message"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => json<{ ok: boolean }>(r)),

  move: (id: string, to: string) =>
    fetch(withFnr(`/api/task/${id}/move`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to }),
    }).then((r) => json<{ ok: boolean }>(r)),

  attachments: (id: string) =>
    fetch(withFnr(`/api/attachments?task=${id}`)).then((r) =>
      json<{ files: string[] }>(r)),

  uploadAttachment: (id: string, name: string, content: ArrayBuffer | string) =>
    fetch(withFnr(`/api/attachment/${id}/${encodeURIComponent(name)}`), {
      method: "POST", body: content,
    }),

  attachmentUrl: (id: string, name: string) =>
    withFnr(`/api/attachment/${id}/${encodeURIComponent(name)}`),

  /** Сохранить карточку (единое описание). 409 (живая сессия) не бросает —
   *  возвращается {ok:false, conflict:true} для confirm'а с force. */
  checklistSectionAdd: (tid: string, title: string, kind = "custom") =>
    fetch(withFnr(`/api/checklist/${tid}/section`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, kind }),
    }).then((r) => r.json()),

  checklistItemAdd: (tid: string, sectionId: number, text: string,
                     state = "todo", mandatory = false) =>
    fetch(withFnr(`/api/checklist/${tid}/item`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_id: sectionId, text, state, mandatory }),
    }).then((r) => r.json()),

  checklistItemPatch: (itemId: number, patch: Record<string, unknown>) =>
    fetch(withFnr(`/api/checklist/item/${itemId}`), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),

  checklistItemDelete: (itemId: number) =>
    fetch(withFnr(`/api/checklist/item/${itemId}`), { method: "DELETE" })
      .then((r) => r.json()),

  checklistSectionDelete: (sectionId: number) =>
    fetch(withFnr(`/api/checklist/section/${sectionId}`), { method: "DELETE" })
      .then((r) => r.json()),

  checklistImport: (tid: string, text: string) =>
    fetch(withFnr(`/api/checklist/${tid}/import`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => r.json()),

  saveCard: (id: string, cardMd: string, force = false) =>
    fetch(withFnr(`/api/task/${id}/card`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_md: cardMd, force }),
    }).then((r) => r.json().then((b) => ({
      ok: r.ok && !!(b as { ok?: boolean }).ok,
      conflict: r.status === 409,
      error: (b as { error?: string }).error,
    }))),
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

// иконка статуса для крупного чипа в шапке карточки (макет:279 «⏸ Нужен человек ▾»)
export const PIPE_ICON: Record<string, string> = {
  PROPOSED: "✎", BACKLOG: "🗒", READY: "⏳", IMPLEMENTING: "▶", REVIEW: "🔍",
  DONE: "✔", VERIFIED: "✅", BLOCKED: "⛔", NEEDS_HUMAN: "⏸", ABORTED: "✖",
};

export const PIPE_COLOR: Record<string, string> = {
  DONE: "ok", VERIFIED: "ok", NEEDS_HUMAN: "bad", BLOCKED: "warn",
  IMPLEMENTING: "acc", REVIEW: "acc", PROPOSED: "warn",
};
