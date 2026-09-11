import type { DemoDataSet } from "@/lib/dashboard-types";

const now = Date.now();
const minutesAgo = (minutes: number) => new Date(now - minutes * 60_000).toISOString();

const runs = [
  {
    id: 701,
    head_sha: "a1c4f2e9d1aa92c",
    base_sha: "7b90ee1b20fd21a",
    status: "complete",
    file_count: 6,
    total_changed_lines: 104,
    created_at: minutesAgo(4),
  },
  {
    id: 702,
    head_sha: "9de001b7c6b4480",
    base_sha: "a1c4f2e9d1aa92c",
    status: "oversized",
    file_count: 21,
    total_changed_lines: 892,
    created_at: minutesAgo(64),
  },
  {
    id: 703,
    head_sha: "55f3aa9d0f07bd2",
    base_sha: "9de001b7c6b4480",
    status: "cancelled",
    file_count: 3,
    total_changed_lines: 13,
    created_at: minutesAgo(24 * 60),
  },
  {
    id: 704,
    head_sha: "c301c0ffee201a6",
    base_sha: "55f3aa9d0f07bd2",
    status: "complete",
    file_count: 11,
    total_changed_lines: 188,
    created_at: minutesAgo(24 * 60 + 48),
  },
  {
    id: 705,
    head_sha: "db88ea4213c899a",
    base_sha: "c301c0ffee201a6",
    status: "queued",
    file_count: 2,
    total_changed_lines: 34,
    created_at: minutesAgo(24 * 60 + 75),
  },
] as const;

const detail = {
  run: runs[0],
  changed_files: [
    { path: "app/auth/session.py", status: "modified", additions: 22, deletions: 8 },
    { path: "app/auth/tokens.py", status: "modified", additions: 14, deletions: 2 },
    { path: "tests/auth/test_session.py", status: "added", additions: 68, deletions: 0 },
  ],
  tool_runs: [
    {
      check_name: "semgrep",
      category: "static analysis",
      conclusion: "passed",
      required: true,
      duration_ms: 13_400,
      summary: "No blocking patterns detected.",
    },
    {
      check_name: "gitleaks",
      category: "secrets",
      conclusion: "passed",
      required: true,
      duration_ms: 7_200,
      summary: "No secrets detected in changed files.",
    },
    {
      check_name: "dependency scan",
      category: "dependencies",
      conclusion: "failed",
      required: true,
      duration_ms: 18_800,
      summary: "1 dependency has a known high-severity advisory.",
    },
  ],
  ai_review: {
    status: "completed",
    decision: "HUMAN_REVIEW",
    risk: "high",
    confidence: 0.91,
    summary: "The session changes improve token rotation, but one comparison remains timing-sensitive.",
    provider: "openai",
    model: "gpt-5-coder",
    findings: [
      {
        id: 901,
        file: "app/auth/session.py",
        start_line: 42,
        end_line: 42,
        severity: "critical",
        category: "security",
        title: "Session token compared with ==, not constant-time",
        evidence: "The token strings are compared directly before the session is accepted.",
        recommendation: "Use a constant-time comparison such as hmac.compare_digest for session secrets.",
      },
      {
        id: 902,
        file: "app/auth/session.py",
        start_line: 67,
        end_line: 73,
        severity: "medium",
        category: "missing_tests",
        title: "Rotation path has no covering test",
        evidence: "The new rotation branch is not exercised by the existing session test fixture.",
        recommendation: "Add a test that expires the old token and asserts a new session is issued.",
      },
    ],
  },
  policy_decision: {
    decision: "HUMAN_REVIEW",
    risk: "high",
    reasons: [
      "A critical security finding remains unresolved.",
      "The dependency scan reported a high-severity advisory.",
    ],
    policy_version: "2026.08",
  },
  merge_attempts: [
    { outcome: "not_attempted", reasons: ["Policy decision requires human review."], created_at: minutesAgo(3) },
  ],
};

