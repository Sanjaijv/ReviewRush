"use client";

import { useEffect, useState } from "react";
import { ChevronDown, GitCompareArrows, Play, RotateCcw, ScrollText, TriangleAlert } from "lucide-react";
import { adminApi, adminApiJson, ApiError } from "@/lib/api";
import type { DatasetVersion, FinetuneJob } from "@/lib/types";
import { demoData } from "@/lib/demo-data";
import { formatPercent, formatRelativeTime } from "@/lib/formatters";
import { AlertBanner, EmptyState, ErrorPanel, LoadingPanel, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

const demo = process.env.NEXT_PUBLIC_REVIEWRUSH_DEMO === "true";
type ShadowResult = Record<string, unknown>;

export function FinetunePanel() {
  const [jobs, setJobs] = useState<FinetuneJob[]>(demo ? demoData.finetuneJobs : []);
  const [datasets, setDatasets] = useState<DatasetVersion[]>(demo ? [{ id: 6, version: 6, item_count: 4920, created_at: new Date().toISOString() }] : []);
  const [shadowResults, setShadowResults] = useState<ShadowResult[]>([]);
  const [loading, setLoading] = useState(!demo);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(demo ? String(demoData.finetuneJobs[0]?.id ?? "") : null);

  useEffect(() => {
    if (demo) return;
    Promise.all([
      adminApi<FinetuneJob[]>("/finetune/jobs"),
      adminApi<ShadowResult[]>("/finetune/shadow-results"),
      adminApi<DatasetVersion[]>("/eval/dataset/versions"),
    ])
      .then(([jobRows, shadows, datasetRows]) => {
        setJobs(jobRows.map((job) => ({ ...job, id: String(job.id), model: job.model ?? job.output_model ?? job.base_model ?? "Unavailable", created_at: job.created_at ?? new Date().toISOString() })));
        setShadowResults(shadows);
        setDatasets(datasetRows);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Fine-tune admin is unavailable."))
      .finally(() => setLoading(false));
  }, []);

  async function startJob() {
    const dataset = datasets[0];
    if (!dataset) {
      setError("Build a dataset version before starting a fine-tune job.");
      return;
    }
    setBusy("start");
    setError(null);
    try {
      if (demo) {
        const id = `job-demo-${jobs.length + 1}`;
        setJobs((current) => [{ id, model: "qwen2.5-coder:7b", method: "lora", status: "running", created_at: new Date().toISOString(), metrics: {}, log: [`dataset v${dataset.version} selected`, "training queued · demo fixture"] }, ...current]);
        setExpanded(id);
      } else {
        const created = await adminApiJson<FinetuneJob>("/finetune/jobs", "POST", { dataset_version_id: dataset.id, notes: "Started from dashboard" });
        const job = { ...created, id: String(created.id), model: created.model ?? created.output_model ?? created.base_model ?? "Unavailable" };
        setJobs((current) => [job, ...current]);
        setExpanded(String(job.id));
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not start fine-tune job.");
    } finally {
      setBusy(null);
    }
  }

  async function rollback() {
    if (!window.confirm("Rollback the active model to the previous promotion?")) return;
    setBusy("rollback");
    try {
      if (!demo) await adminApiJson("/finetune/rollback", "POST", { notes: "Rollback requested from dashboard" });
      else setError("Demo mode: rollback is visual only.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not rollback the active model.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <LoadingPanel label="Loading fine-tune admin" />;
  if (error && !demo) return <ErrorPanel message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <SectionHeader eyebrow="Admin / Custom models" title="Fine-tune" description="Train, compare, shadow-evaluate, and roll back custom review models." action={<StatusPill label="token-gated utility" tone="neutral" />} />
      {error && <AlertBanner tone="warn">{error}</AlertBanner>}
      <section>
        <SectionHeader eyebrow="Jobs" title="Fine-tune jobs" action={<button type="button" disabled={busy === "start" || datasets.length === 0} onClick={() => void startJob()} className="rr-focus-ring inline-flex items-center gap-2 rounded-xs border border-line px-3 py-2 text-sm font-semibold text-ink-700 transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"><Play size={14} aria-hidden="true" />{busy === "start" ? "Starting…" : datasets.length === 0 ? "No dataset" : "Start job"}</button>} />
        {jobs.length ? <div className="space-y-2">{jobs.map((job) => {
          const jobId = String(job.id);
          const isOpen = expanded === jobId;
          return <article key={jobId} className="rr-card overflow-hidden"><button type="button" onClick={() => setExpanded(isOpen ? null : jobId)} aria-expanded={isOpen} className="rr-focus-ring flex w-full items-center gap-3 p-4 text-left"><span className="font-mono text-xs text-ink-500">{jobId}</span><span className="min-w-0 flex-1 truncate font-display font-semibold">{job.model ?? "Unavailable"} <span className="font-normal text-ink-500">· {job.method}</span></span><StatusPill label={job.status} /><span className="text-xs text-ink-500">{formatRelativeTime(job.created_at)}</span><ChevronDown size={16} className={`text-ink-500 transition ${isOpen ? "rotate-180" : ""}`} aria-hidden="true" /></button>{isOpen && <div className="grid gap-5 border-t border-line p-4 lg:grid-cols-2"><div><div className="flex items-center gap-2"><ScrollText size={15} className="text-accent" aria-hidden="true" /><p className="font-semibold">Training log</p></div><pre className="rr-scrollbar mt-3 max-h-48 overflow-auto rounded-xs bg-ink-900 p-3 font-mono text-[11px] leading-5 text-paper-0">{(job.log ?? ["No training log is available."]).join("\n")}</pre></div><div><p className="font-semibold">Resulting metrics</p><div className="mt-3 grid grid-cols-2 gap-2">{Object.entries(job.metrics ?? {}).map(([key, value]) => <div key={key} className="rounded-xs bg-paper-0 p-3"><p className="font-mono text-[11px] text-ink-500">{key}</p><p className="mt-1 font-display text-xl font-bold">{typeof value === "number" ? formatPercent(value) : String(value)}</p></div>)}{!Object.keys(job.metrics ?? {}).length && <p className="text-sm text-ink-500">Metrics are unavailable for this job.</p>}</div><div className="mt-4 flex flex-wrap gap-2"><button type="button" className="rr-focus-ring inline-flex items-center gap-1.5 rounded-xs border border-line px-3 py-2 text-xs font-semibold text-ink-700 transition hover:border-accent hover:text-accent"><GitCompareArrows size={14} aria-hidden="true" />Compare baseline</button>{job.status === "complete" && <button type="button" disabled={busy === "rollback"} onClick={() => void rollback()} className="rr-focus-ring inline-flex items-center gap-1.5 rounded-xs border border-bad/30 px-3 py-2 text-xs font-semibold text-bad transition hover:bg-bad/10 disabled:opacity-50"><RotateCcw size={14} aria-hidden="true" />{busy === "rollback" ? "Rolling back…" : "Rollback"}</button>}</div></div></div>}</article>;
        })}</div> : <EmptyState title="No fine-tune jobs yet." description="Completed training jobs will appear here with their logs and resulting metrics." />}
      </section>
      <section className="mt-10"><SectionHeader eyebrow="Shadow deployment" title="Shadow-eval results" description="Candidate model scores against live traffic without changing the active promotion." /><div className="rr-card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left"><thead className="border-b border-line bg-surface-1"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Candidate</th><th className="px-4 py-3 font-medium">Live issues</th><th className="px-4 py-3 font-medium">Candidate issues</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">When</th></tr></thead><tbody className="divide-y divide-line">{shadowResults.length ? shadowResults.map((result, index) => <tr key={String(result.id ?? index)}><td className="px-4 py-3 font-mono text-xs">{String(result.candidate_model ?? "Unavailable")}</td><td className="px-4 py-3 text-sm">{String(result.live_issue_count ?? "—")}</td><td className="px-4 py-3 text-sm">{String(result.candidate_issue_count ?? "—")}</td><td className="px-4 py-3"><StatusPill label={String(result.status ?? "unknown")} /></td><td className="px-4 py-3 text-sm text-ink-500">{formatRelativeTime(typeof result.created_at === "string" ? result.created_at : null)}</td></tr>) : <tr><td colSpan={5} className="px-4 py-12 text-center text-sm text-ink-500"><TriangleAlert className="mx-auto mb-2 text-ink-500" size={18} aria-hidden="true" />No shadow evaluations recorded.</td></tr>}</tbody></table></div></div></section>
    </div>
  );
}
