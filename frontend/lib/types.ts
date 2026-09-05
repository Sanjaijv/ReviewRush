// Mirrors the response shapes returned by app/api/v1/dashboard.py.
// Kept as plain interfaces (not generated) since the backend has no OpenAPI
// client-generation step wired up yet - update these alongside the backend
// route when a field changes.

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

export type RunStatus = "complete" | "cancelled" | "oversized" | string;

export interface RunSummary {
  id: number;
  head_sha: string;
  base_sha: string;
  status: RunStatus;
  file_count: number;
  total_changed_lines: number;
  created_at: string;
}

export interface RunDetail {
  diff_snapshot: Record<string, unknown>;
  tool_runs: Record<string, unknown>[];
  ai_review: Record<string, unknown> | null;
  policy_decision: Record<string, unknown> | null;
  merge_attempts: Record<string, unknown>[];
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

// Metrics is intentionally untyped (compute_repository_metrics' shape isn't
// fixed/documented) - rendered as raw JSON, same as the previous dashboard.
export type RepositoryMetrics = Record<string, unknown>;