export const demoData: DemoDataSet = {
  installations: [
    { id: 1, account_login: "acme-corp", account_type: "Organization", status: "active" },
    { id: 2, account_login: "sanjaijv-labs", account_type: "Organization", status: "active" },
  ],
  repositoriesByInstallation: {
    1: [
      { id: 101, full_name: "acme-corp/reviewrush-test", default_branch: "main", is_active: true, disconnected_at: null },
      { id: 102, full_name: "acme-corp/payments-api", default_branch: "main", is_active: true, disconnected_at: null },
      { id: 103, full_name: "acme-corp/infra-terraform", default_branch: "main", is_active: false, disconnected_at: minutesAgo(3 * 24 * 60) },
    ],
    2: [
      { id: 201, full_name: "sanjaijv-labs/agent-playground", default_branch: "main", is_active: true, disconnected_at: null },
    ],
  },
  repositoryData: {
    101: {
      runs: [...runs],
      metrics: {
        total_reviews: 128,
        avg_review_time_ms: 142000,
        policy_decisions_by_outcome: { APPROVE: 104, HUMAN_REVIEW: 18, BLOCK: 6 },
        merge_attempts_by_outcome: { MERGED: 21 },
        false_positive_rate: 0.06,
      },
      auditLog: [
        { id: 1, actor_type: "system", actor_login: null, action: "policy.decided", target_type: "diff_snapshot", target_id: "881", metadata: { decision: "HUMAN_REVIEW", risk: "high" }, created_at: minutesAgo(4) },
        { id: 2, actor_type: "user", actor_login: "sanjaijv", action: "repository.config_updated", target_type: "config", target_id: "v4", metadata: { source: "dashboard" }, created_at: minutesAgo(60) },
        { id: 3, actor_type: "user", actor_login: "sanjaijv", action: "task_failure.resolved", target_type: "task_failure", target_id: "12", metadata: { task: "run_analysis_pipeline_task" }, created_at: minutesAgo(120) },
      ],
      config: { source: "dashboard_override", version: 4, config: { review: { enabled: true, max_changed_lines: 800 }, policy: { block_on: ["critical"] } } },
      configVersions: [
        { version: 4, actor_login: "sanjaijv", created_at: minutesAgo(60), config: { review: { enabled: true, max_changed_lines: 800 }, policy: { block_on: ["critical"] } } },
        { version: 3, actor_login: "sanjaijv", created_at: minutesAgo(14 * 24 * 60), config: { review: { enabled: true, max_changed_lines: 600 }, policy: { block_on: ["critical", "high"] } } },
        { version: 2, actor_login: "bot-migration", created_at: minutesAgo(21 * 24 * 60), config: { review: { enabled: true } } },
      ],
      taskFailures: [
        { id: 12, diff_snapshot_id: 702, task_name: "run_analysis_pipeline_task", task_id: "celery-55a", retry_count: 3, exception_type: "ConnectionError", exception_message: "Unable to connect to the worker queue after retry budget was exhausted.", resolved_at: null, resolved_by: null, created_at: minutesAgo(12) },
        { id: 13, diff_snapshot_id: 703, task_name: "run_ai_review_task", task_id: "celery-55b", retry_count: 1, exception_type: "TimeoutError", exception_message: "Model response exceeded the configured deadline.", resolved_at: null, resolved_by: null, created_at: minutesAgo(44) },
      ],
      details: { 701: detail },
    },
    102: {
      runs: [runs[1], runs[2]],
      metrics: { total_reviews: 64, avg_review_time_ms: 226000, policy_decisions_by_outcome: { APPROVE: 31, HUMAN_REVIEW: 15, BLOCK: 18 }, merge_attempts_by_outcome: { MERGED: 4 } },
      auditLog: [],
      config: { source: "repository_file", version: null, config: { review: { enabled: true } } },
      configVersions: [],
      taskFailures: [],
      details: {},
    },
    103: {
      runs: [], metrics: {}, auditLog: [], config: { source: "repository_file", version: null, config: null }, configVersions: [], taskFailures: [], details: {},
    },
    201: {
      runs: [runs[3]], metrics: { total_reviews: 18, avg_review_time_ms: 179000, policy_decisions_by_outcome: { APPROVE: 17, HUMAN_REVIEW: 1 }, merge_attempts_by_outcome: { MERGED: 2 } }, auditLog: [], config: { source: "repository_file", version: null, config: null }, configVersions: [], taskFailures: [], details: {},
    },
  },
  organizations: [
    { id: 21, slug: "acme-corp", name: "Acme Corp", role: "owner", plan: "pro", region: "us", retention_days_default: 30, ai_provider_override: null, ai_model_override: null, max_ai_reviews_per_day: 500, max_repositories: 25 },
  ],
  promotion: { id: 8, eval_run_id: 14, provider: "openai", model: "gpt-5-coder", prompt_version: "prompt-22", policy_version: "2026.08", created_at: minutesAgo(3 * 24 * 60) },
  finetuneJobs: [
    { id: "job-2026-09-01", model: "qwen2.5-coder:7b", method: "lora", status: "complete", created_at: minutesAgo(4 * 24 * 60), metrics: { precision: 0.83, recall: 0.76 }, log: ["dataset prepared · 4,920 examples", "training complete · 12 epochs", "shadow evaluation passed"] },
    { id: "job-2026-08-14", model: "qwen2.5-coder:7b", method: "lora", status: "failed", created_at: minutesAgo(22 * 24 * 60), metrics: {}, log: ["training started", "failed · out of memory"] },
  ],
};
