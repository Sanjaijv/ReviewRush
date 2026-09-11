// Backend-facing dashboard contracts. Keep these in step with app/api/v1/dashboard.py.

export interface Me {
  github_user_id: number;
  login: string;
  avatar_url: string;
  installation_ids: number[];
}

export interface Installation {
  id: number;
  account_login: string;
  account_type: string;
  status: string;
}

export interface RepositorySummary {
  id: number;
  full_name: string;
  default_branch: string;
  is_active: boolean;
  disconnected_at: string | null;
}

export type RunStatus = "complete" | "cancelled" | "oversized" | "queued" | "running" | string;

export interface RunSummary {
  id: number;
  head_sha: string;
  base_sha: string;
  status: RunStatus;
  file_count: number;
  total_changed_lines: number;
  created_at: string;
}

export interface ChangedFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
}

export interface ToolRunPayload {
  check_name: string;
  category: string;
  status?: string;
  conclusion: string;
  required: boolean;
  duration_ms: number;
  summary: string;
}

export interface FindingPayload {
  id?: number;
  file: string;
  start_line: number;
  end_line: number;
  severity: string;
  category: string;
  title: string;
  evidence?: string;
  recommendation: string;
}

export interface AIReviewPayload {
  status: string;
  decision: string | null;
  risk: string | null;
  confidence: number | null;
  summary: string;
  provider: string;
  model: string;
  findings: FindingPayload[];
}

export interface PolicyDecisionPayload {
  decision: string;
  risk: string;
  reasons: string[];
  policy_version: string;
}

export interface MergeAttemptPayload {
  outcome: string;
  reasons: string[];
  created_at: string;
}

export interface RunDetail {
  run: RunSummary;
  changed_files: ChangedFile[];
  tool_runs: ToolRunPayload[];
  ai_review: AIReviewPayload | null;
  policy_decision: PolicyDecisionPayload | null;
  merge_attempts: MergeAttemptPayload[];
  [key: string]: unknown;
}

export interface RepoConfigResponse {
  source: "dashboard_override" | "repository_file";
  version: number | null;
  config: Record<string, unknown> | null;
}

export interface RepoConfigVersion {
  version: number;
  actor_login: string;
  created_at: string;
  config: Record<string, unknown>;
}

export interface AuditEvent {
  id: number;
  actor_type: string;
  actor_login: string | null;
  action: string;
  target_type: string;
  target_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface TaskFailure {
  id: number;
  diff_snapshot_id: number | null;
  task_name: string;
  task_id: string;
  retry_count: number;
  exception_type: string;
  exception_message: string;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
}

export type RepositoryMetrics = Record<string, unknown>;

export interface Organization {
  id: number;
  slug: string;
  name: string;
  role: string;
  plan: string;
  region: string;
  retention_days_default: number | null;
  ai_provider_override: string | null;
  ai_model_override: string | null;
  max_ai_reviews_per_day: number | null;
  max_repositories: number | null;
}

export interface DatasetVersion {
  id: number;
  version: number;
  item_count: number;
  created_at: string;
}

export interface EvaluationRun {
  id: number;
  run_type: string;
  dataset_version_id: number | null;
  provider: string;
  model: string;
  prompt_version: string;
  policy_version: string;
  status: string;
  case_count: number;
  metrics: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
}

export interface Promotion {
  id: number;
  eval_run_id: number;
  provider: string;
  model: string;
  prompt_version: string;
  policy_version: string;
  created_at: string;
}

export interface FinetuneJob {
  id: string | number;
  model?: string;
  base_model?: string;
  output_model?: string | null;
  method: string;
  status: string;
  created_at: string;
  metrics?: Record<string, unknown>;
  log?: string[];
}
