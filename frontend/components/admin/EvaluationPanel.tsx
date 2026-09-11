"use client";

import { useEffect, useState } from "react";
import { Database, Play, Rocket, ShieldCheck } from "lucide-react";
import { adminApi, adminApiJson, ApiError } from "@/lib/api";
import type { DatasetVersion, EvaluationRun, Promotion } from "@/lib/types";
import { demoData } from "@/lib/demo-data";
import { formatPercent, formatRelativeTime } from "@/lib/formatters";
import { AlertBanner, EmptyState, ErrorPanel, LoadingPanel, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

const demo = process.env.NEXT_PUBLIC_REVIEWRUSH_DEMO === "true";

export function EvaluationPanel() {
  const [datasets, setDatasets] = useState<DatasetVersion[]>(demo ? [{ id: 6, version: 6, item_count: 4920, created_at: new Date().toISOString() }] : []);
  const [runs, setRuns] = useState<EvaluationRun[]>(demo ? [{ id: 14, run_type: "dataset", dataset_version_id: 6, provider: "openai", model: "gpt-5-coder", prompt_version: "prompt-22", policy_version: "2026.08", status: "done", case_count: 4920, metrics: { precision: 0.83, recall: 0.71 }, error_message: null, created_at: new Date().toISOString() }] : []);
  const [promotion, setPromotion] = useState<Promotion | null>(demo ? demoData.promotion : null);
  const [loading, setLoading] = useState(!demo);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (demo) return;
    Promise.all([adminApi<DatasetVersion[]>("/eval/dataset/versions"), adminApi<EvaluationRun[]>("/eval/runs"), adminApi<Promotion | null>("/eval/promotions/active")])
      .then(([datasetRows, runRows, active]) => { setDatasets(datasetRows); setRuns(runRows); setPromotion(active); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Evaluation admin is unavailable."))
      .finally(() => setLoading(false));
  }, []);

  async function buildDataset() {
    setBusy("dataset");
    try {
      if (!demo) {
        const dataset = await adminApiJson<DatasetVersion>("/eval/dataset/build", "POST", { notes: "Built from dashboard" });
        setDatasets((current) => [dataset, ...current]);
      }
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Could not build dataset."); } finally { setBusy(null); }
  }

  async function runBenchmark(datasetId: number) {
    setBusy(`run-${datasetId}`);
    try {
      if (!demo) {
        const run = await adminApi<EvaluationRun>(`/eval/dataset/${datasetId}/run`, { method: "POST" });
        setRuns((current) => [run, ...current]);
      }
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Could not start evaluation."); } finally { setBusy(null); }
  }

  async function promote(run: EvaluationRun) {
    setBusy(`promote-${run.id}`);
    try {
      if (!demo) {
        const active = await adminApiJson<Promotion>("/eval/promotions", "POST", { eval_run_id: run.id });
        setPromotion(active);
      } else {
        setPromotion({ id: 9, eval_run_id: run.id, provider: run.provider, model: run.model, prompt_version: run.prompt_version, policy_version: run.policy_version, created_at: new Date().toISOString() });
      }
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Could not promote this run."); } finally { setBusy(null); }
  }

  if (loading) return <LoadingPanel label="Loading evaluation admin" />;
  if (error && !demo) return <ErrorPanel message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <SectionHeader eyebrow="Admin / Model quality" title="Evaluation" description="Benchmark the AI reviewer against labeled examples. Long-running actions stay visible as rows." action={<StatusPill label="token-gated utility" tone="neutral" />} />
      {error && <AlertBanner tone="bad">{error}</AlertBanner>}
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rr-card p-5"><div className="flex items-start justify-between gap-3"><div><p className="rr-eyebrow">Dataset versions</p><h3 className="mt-1 font-display text-lg font-semibold">Labeled benchmark data</h3></div><button type="button" disabled={busy === "dataset"} onClick={() => void buildDataset()} className="rr-focus-ring inline-flex items-center gap-2 rounded-xs border border-line px-3 py-2 text-sm font-semibold text-ink-700 transition hover:border-accent hover:text-accent disabled:opacity-50"><Database size={14} aria-hidden="true" />{busy === "dataset" ? "Building…" : "Build new"}</button></div><div className="mt-5 space-y-2">{datasets.length ? datasets.map((dataset) => <div key={dataset.id} className="flex items-center gap-3 rounded-xs bg-paper-0 px-3 py-3"><span className="font-mono text-xs font-semibold">v{dataset.version}</span><span className="text-sm text-ink-700">{dataset.item_count.toLocaleString()} labeled cases</span><span className="ml-auto text-xs text-ink-500">{formatRelativeTime(dataset.created_at)}</span><button type="button" disabled={busy === `run-${dataset.id}`} onClick={() => void runBenchmark(dataset.id)} className="rr-focus-ring rounded-xs p-1.5 text-accent transition hover:bg-accent/10" aria-label={`Run benchmark for dataset version ${dataset.version}`}><Play size={14} aria-hidden="true" /></button></div>) : <p className="text-sm text-ink-500">No dataset versions yet.</p>}</div></section>
        <section className="rr-card p-5"><p className="rr-eyebrow">Active promotion</p><h3 className="mt-1 font-display text-lg font-semibold">Model and prompt in production</h3>{promotion ? <div className="mt-5 rounded-xs border border-good/25 bg-good/5 p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-mono text-sm">{promotion.model}</p><p className="mt-1 text-sm text-ink-500">{promotion.provider} · {promotion.prompt_version}</p></div><ShieldCheck size={19} className="text-good" aria-hidden="true" /></div><p className="mt-4 text-xs text-ink-500">Promoted {formatRelativeTime(promotion.created_at)}</p></div> : <EmptyState title="No active promotion." description="A successful evaluation run can be promoted from the table below." />}</section>
      </div>
      <section className="mt-8"><SectionHeader eyebrow="Benchmarks" title="Evaluation runs" /><div className="rr-card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left"><thead className="border-b border-line bg-surface-1"><tr className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-500"><th className="px-4 py-3 font-medium">Run</th><th className="px-4 py-3 font-medium">Dataset</th><th className="px-4 py-3 font-medium">Precision</th><th className="px-4 py-3 font-medium">Recall</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 text-right" /></tr></thead><tbody className="divide-y divide-line">{runs.length ? runs.map((run) => <tr key={run.id} className="hover:bg-paper-0/65"><td className="px-4 py-3 font-mono text-sm">eval-run-{String(run.id).padStart(3, "0")}</td><td className="px-4 py-3 text-sm">v{run.dataset_version_id ?? "—"}</td><td className="px-4 py-3 font-mono text-sm">{formatPercent(run.metrics.precision)}</td><td className="px-4 py-3 font-mono text-sm">{formatPercent(run.metrics.recall)}</td><td className="px-4 py-3"><StatusPill label={run.status} /></td><td className="px-4 py-3 text-right"><button type="button" disabled={busy === `promote-${run.id}`} onClick={() => void promote(run)} className="rr-focus-ring inline-flex items-center gap-1.5 rounded-xs bg-accent px-3 py-1.5 text-xs font-semibold text-paper-0 transition hover:bg-accent/85 disabled:opacity-50"><Rocket size={13} aria-hidden="true" />{busy === `promote-${run.id}` ? "Promoting…" : "Promote"}</button></td></tr>) : <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-ink-500">No evaluation runs yet.</td></tr>}</tbody></table></div></div></section>
    </div>
  );
}
