"use client";

import { ChevronDown, ArrowRight } from "lucide-react";
import type { RepositoryMetrics, RunSummary } from "@/lib/types";
import { mapMetricModels } from "@/lib/dashboard-mappers";
import { formatRelativeTime, shortSha } from "@/lib/formatters";
import { AlertBanner, EmptyState, MetricTile, SectionHeader, StatusPill, TextButton } from "@/components/dashboard/primitives";

export function OverviewPanel({ metrics, runs, unresolvedFailureCount, onOpenRun, onViewAll, onViewFailures }: { metrics: RepositoryMetrics; runs: RunSummary[]; unresolvedFailureCount: number; onOpenRun: (run: RunSummary) => void; onViewAll: () => void; onViewFailures: () => void }) {
  const metricModels = mapMetricModels(metrics);
  return (
    <div className="space-y-8">
      {unresolvedFailureCount > 0 && <AlertBanner tone="warn" action={<TextButton className="text-warn decoration-warn/40 hover:decoration-warn" onClick={onViewFailures}>Review failures <ArrowRight className="ml-1 inline" size={14} aria-hidden="true" /></TextButton>}><strong>{unresolvedFailureCount} unresolved task {unresolvedFailureCount === 1 ? "failure" : "failures"}</strong><span className="ml-1 text-warn/80">The review pipeline needs operator attention.</span></AlertBanner>}
      <section>
        <SectionHeader eyebrow="Repository health" title="Is this repo healthy?" description="A compact view of review volume, policy outcomes, and pipeline speed." />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{metricModels.map((metric) => <MetricTile key={metric.label} {...metric} />)}</div>
        <details className="mt-3 rr-card group"><summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold text-ink-700 [&::-webkit-details-marker]:hidden"><ChevronDown size={15} className="transition group-open:rotate-180" aria-hidden="true" />More metrics<span className="ml-auto font-mono text-[11px] font-medium uppercase tracking-[0.05em] text-ink-500">{Object.keys(metrics).length} available</span></summary><div className="grid gap-3 border-t border-line px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(metrics).filter(([key]) => !["total_reviews", "avg_review_time_ms", "policy_decisions_by_outcome", "merge_attempts_by_outcome"].includes(key)).map(([key, value]) => <div key={key} className="rounded-xs bg-paper-0 px-3 py-2"><p className="font-mono text-[11px] text-ink-500">{key}</p><p className="mt-1 truncate text-sm font-semibold">{typeof value === "object" ? JSON.stringify(value) : String(value ?? "Unavailable")}</p></div>)}</div></details>
      </section>
      <section>
        <SectionHeader eyebrow="Latest activity" title="Recent runs" action={<TextButton onClick={onViewAll}>View all <ArrowRight className="ml-1 inline" size={14} aria-hidden="true" /></TextButton>} />
        {runs.length === 0 ? <EmptyState title="No runs yet." description="The first reviewed push will appear here once ReviewRush processes it." /> : <div className="rr-card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left"><thead className="border-b border-line bg-paper-0/70"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Commit</th><th className="px-4 py-3 font-medium">Files</th><th className="px-4 py-3 font-medium">Lines</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3" /></tr></thead><tbody className="divide-y divide-line">{runs.slice(0, 5).map((run) => <tr key={run.id} className="transition hover:bg-paper-0/65"><td className="px-4 py-3 font-mono text-sm font-medium">{shortSha(run.head_sha)}</td><td className="px-4 py-3 text-sm text-ink-700">{run.file_count}</td><td className="px-4 py-3 font-mono text-xs text-ink-700">+{run.total_changed_lines}</td><td className="px-4 py-3"><StatusPill label={run.status} /></td><td className="px-4 py-3 text-sm text-ink-500">{formatRelativeTime(run.created_at)}</td><td className="px-4 py-3 text-right"><button type="button" onClick={() => onOpenRun(run)} className="rr-focus-ring rounded-xs p-1 text-ink-500 transition hover:text-accent" aria-label={`View run ${shortSha(run.head_sha)}`}><ArrowRight size={16} aria-hidden="true" /></button></td></tr>)}</tbody></table></div></div>}
      </section>
    </div>
  );
}
