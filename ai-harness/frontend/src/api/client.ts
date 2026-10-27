// Типизированный клиент REST API (СТ §4.1.2, Приложение В)

export interface TaskCard {
  code: string
  title: string
  priority: string
  type: string
  statusKey: string
  project?: string
  storyCode?: string | null
  psiPath?: string | null
  tags?: string[]
  agent?: { name: string } | null
  tokensUsed?: number
  gate?: { allowed: string[]; denied: { to: string; reason: string }[] }
  descriptionMd?: string
  changedByOther?: boolean
  relations?: { id: string; kind: string; code: string; title: string }[]
  blockedReason?: string | null
  createdAt?: string
  updatedAt?: string
}

export interface GateInfo { allowed: string[]; denied: { to: string; reason: string }[] }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const err = new Error(body.message || `HTTP ${res.status}`) as Error & { tech?: string; status?: number }
    err.tech = body.techDetail ?? body.techDetail
    err.status = res.status
    throw err
  }
  return res.json() as Promise<T>
}

export const api = {
  login: (name: string, password: string) =>
    request<{ user: string }>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ name, password }),
    }),
  logout: () => request<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' }),
  matrix: (typeKey: string) =>
    request<{ type: string; matrix: Record<string, { userId: string; name: string; mode: string }[]> }>(`/api/v1/matrix/${typeKey}`),
  setMatrix: (typeKey: string, statusKey: string, entries: { userId: string; mode: string }[]) =>
    request<{ ok: boolean }>(`/api/v1/matrix/${typeKey}/${statusKey}`, {
      method: 'PUT', body: JSON.stringify({ statusKey, entries }),
    }),
  agents: () => request<{ id: string; name: string; role: string; connectionId: string; isPreset: boolean; model: string; allowedTools: string[]; mcpServers: Record<string, unknown> | null; agentDir: string; skills: string[] }[]>('/api/v1/agents'),
  toolContent: (kind: string, name: string) => request<{ kind: string; name: string; relPath: string; description?: string; content: string; changed: boolean }>(`/api/v1/tools/${kind}/${name}`),
  toolWrite: (kind: string, name: string, content: string) => request<{ ok: boolean; hash: string }>(`/api/v1/tools/${kind}/${name}`, { method: 'PUT', body: JSON.stringify({ content }) }),
  users: () => request<{ id: string; name: string; userType: string }[]>('/api/v1/users'),
  createColumn: (payload: { label: string; color?: string }) =>
    request<{ id: string }>('/api/v1/alias-columns', { method: 'POST', body: JSON.stringify(payload) }),
  updateColumn: (id: string, payload: { label?: string; color?: string; position?: number }) =>
    request<{ id: string }>(`/api/v1/alias-columns/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteColumn: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/alias-columns/${id}`, { method: 'DELETE' }),
  tasks: (params: Record<string, string | undefined>) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v && q.set(k, v))
    return request<{ total: number; items: TaskCard[] }>(`/api/v1/tasks?${q}`)
  },
  task: (code: string) => request<TaskCard>(`/api/v1/tasks/${code}`),
  createTask: (payload: unknown) =>
    request<TaskCard>('/api/v1/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  patchTask: (code: string, payload: unknown) =>
    request<TaskCard>(`/api/v1/tasks/${code}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  transition: (code: string, to: string) =>
    request<{ applied: boolean; reason?: string }>(`/api/v1/tasks/${code}/transitions`, {
      method: 'POST', body: JSON.stringify({ to }),
    }),
  force: (code: string, to: string, reason: string) =>
    request<{ applied: boolean }>(`/api/v1/tasks/${code}/force`, {
      method: 'POST', body: JSON.stringify({ to, reason }),
    }),
  runs: (code: string) =>
    request<{ id: string; attempt: number; running: boolean; stale: boolean; outcome: string | null; agent: string; input: number; output: number; cache: number; tokens: number; startedAt: string; heartbeatAt: string | null; finishedAt: string | null; statusKey: string }[]>(`/api/v1/tasks/${code}/runs`),
  runLog: (runId: string, after = 0) =>
    request<{ items: { seq: number; kind: string; text: string | null; data?: { [k: string]: unknown } | null; at: string }[]; last: number }>(`/api/v1/runs/${runId}/log?after=${after}`),
  interrupt: (code: string, reason: string) =>
    request<{ ok: boolean }>(`/api/v1/tasks/${code}/interrupt`, { method: 'POST', body: JSON.stringify({ reason }) }),
  chronicle: (code: string) =>
    request<{ items: { id: string; type: string; authorKind: string; ruleCode?: string; message: string; at: string }[] }>(
      `/api/v1/tasks/${code}/chronicle`),
  notifications: () =>
    request<{ items: { id: string; code: string; eventKey: string; message: string; techDetail?: string }[] }>(
      '/api/v1/notifications'),
  psi: (code: string) =>
    request<{ versions: { version: number }[]; items: { position: number; kind: string; text: string; expected?: string; actual?: string; status: string; bugTaskId?: string }[]; runs: { id: string; passed: number; failed: number; at: string }[] }>(
      `/api/v1/stories/${code}/psi`),
  psiRun: (code: string, results: { position: number; passed: boolean; actual: string }[]) =>
    request<{ passed: number; failed: number; bugProposals: { position: number; action: string; expected: string; actual: string }[] }>(
      `/api/v1/stories/${code}/psi/runs`, { method: 'POST', body: JSON.stringify({ results }) }),
  comments: (code: string) =>
    request<{ id: string; author: string; body: string; at: string }[]>(`/api/v1/tasks/${code}/comments`),
  addRelation: (code: string, toCode: string, kind: string) =>
    request<{ id: string }>(`/api/v1/tasks/${code}/relations`, { method: 'POST', body: JSON.stringify({ toCode, kind }) }),
  delRelation: (code: string, relationId: string) =>
    request<{ ok: boolean }>(`/api/v1/tasks/${code}/relations/${relationId}`, { method: 'DELETE' }),
  storyLink: (code: string, storyCode: string | null) =>
    request<{ ok: boolean }>(`/api/v1/tasks/${code}/story-link`, { method: 'POST', body: JSON.stringify({ storyCode }) }),
  addComment: (code: string, body: string) =>
    request<{ id: string }>(`/api/v1/tasks/${code}/comments`, { method: 'POST', body: JSON.stringify({ body }) }),
  artifact: (code: string, kind: string) =>
    request<{ versions: { version: number; bodyMd: string; at: string }[] }>(`/api/v1/tasks/${code}/artifacts/${kind}`),
  addArtifact: (code: string, kind: string, bodyMd: string) =>
    request<{ version: number }>(`/api/v1/tasks/${code}/artifacts/${kind}`, { method: 'POST', body: JSON.stringify({ bodyMd }) }),
  patchTags: (code: string, tags: string[]) =>
    request<TaskCard>(`/api/v1/tasks/${code}`, { method: 'PATCH', body: JSON.stringify({ tags }) }),
  validateFlow: (typeKey: string) =>
    request<{ errors: string[]; warnings: string[]; ok: boolean }>(`/api/v1/flows/${typeKey}/validate`),
  pipelinePaused: () =>
    request<{ paused: boolean }>('/api/v1/pipeline-paused'),
  pipelinePause: (paused: boolean, reason?: string) =>
    request<{ ok: boolean; interrupted: number }>('/api/v1/pipeline-pause', {
      method: 'POST', body: JSON.stringify({ paused, reason: reason || null }),
    }),
  pipelineStatus: () =>
    request<{ warnings: { level: string; message: string; goto?: string }[] }>('/api/v1/pipeline-status'),
  eve: (text: string, screenTaskCode?: string) =>
    request<{ reply?: string; action?: string; intent?: { kind: string; task: string; to: string } }>(
      '/api/v1/assistant/messages', { method: 'POST', body: JSON.stringify({ text, screenTaskCode }) }),
  queue: () => request<{ working: { code: string; status: string; agent: string; minutes?: number }[]; waiting: { code: string; status: string; attempts: number }[]; blocked: { code: string; reason: string }[] }>('/api/v1/queue'),
  projects: () => request<{ id: string; name: string; mnemonic: string; isArchived: boolean; openCount?: number }[]>('/api/v1/projects'),
  flow: (typeKey: string) =>
    request<{ version: number; isPublished: boolean; statuses: { key: string; label: string; aliasColumnId: string; gate?: string; stageDesc?: string; entry: boolean; terminal: boolean; blocking: boolean }[]; transitions: { from: string; to: string; runner: string; display: string; rule?: string }[] }>(
      `/api/v1/flows/${typeKey}`),
  requestProviders: () =>
    request<{ id: string; name: string; protocol: string; url: string; model: string; tokenTail: string; checkStatus: string; isActive: boolean }[]>('/api/v1/connections'),
  aliasColumns: () => request<{ id: string; label: string; color: string; position: number }[]>('/api/v1/alias-columns'),
  saveDraft: (typeKey: string, definition: unknown) =>
    request<{ version: number }>(`/api/v1/flows/${typeKey}/draft`, { method: 'PUT', body: JSON.stringify(definition) }),
  publishFlow: (typeKey: string, migrations?: Record<string, string>) =>
    request<{ version: number }>(`/api/v1/flows/${typeKey}/publish`, {
      method: 'POST', body: JSON.stringify({ migrations: migrations ?? null }),
    }),
}
