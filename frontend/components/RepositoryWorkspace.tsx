"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, GitBranch, MoreHorizontal, Power } from "lucide-react";
import type { DemoRepositoryData, WorkspaceTab } from "@/lib/dashboard-types";
import type { RepositorySummary, RunDetail, RunSummary } from "@/lib/types";
import { apiJson, ApiError } from "@/lib/api";
import { loadRepositoryData, loadRunDetail, rerunRun, cancelRun } from "@/lib/dashboard-api";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { OverviewPanel } from "@/components/OverviewPanel";
import { RunsPanel } from "@/components/RunsPanel";
import { RunDetailPanel } from "@/components/RunDetailPanel";
import { ConfigPanel } from "@/components/ConfigPanel";
import { OpsPanel } from "@/components/OpsPanel";
import { ErrorPanel, LoadingPanel, StatusPill } from "@/components/dashboard/primitives";


export function RepositoryWorkspace({ repository, demoData, initialTab = "overview", initialRunId, onBack, onDisconnect }: { repository: RepositorySummary; demoData?: DemoRepositoryData; initialTab?: WorkspaceTab; initialRunId?: number | null; onBack: () => void; onDisconnect: () => void }) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<WorkspaceTab>(initialRunId ? "runs" : initialTab);
  const [data, setData] = useState<DemoRepositoryData | null>(demoData ?? null);
  const [loading, setLoading] = useState(!demoData);
  const [error, setError] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunSummary | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [runLoading, setRunLoading] = useState(Boolean(initialRunId));
  const [runError, setRunError] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  useEffect(() => {
    if (demoData) return;
    let cancelled = false;
    loadRepositoryData(repository.id).then((loaded) => { if (!cancelled) setData({ ...loaded, details: {} }); }).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load repository."); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [demoData, repository.id]);

  const unresolvedCount = data?.taskFailures.filter((failure) => !failure.resolved_at).length ?? 0;
  const routeRun = initialRunId && data ? data.runs.find((run) => run.id === initialRunId) ?? null : null;
  const displayedRun = selectedRun ?? routeRun;
  const currentTabLabel = useMemo(() => ({ overview: "Overview", runs: "Runs", config: "Config", ops: "Operations" })[activeTab], [activeTab]);

  useEffect(() => {
    if (!initialRunId || !data || runDetail || !routeRun) return;
    let cancelled = false;
    const detailPromise = demoData?.details[routeRun.id] ? Promise.resolve(demoData.details[routeRun.id]) : loadRunDetail(repository.id, routeRun.id);
    detailPromise.then((detail) => { if (!cancelled) setRunDetail(detail); }).catch((reason) => { if (!cancelled) setRunError(reason instanceof Error ? reason.message : "Could not load this run."); }).finally(() => { if (!cancelled) setRunLoading(false); });
    return () => { cancelled = true; };
  }, [data, demoData, initialRunId, repository.id, routeRun, runDetail]);

  async function openRun(run: RunSummary) {
    setSelectedRun(run);
    setRunError(null);
    setRunLoading(true);
    setActiveTab("runs");
    router.push(`/repositories/${repository.id}/runs/${run.id}`);
    try {
      const detail = demoData?.details[run.id] ?? await loadRunDetail(repository.id, run.id);
      setRunDetail(detail);
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : "Could not load this run.");
    } finally {
      setRunLoading(false);
    }
  }

  function changeTab(tab: WorkspaceTab) {
    setActiveTab(tab);
    setSelectedRun(null);
    setRunDetail(null);
    router.push(`/repositories/${repository.id}/${tab}`);
  }

  async function refresh() {
    if (demoData) return;
    setError(null);
    try { const loaded = await loadRepositoryData(repository.id); setData({ ...loaded, details: {} }); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not refresh repository."); }
  }

  async function handleRunAction(run: RunSummary, action: "rerun" | "cancel") {
    if (demoData) { setData((current) => current ? { ...current, runs: current.runs.map((row) => row.id === run.id ? { ...row, status: action === "cancel" ? "cancelled" : "queued" } : row) } : current); return; }
    try { if (action === "rerun") await rerunRun(repository.id, run.id); else await cancelRun(repository.id, run.id); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : `Could not ${action} this run.`); }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect this repository from ReviewRush?")) return;
    setDisconnecting(true);
    try { if (!demoData) await apiJson(`/repositories/${repository.id}/disconnect`, "POST", {}); onDisconnect(); } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Could not disconnect this repository."); } finally { setDisconnecting(false); }
  }

  if (error) return <ErrorPanel message={error} onRetry={() => void refresh()} />;
  if (loading || !data) return <LoadingPanel label={`Loading ${repository.full_name}`} />;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4"><div className="flex min-w-0 items-center gap-3"><button type="button" onClick={onBack} aria-label="Back to repositories" className="rr-focus-ring rounded-xs p-1.5 text-ink-500 transition hover:bg-surface-1 hover:text-accent"><ArrowLeft size={18} aria-hidden="true" /></button><div className="min-w-0"><p className="rr-eyebrow mb-1">Repository workspace / {currentTabLabel}</p><h1 className="truncate font-display text-2xl font-bold tracking-[-0.04em]">{repository.full_name}</h1><p className="mt-1 flex items-center gap-1.5 font-mono text-xs text-ink-500"><GitBranch size={13} aria-hidden="true" />{repository.default_branch}</p></div></div><div className="flex items-center gap-2"><StatusPill label={repository.is_active ? "connected" : "inactive"} tone={repository.is_active ? "good" : "neutral"} /><details className="relative"><summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-2 rounded-xs border border-line px-3 py-2 text-sm font-semibold text-ink-700 transition hover:border-accent hover:text-accent [&::-webkit-details-marker]:hidden"><MoreHorizontal size={16} aria-hidden="true" />Actions</summary><div className="absolute right-0 top-11 z-10 w-52 rounded-sm border border-line bg-surface-1 p-1.5 shadow-[0_12px_32px_rgba(23,27,34,0.12)]"><button type="button" onClick={() => void disconnect()} disabled={disconnecting} className="rr-focus-ring flex w-full items-center gap-2 rounded-xs px-3 py-2 text-left text-sm text-bad transition hover:bg-bad/5 disabled:opacity-50"><Power size={14} aria-hidden="true" />{disconnecting ? "Disconnecting…" : "Disconnect repository"}</button><a href={`https://github.com/${repository.full_name}`} target="_blank" rel="noreferrer" className="rr-focus-ring flex items-center gap-2 rounded-xs px-3 py-2 text-sm text-ink-700 transition hover:bg-paper-0 hover:text-accent"><ExternalLink size={14} aria-hidden="true" />Open on GitHub</a></div></details></div></div>
      <WorkspaceTabs activeTab={activeTab} onChange={changeTab} failureCount={unresolvedCount} />
      <div className="pt-7" role="tabpanel">
        {activeTab === "overview" && <OverviewPanel metrics={data.metrics} runs={data.runs} unresolvedFailureCount={unresolvedCount} onOpenRun={(run) => void openRun(run)} onViewAll={() => changeTab("runs")} onViewFailures={() => changeTab("ops")} />}
        {activeTab === "runs" && (displayedRun ? <RunDetailPanel run={displayedRun} detail={runDetail} loading={runLoading} error={runError} repositoryFullName={repository.full_name} repositoryId={repository.id} demo={Boolean(demoData)} onBack={() => { setSelectedRun(null); setRunDetail(null); router.push(`/repositories/${repository.id}/runs`); }} /> : <RunsPanel runs={data.runs} onOpenRun={(run) => void openRun(run)} onRerun={(run) => handleRunAction(run, "rerun")} onCancel={(run) => handleRunAction(run, "cancel")} />)}
        {activeTab === "config" && <ConfigPanel repositoryId={repository.id} config={data.config} versions={data.configVersions} demo={Boolean(demoData)} onSaved={() => void refresh()} />}
        {activeTab === "ops" && <OpsPanel repositoryId={repository.id} taskFailures={data.taskFailures} auditLog={data.auditLog} demo={Boolean(demoData)} onResolved={() => void refresh()} />}
      </div>
    </div>
  );
}
