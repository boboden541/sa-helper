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

export interface ChecklistSection {
  title: string;
  items: Array<{ state: "todo" | "wip" | "done"; text: string }>;
  done: number;
  wip: number;
  total: number;
}

export interface TaskDoc {
  task: Task;
  card_md: string;
  comments_md: string;
  ask_pending?: boolean;
  checklist_sections?: ChecklistSection[];
  attachments?: string[];
}

export interface JournalEntry {
  ts: string;
  author: string;
  text: string;
}
