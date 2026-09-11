"use client";

import { useMemo, useState } from "react";
import { CalendarDays, ChevronDown, Eye, RotateCcw, Square, SlidersHorizontal } from "lucide-react";
import type { RunSummary } from "@/lib/types";
import { formatRelativeTime, shortSha } from "@/lib/formatters";
import { EmptyState, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

const statuses = ["complete", "oversized", "cancelled", "queued", "running"];

export function RunsPanel({ runs, onOpenRun, onRerun, onCancel }: { runs: RunSummary[]; onOpenRun: (run: RunSummary) => void; onRerun: (run: RunSummary) => Promise<void>; onCancel: (run: RunSummary) => Promise<void> }) {
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>([]);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const filteredRuns = useMemo(() => runs.filter((run) => {
    const date = new Date(run.created_at);
    const afterStart = fromDate ? date >= new Date(`${fromDate}T00:00:00`) : true;
    const beforeEnd = toDate ? date <= new Date(`${toDate}T23:59:59`) : true;
    return (selectedStatuses.length === 0 || selectedStatuses.includes(run.status)) && afterStart && beforeEnd;
  }), [fromDate, selectedStatuses, toDate, runs]);

  async function action(run: RunSummary, callback: (run: RunSummary) => Promise<void>) {
    setBusyId(run.id);
    try { await callback(run); } finally { setBusyId(null); }
  }

  return (
    <div>
      <SectionHeader eyebrow="History" title="Review runs" description="Every reviewed push, newest first." action={<span className="font-mono text-xs text-ink-500">{filteredRuns.length} / {runs.length} runs</span>} />
      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-sm border border-line bg-surface-1 p-3">
        <SlidersHorizontal size={15} className="ml-1 text-ink-500" aria-hidden="true" />
        <details className="relative">
          <summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-2 rounded-xs border border-line px-3 py-1.5 text-sm font-semibold text-ink-700 [&::-webkit-details-marker]:hidden">
            Status {selectedStatuses.length > 0 && <span className="rounded-xs bg-accent/10 px-1.5 font-mono text-[10px] text-accent">{selectedStatuses.length}</span>}<ChevronDown size={14} aria-hidden="true" />
          </summary>
          <div className="absolute left-0 top-10 z-10 w-44 rounded-sm border border-line bg-surface-1 p-2 shadow-[0_12px_32px_rgba(23,27,34,0.12)]">
            {statuses.map((status) => <label key={status} className="flex cursor-pointer items-center gap-2 rounded-xs px-2 py-2 text-sm hover:bg-paper-0"><input type="checkbox" checked={selectedStatuses.includes(status)} onChange={(event) => setSelectedStatuses((current) => event.target.checked ? [...current, status] : current.filter((value) => value !== status))} className="accent-accent" />{status}</label>)}
          </div>
        </details>
        <label className="flex items-center gap-2 rounded-xs border border-line px-3 py-1.5 text-sm text-ink-700"><CalendarDays size={14} className="text-ink-500" aria-hidden="true" /><span className="sr-only">From date</span><input aria-label="From date" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} className="min-w-0 bg-transparent text-sm outline-hidden" /></label>
        <span className="text-ink-500">→</span>
        <label className="flex items-center gap-2 rounded-xs border border-line px-3 py-1.5 text-sm text-ink-700"><CalendarDays size={14} className="text-ink-500" aria-hidden="true" /><span className="sr-only">To date</span><input aria-label="To date" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} className="min-w-0 bg-transparent text-sm outline-hidden" /></label>
        {(selectedStatuses.length > 0 || fromDate || toDate) && <button type="button" onClick={() => { setSelectedStatuses([]); setFromDate(""); setToDate(""); }} className="rr-focus-ring ml-auto text-xs font-semibold text-accent underline underline-offset-4">Clear filters</button>}
      </div>

      {filteredRuns.length === 0 ? <EmptyState title="No runs match these filters." description="Clear one or more filters to see the complete run history." /> : (
        <div className="rr-card overflow-hidden">
          <div className="rr-scrollbar overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead className="sticky top-0 z-[1] border-b border-line bg-surface-1"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Commit</th><th className="px-4 py-3 font-medium">Files</th><th className="px-4 py-3 font-medium">Lines</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">When</th><th className="px-4 py-3 text-right font-medium">Actions</th></tr></thead>
              <tbody className="divide-y divide-line">{filteredRuns.map((run) => { const busy = busyId === run.id; return <tr key={run.id} className="transition hover:bg-paper-0/65"><td className="px-4 py-3 font-mono text-sm font-medium">{shortSha(run.head_sha)}</td><td className="px-4 py-3 text-sm">{run.file_count}</td><td className="px-4 py-3 font-mono text-xs">+{run.total_changed_lines}</td><td className="px-4 py-3"><StatusPill label={run.status} /></td><td className="px-4 py-3 text-sm text-ink-500">{formatRelativeTime(run.created_at)}</td><td className="px-4 py-3"><div className="flex justify-end gap-1.5"><button type="button" onClick={() => onOpenRun(run)} className="rr-focus-ring inline-flex items-center gap-1 rounded-xs px-2 py-1 text-xs font-semibold text-accent transition hover:bg-accent/10"><Eye size={13} aria-hidden="true" />View</button>{run.status === "complete" && <button type="button" disabled={busy} onClick={() => void action(run, onRerun)} className="rr-focus-ring inline-flex items-center gap-1 rounded-xs px-2 py-1 text-xs font-semibold text-ink-500 transition hover:bg-paper-0 disabled:opacity-50"><RotateCcw size={13} aria-hidden="true" />{busy ? "Working…" : "Rerun"}</button>}{["queued", "running"].includes(run.status) && <button type="button" disabled={busy} onClick={() => void action(run, onCancel)} className="rr-focus-ring inline-flex items-center gap-1 rounded-xs px-2 py-1 text-xs font-semibold text-bad transition hover:bg-bad/10 disabled:opacity-50"><Square size={12} aria-hidden="true" />Cancel</button>}</div></td></tr>; })}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
