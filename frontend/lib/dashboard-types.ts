import type {
  AuditEvent,
  FinetuneJob,
  Installation,
  Organization,
  Promotion,
  RepoConfigResponse,
  RepoConfigVersion,
  RepositoryMetrics,
  RepositorySummary,
  RunDetail,
  RunSummary,
  TaskFailure,
} from "@/lib/types";

export type StatusTone = "good" | "warn" | "bad" | "neutral" | "accent";
export type WorkspaceTab = "overview" | "runs" | "config" | "ops";
export type OpsTab = "failures" | "audit";
export type AdminSurface = "organization" | "evaluation" | "finetune";

export interface LoadedRepositoryData {
  runs: RunSummary[];
  metrics: RepositoryMetrics;
  auditLog: AuditEvent[];
  config: RepoConfigResponse;
  configVersions: RepoConfigVersion[];
  taskFailures: TaskFailure[];
}

export interface RepositoryMetric {
  label: string;
  value: string;
  hint: string;
  unavailable?: boolean;
}

export interface RepositoryCardModel {
  repository: RepositorySummary;
  recentPolicy?: string;
  recentRunAt?: string;
}

export interface DemoRepositoryData extends LoadedRepositoryData {
  details: Record<number, RunDetail>;
}

export interface DemoDataSet {
  installations: Installation[];
  repositoriesByInstallation: Record<number, RepositorySummary[]>;
  repositoryData: Record<number, DemoRepositoryData>;
  organizations: Organization[];
  promotion: Promotion | null;
  finetuneJobs: FinetuneJob[];
}
