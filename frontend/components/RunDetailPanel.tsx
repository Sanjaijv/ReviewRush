"use client";

import { useState } from "react";
import { ArrowLeft, ChevronDown, ExternalLink, GitBranch, ShieldCheck } from "lucide-react";
import type { RunDetail, RunSummary } from "@/lib/types";
import { submitFindingFeedback } from "@/lib/dashboard-api";
import { formatRelativeTime, policyCopy, shortSha, statusTone } from "@/lib/formatters";
import { mapRunDetail } from "@/lib/dashboard-mappers";
import { AlertBanner, ErrorPanel, LoadingPanel, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

export function RunDetailPanel({ run, detail, loading, error, repositoryFullName, repositoryId, demo, onBack }: { run: RunSummary; detail: RunDetail | null; loading: boolean; error: string | null; repositoryFullName: string; repositoryId: number; demo: boolean; onBack: () => void }) {
  const [feedback, setFeedback] = useState<Record<number, "useful" | "incorrect">>({});
  if (loading) return <LoadingPanel label={`Loading ${shortSha(run.head_sha)}`} />;
  if (error) return <ErrorPanel message={error} onRetry={onBack} />;
  if (!detail) return <ErrorPanel message="This run did not return any detail." onRetry={onBack} />;
  const view = mapRunDetail(detail);

  async function vote(findingId: number, reaction: "useful" | "incorrect") {
    setFeedback((current) => ({ ...current, [findingId]: reaction }));
    if (!demo) {
      try { await submitFindingFeedback(repositoryId, findingId, reaction); } catch { setFeedback((current) => { const next = { ...current }; delete next[findingId]; return next; }); }
    }
  }

  return (
    <div>
      <button type="button" onClick={onBack} className="rr-focus-ring mb-6 inline-flex items-center gap-2 rounded-xs text-sm font-semibold text-ink-500 transition hover:text-accent"><ArrowLeft size={15} aria-hidden="true" />Back to runs</button>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div><p className="rr-eyebrow mb-2">Run detail / {formatRelativeTime(run.created_at)}</p><h2 className="font-display text-3xl font-bold tracking-[-0.04em]">{shortSha(run.head_sha)} <span className="font-normal text-ink-500">←</span> {shortSha(run.base_sha)}</h2><p className="mt-2 flex items-center gap-2 text-sm text-ink-500"><GitBranch size={14} aria-hidden="true" />{repositoryFullName} · {run.file_count} files · +{run.total_changed_lines} lines</p></div>
        <a href={`https://github.com/${repositoryFullName}/commit/${run.head_sha}`} target="_blank" rel="noreferrer" className="rr-focus-ring inline-flex items-center gap-2 rounded-xs border border-line px-3 py-2 text-sm font-semibold text-ink-700 transition hover:border-accent hover:text-accent">Open on GitHub <ExternalLink size={14} aria-hidden="true" /></a>
      </div>

      <div className="space-y-8">
        <section><SectionHeader eyebrow="Pipeline" title="Deterministic checks" /><div className="grid gap-3 md:grid-cols-3">{view.toolRuns.length ? view.toolRuns.map((tool) => <div key={tool.name} className="rr-card p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-display font-semibold">{tool.name}</p><p className="mt-1 font-mono text-[11px] text-ink-500">{tool.category} · {tool.duration}</p></div><StatusPill label={tool.conclusion} /></div><p className="mt-4 text-sm text-ink-500">{tool.summary}</p></div>) : <div className="rr-card p-5 text-sm text-ink-500">No deterministic checks were recorded.</div>}</div></section>

        <section><SectionHeader eyebrow="AI review" title="Findings" description={view.review ? `${view.review.findings.length} finding${view.review.findings.length === 1 ? "" : "s"} · ${view.review.model}` : "No AI review was recorded for this run."} />{view.review?.summary && <div className="mb-4 rounded-sm border border-line bg-surface-1 px-4 py-3 text-sm text-ink-700">{view.review.summary}</div>}{view.review?.findings.length ? <div className="space-y-3">{view.review.findings.map((finding) => <FindingCard key={finding.id} finding={finding} voted={feedback[finding.id]} onVote={(reaction) => void vote(finding.id, reaction)} />)}</div> : <div className="rr-card p-8 text-center text-sm text-ink-500">No findings on this run.</div>}</section>

        <PolicyDecisionPanel policy={view.policy} mergeAttempts={view.mergeAttempts} />
      </div>
    </div>
  );
}

function FindingCard({ finding, voted, onVote }: { finding: ReturnType<typeof mapRunDetail>["review"] extends infer T ? T extends { findings: Array<infer F> } ? F : never : never; voted?: "useful" | "incorrect"; onVote: (reaction: "useful" | "incorrect") => void }) {
  const [open, setOpen] = useState(false);
  return <article className={`rr-card overflow-hidden border-l-4 ${finding.severity === "critical" ? "border-l-risk-critical" : finding.severity === "high" ? "border-l-bad" : finding.severity === "medium" ? "border-l-warn" : "border-l-good"}`}>
    <button type="button" onClick={() => setOpen((current) => !current)} aria-expanded={open} className="rr-focus-ring flex w-full items-start gap-3 p-4 text-left"><span className="mt-0.5 shrink-0"><StatusPill label={finding.severity} tone={finding.severity === "critical" ? "bad" : statusTone(finding.severity)} /></span><div className="min-w-0 flex-1"><p className="font-mono text-xs text-ink-500">{finding.category}</p><p className="mt-1 font-display text-base font-semibold leading-snug">{finding.file}:{finding.startLine}{finding.endLine !== finding.startLine ? `–${finding.endLine}` : ""} <span className="font-normal text-ink-500">·</span> {finding.title}</p></div><ChevronDown size={17} className={`mt-1 shrink-0 text-ink-500 transition ${open ? "rotate-180" : ""}`} aria-hidden="true" /></button>
    {open && <div className="border-t border-line px-4 pb-4 pt-3"><div className="grid gap-4 lg:grid-cols-2"><div><p className="rr-eyebrow mb-1">Evidence</p><p className="text-sm leading-6 text-ink-700">{finding.evidence}</p></div><div><p className="rr-eyebrow mb-1">Recommendation</p><p className="text-sm leading-6 text-ink-700">{finding.recommendation}</p></div></div><div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3"><StatusPill label={finding.category === "security" ? "Fix available — apply from the PR checkbox" : "fix committed"} tone={finding.category === "security" ? "neutral" : "accent"} className="normal-case tracking-normal" />{voted ? <span className="text-xs font-semibold text-ink-500">Marked {voted === "useful" ? "helpful" : "incorrect"}</span> : <div className="flex items-center gap-2"><span className="text-xs text-ink-500">Was this finding useful?</span><button type="button" onClick={() => onVote("useful")} className="rr-focus-ring rounded-xs border border-line px-2 py-1 text-xs font-semibold text-ink-700 transition hover:border-good hover:text-good">Yes</button><button type="button" onClick={() => onVote("incorrect")} className="rr-focus-ring rounded-xs border border-line px-2 py-1 text-xs font-semibold text-ink-700 transition hover:border-bad hover:text-bad">No</button></div>}</div></div>}
  </article>;
}

function PolicyDecisionPanel({ policy, mergeAttempts }: { policy: ReturnType<typeof mapRunDetail>["policy"]; mergeAttempts: ReturnType<typeof mapRunDetail>["mergeAttempts"] }) {
  if (!policy) return <AlertBanner tone="info"><strong>Policy decision unavailable.</strong><span className="ml-1">This run has not reached a final decision.</span></AlertBanner>;
  const tone = policy.decision === "APPROVE" ? "good" : policy.decision === "BLOCK" ? "bad" : "accent";
  return <section><SectionHeader eyebrow="Policy engine" title="Policy decision" /><div className={`rr-card overflow-hidden border-l-4 ${tone === "good" ? "border-l-good" : tone === "bad" ? "border-l-bad" : "border-l-accent"}`}><div className="flex flex-wrap items-start justify-between gap-5 p-5"><div><div className="flex flex-wrap items-center gap-2"><StatusPill label={policy.decision} tone={tone} /><StatusPill label={`${policy.risk} risk`} tone={policy.risk === "critical" ? "bad" : statusTone(policy.risk)} /></div><p className="mt-3 font-display text-xl font-semibold">{policyCopy(policy.decision)}</p><p className="mt-1 font-mono text-[11px] text-ink-500">Policy {policy.version}</p></div><ShieldCheck className={tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-accent"} size={28} strokeWidth={1.5} aria-hidden="true" /></div>{policy.reasons.length > 0 && <div className="border-t border-line px-5 py-4"><p className="rr-eyebrow mb-2">Reasons</p><ul className="list-disc space-y-1 pl-5 text-sm text-ink-700">{policy.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}<details className="group border-t border-line"><summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-2 px-5 py-3 text-sm font-semibold text-ink-700 [&::-webkit-details-marker]:hidden"><ChevronDown size={15} className="transition group-open:rotate-180" aria-hidden="true" />Merge attempts <span className="ml-auto font-mono text-[11px] text-ink-500">{mergeAttempts.length}</span></summary>{mergeAttempts.length > 0 && <div className="border-t border-line px-5 py-3">{mergeAttempts.map((attempt) => <div key={attempt.created_at} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"><span className="font-mono text-xs">{attempt.outcome}</span><span className="text-ink-500">{formatRelativeTime(attempt.created_at)}</span></div>)}</div>}</details></div></section>;
}
