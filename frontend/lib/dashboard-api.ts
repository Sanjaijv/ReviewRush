import { api, apiJson } from "@/lib/api";
import type {
  AuditEvent,
  RepoConfigResponse,
  RepoConfigVersion,
  RepositoryMetrics,
  RunDetail,
  RunSummary,
  TaskFailure,
} from "@/lib/types";
import type { LoadedRepositoryData } from "@/lib/dashboard-types";

export async function loadRepositoryData(repositoryId: number): Promise<LoadedRepositoryData> {
  const [runs, metrics, auditLog, config, configVersions, taskFailures] = await Promise.all([
    api<RunSummary[]>(`/repositories/${repositoryId}/runs`),
    api<RepositoryMetrics>(`/repositories/${repositoryId}/metrics`),
    api<AuditEvent[]>(`/repositories/${repositoryId}/audit-log`),
    api<RepoConfigResponse>(`/repositories/${repositoryId}/config`),
    api<RepoConfigVersion[]>(`/repositories/${repositoryId}/config/versions`),
    api<TaskFailure[]>(`/repositories/${repositoryId}/task-failures`),
  ]);
  return { runs, metrics, auditLog, config, configVersions, taskFailures };
}

export function loadRunDetail(repositoryId: number, runId: number) {
  return api<RunDetail>(`/repositories/${repositoryId}/runs/${runId}`);
}

export function rerunRun(repositoryId: number, runId: number) {
  return api(`/repositories/${repositoryId}/runs/${runId}/rerun`, { method: "POST" });
}

export function cancelRun(repositoryId: number, runId: number) {
  return api(`/repositories/${repositoryId}/runs/${runId}/cancel`, { method: "POST" });
}

export function resolveTaskFailure(repositoryId: number, failureId: number) {
  return api(`/repositories/${repositoryId}/task-failures/${failureId}/resolve`, { method: "POST" });
}

export function saveRepositoryConfig(repositoryId: number, config: Record<string, unknown>) {
  return apiJson(`/repositories/${repositoryId}/config`, "PUT", { config });
}

export function submitFindingFeedback(
  repositoryId: number,
  findingId: number,
  reaction: "useful" | "incorrect",
) {
  return apiJson(`/repositories/${repositoryId}/findings/${findingId}/feedback`, "POST", {
    reaction,
    consent: true,
  });
}
