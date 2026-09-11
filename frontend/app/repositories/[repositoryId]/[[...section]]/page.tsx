import { Dashboard } from "@/components/Dashboard";
import type { WorkspaceTab } from "@/lib/dashboard-types";

const tabs = new Set<WorkspaceTab>(["overview", "runs", "config", "ops"]);

export default async function RepositoryPage({ params }: { params: Promise<{ repositoryId: string; section?: string[] }> }) {
  const { repositoryId, section = [] } = await params;
  const parsedId = Number(repositoryId);
  const initialTab = tabs.has(section[0] as WorkspaceTab) ? section[0] as WorkspaceTab : "overview";
  const runId = initialTab === "runs" && section[1] ? Number(section[1]) : null;
  return <Dashboard initialRepositoryId={Number.isFinite(parsedId) ? parsedId : null} initialTab={initialTab} initialRunId={runId !== null && Number.isFinite(runId) ? runId : null} />;
}
