// Зеркало канона harness/state_machine.py и манифеста v3.

export type PipelineStatus =
  | "PROPOSED"
  | "BACKLOG"
  | "READY"
  | "IMPLEMENTING"
  | "REVIEW"
  | "DONE"
  | "VERIFIED"
  | "BLOCKED"
  | "NEEDS_HUMAN"
  | "ABORTED";

export type V2Status =
  | "PLANNED" | "APPROVED" | "TDD_RED" | "TDD_GREEN" | "GATES"
  | "AGENT_REVIEW" | "DONE" | "ESCALATED_BLOCKED" | "ABORTED";

export interface AcceptanceCriterion {
  id: string;
  desc: string;
  status: "PENDING" | "PASSED" | "FAILED";
  test?: string | null;
}

export interface Finding {
  id: string;
  text: string;
  file?: string;
  resolution?: "open" | "resolved" | "still_blocking";
}

export interface LiveStatus {
  hb_age_s: number;
  running: boolean;
  last_action?: string;
}

export interface ChecklistProgress {
  total: number;
  done: number;
  in_progress: number;
}

export interface Task {
  id: string;
  title?: string;
  description?: string;
  system?: string;
  phase?: string;
  branch?: string;
  worktree?: string;
  status?: V2Status;
  pipeline?: PipelineStatus;
  paused?: boolean;
  blocked_from?: PipelineStatus | null;
  depends_on?: string[];
  acceptance_criteria?: AcceptanceCriterion[];
  findings?: Finding[];
  review_iterations?: number;
  review_verdict?: string | null;
  iteration_count?: number;
  origin?: "plan" | "manual" | "agent";
  session_id?: string;
  actions?: string[];
  can_ask?: boolean;
  checklist?: ChecklistProgress;
  live?: LiveStatus | null;
  usage?: Usage;
  pipeline_since?: string;
  move_targets?: string[];
  decomposed?: boolean;
}

export interface Usage {
  tokens_in?: number;
  tokens_out?: number;
  tokens_total?: number;
  cost_usd?: number;
  sessions?: number;
}

export interface Story {
  fnr: string;
  title: string;
  status: string;
  tasks: number;
  counts: Record<string, number>;
  usage?: Usage;
  task_list: Array<Task & { plan_done: number; plan_total: number }>;
  handoff_pending: boolean;
  handoff_failed: boolean;
  manifest_ok: boolean;
}

export interface BoardState {
  manifest: {
    fnr_id?: string;
    status?: string;
    story_title?: string;
    systems?: Array<{ name: string }>;
    tasks: Task[];
  };
  flags: string[];
}

export type ChecklistItemState =
  | "todo" | "inprog" | "review" | "done" | "blocked" | "failed";

export interface ChecklistSection {
  title: string;
  items: Array<{ state: ChecklistItemState; text: string }>;
  done: number;
  wip: number;
  total: number;
}

export interface EscalationOption {
  title: string;
  explanation?: string;
  flag?: string | null;
  recommended?: boolean;
}

export interface TaskDoc {
  task: Task;
  card_md: string;
  comments_md: string;
  ask_pending?: boolean;
  checklist_sections?: ChecklistSection[];
  attachments?: string[];
  options?: { options: EscalationOption[] } | null;
  problem?: {
    reason: string;
    diagnosis?: string | null;
    last_result: string;
    findings: Finding[];
    retries: number;
    review_iterations: number;
    blocked_from: string | null;
  } | null;
  checklist?: ChecklistSectionModel[];
}

export interface ChecklistItemModel {
  id: number;
  seq: number;
  depth: number;
  text: string;
  state: "todo" | "inprog" | "done" | "review" | "blocked" | "failed" | "skipped";
  mandatory: number;
  updated_at: string;
}

export interface ChecklistSectionModel {
  id: number;
  title: string;
  kind: "plan" | "review" | "custom";
  seq: number;
  note: string | null;
  items: ChecklistItemModel[];
}

export interface JournalEntry {
  ts: string;
  author: string;
  text: string;
}

export interface Project {
  name: string;
  path: string;
  task_count: number;
  usage: Usage;
  stories: Story[];
}
