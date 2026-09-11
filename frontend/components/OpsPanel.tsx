"use client";

import { useState } from "react";
import { CircleCheck, CircleX, Eye } from "lucide-react";
import type { AuditEvent, TaskFailure } from "@/lib/types";
import { resolveTaskFailure } from "@/lib/dashboard-api";
import { formatActor, formatRelativeTime } from "@/lib/formatters";
import { AlertBanner, EmptyState, SectionHeader } from "@/components/dashboard/primitives";
import { JsonBlock } from "@/components/JsonBlock";

export function OpsPanel({ repositoryId, taskFailures, auditLog, demo, onResolved }: { repositoryId: number; taskFailures: TaskFailure[]; auditLog: AuditEvent[]; demo: boolean; onResolved: () => void }) {
  const [active, setActive] = useState<"failures" | "audit">("failures");
  const [showResolved, setShowResolved] = useState(false);
  const [resolvedIds, setResolvedIds] = useState<number[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const visibleFailures = taskFailures.filter((failure) => showResolved ? true : !failure.resolved_at && !resolvedIds.includes(failure.id));
  const unresolved = taskFailures.filter((failure) => !failure.resolved_at && !resolvedIds.includes(failure.id)).length;

  async function resolve(failure: TaskFailure) {
    setBusyId(failure.id);
    try {
      if (!demo) await resolveTaskFailure(repositoryId, failure.id);
      setResolvedIds((current) => [...current, failure.id]);
      onResolved();
    } finally { setBusyId(null); }
  }

  return (
    <div>
      <SectionHeader eyebrow="Operations" title="Task failures & Audit log" description="What happened, and did a human deal with it?" />
      <div className="mb-6 flex gap-1 border-b border-line" role="tablist" aria-label="Operations panes">
        <button type="button" role="tab" aria-selected={active === "failures"} onClick={() => setActive("failures")} className={`rr-focus-ring relative flex items-center gap-2 px-3 py-3 text-sm font-semibold ${active === "failures" ? "text-accent" : "text-ink-500"}`}>Task failures {unresolved > 0 && <span className="rounded-xs bg-bad/10 px-1.5 font-mono text-[10px] text-bad">{unresolved}</span>}{active === "failures" && <span className="absolute inset-x-2 bottom-0 h-0.5 bg-accent" />}</button>
        <button type="button" role="tab" aria-selected={active === "audit"} onClick={() => setActive("audit")} className={`rr-focus-ring relative flex items-center gap-2 px-3 py-3 text-sm font-semibold ${active === "audit" ? "text-accent" : "text-ink-500"}`}>Audit log {active === "audit" && <span className="absolute inset-x-2 bottom-0 h-0.5 bg-accent" />}</button>
      </div>
      {active === "failures" ? <div role="tabpanel"><div className="mb-4 flex items-center justify-between gap-3">{unresolved > 0 ? <AlertBanner tone="warn"><strong>{unresolved} unresolved task {unresolved === 1 ? "failure" : "failures"}</strong><span className="ml-1 text-warn/80">Resolve to mark as seen.</span></AlertBanner> : <AlertBanner tone="good"><strong>All clear.</strong><span className="ml-1 text-good/80">No unresolved task failures.</span></AlertBanner>}<label className="flex shrink-0 items-center gap-2 text-sm text-ink-500"><input type="checkbox" checked={showResolved} onChange={(event) => setShowResolved(event.target.checked)} className="accent-accent" />Show resolved</label></div>{visibleFailures.length === 0 ? <EmptyState title={showResolved ? "No task failures recorded." : "No unresolved task failures."} description="Pipeline failures will appear here when an operation needs a human to mark it resolved." /> : <div className="rr-card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left"><thead className="border-b border-line bg-paper-0/70"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Task</th><th className="px-4 py-3 font-medium">Error</th><th className="px-4 py-3 font-medium">Retries</th><th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3" /></tr></thead><tbody className="divide-y divide-line">{visibleFailures.map((failure) => <tr key={failure.id} className="hover:bg-paper-0/65"><td className="px-4 py-4"><p className="font-mono text-xs">{failure.task_name}</p><p className="mt-1 text-xs text-ink-500">{failure.task_id}</p></td><td className="max-w-sm px-4 py-4"><p className="text-sm font-semibold text-bad">{failure.exception_type}</p><p className="mt-1 truncate text-sm text-ink-500">{failure.exception_message}</p></td><td className="px-4 py-4 font-mono text-sm">{failure.retry_count}×</td><td className="px-4 py-4 text-sm text-ink-500">{formatRelativeTime(failure.created_at)}</td><td className="px-4 py-4 text-right">{failure.resolved_at || resolvedIds.includes(failure.id) ? <span className="inline-flex items-center gap-1 text-xs font-semibold text-good"><CircleCheck size={14} aria-hidden="true" />Resolved</span> : <button type="button" disabled={busyId === failure.id} onClick={() => void resolve(failure)} className="rr-focus-ring rounded-xs border border-line px-3 py-1.5 text-xs font-semibold text-accent transition hover:border-accent disabled:opacity-50">{busyId === failure.id ? "Resolving…" : "Resolve"}</button>}</td></tr>)}</tbody></table></div></div>}</div> : <div role="tabpanel"><div className="rr-card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left"><thead className="border-b border-line bg-paper-0/70"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Action</th><th className="px-4 py-3 font-medium">Target</th><th className="px-4 py-3 font-medium">Actor</th><th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3" /></tr></thead><tbody className="divide-y divide-line">{auditLog.length > 0 ? auditLog.map((event) => <AuditRow key={event.id} event={event} />) : <tr><td colSpan={5} className="px-4 py-12 text-center text-sm text-ink-500">No audit events recorded for this repository.</td></tr>}</tbody></table></div></div></div>}
    </div>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  return <><tr className="font-mono text-xs transition hover:bg-paper-0/65"><td className="px-4 py-3 text-ink-700">{event.action}</td><td className="px-4 py-3 text-ink-500">{event.target_type} #{event.target_id}</td><td className="px-4 py-3 text-ink-500">{formatActor(event.actor_type, event.actor_login)}</td><td className="px-4 py-3 text-ink-500">{formatRelativeTime(event.created_at)}</td><td className="px-4 py-3 text-right"><button type="button" onClick={() => setOpen((current) => !current)} aria-expanded={open} aria-label={`Show metadata for ${event.action}`} className="rr-focus-ring rounded-xs p-1 text-ink-500 transition hover:text-accent">{open ? <CircleX size={15} aria-hidden="true" /> : <Eye size={15} aria-hidden="true" />}</button></td></tr>{open && <tr><td colSpan={5} className="border-t border-line bg-ink-900/95 px-4 py-3"><JsonBlock value={event.metadata} /></td></tr>}</>;
}
