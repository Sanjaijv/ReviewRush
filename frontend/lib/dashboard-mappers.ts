import type {
  FindingPayload,
  PolicyDecisionPayload,
  RepositoryMetrics,
  RunDetail,
  ToolRunPayload,
} from "@/lib/types";
import type { RepositoryMetric } from "@/lib/dashboard-types";
import { asNumber, asRecord, asString, formatDuration, formatNumber, formatPercent } from "@/lib/formatters";

export function mapMetricModels(metrics: RepositoryMetrics): RepositoryMetric[] {
  const decisions = asRecord(metrics.policy_decisions_by_outcome);
  const total = asNumber(metrics.total_reviews);
  const approved = asNumber(decisions.APPROVE) ?? 0;
  const approveRate = total && total > 0 ? approved / total : null;
  const autoFixCount =
    asNumber(asRecord(metrics.merge_attempts_by_outcome).MERGED) ??
    asNumber(asRecord(metrics.merge_attempts_by_outcome).merged) ??
    asNumber(metrics.auto_fixes_shipped);

  return [
    {
      label: "Runs (30d)",
      value: formatNumber(metrics.total_reviews),
      hint: "review runs recorded",
    },
    {
      label: "Approve rate",
      value: formatPercent(approveRate),
      hint: "policy decisions approved",
      unavailable: approveRate === null,
    },
    {
      label: "Auto-fixes shipped",
      value: formatNumber(autoFixCount),
      hint: "merged fix attempts",
      unavailable: autoFixCount === null,
    },
    {
      label: "Median review time",
      value: formatDuration(metrics.avg_review_time_ms),
      hint: "average pipeline latency",
      unavailable: asNumber(metrics.avg_review_time_ms) === null,
    },
  ];
}

export function mapToolRun(tool: ToolRunPayload) {
  const conclusion = asString(tool.conclusion, "unknown").toLowerCase();
  return {
    name: asString(tool.check_name),
    category: asString(tool.category, "check"),
    conclusion,
    required: Boolean(tool.required),
    duration: formatDuration(tool.duration_ms),
    summary: asString(tool.summary, "No summary provided."),
  };
}

export function mapFinding(finding: FindingPayload, index: number) {
  return {
    id: finding.id ?? index + 1,
    file: asString(finding.file),
    startLine: asNumber(finding.start_line) ?? 0,
    endLine: asNumber(finding.end_line) ?? asNumber(finding.start_line) ?? 0,
    severity: asString(finding.severity, "unknown").toLowerCase(),
    category: asString(finding.category, "uncategorized"),
    title: asString(finding.title),
    evidence: asString(finding.evidence, "Evidence was not included in this response."),
    recommendation: asString(
      finding.recommendation,
      "No recommendation was included in this response.",
    ),
  };
}

export function mapRunDetail(detail: RunDetail) {
  const aiReview = detail.ai_review;
  const policy = detail.policy_decision as PolicyDecisionPayload | null;
  return {
    run: detail.run,
    changedFiles: Array.isArray(detail.changed_files) ? detail.changed_files : [],
    toolRuns: Array.isArray(detail.tool_runs) ? detail.tool_runs.map(mapToolRun) : [],
    review: aiReview
      ? {
          status: asString(aiReview.status),
          decision: asString(aiReview.decision, "Unavailable"),
          risk: asString(aiReview.risk, "Unavailable").toLowerCase(),
          confidence: aiReview.confidence === null ? null : asNumber(aiReview.confidence),
          summary: asString(aiReview.summary, "No AI summary provided."),
          provider: asString(aiReview.provider),
          model: asString(aiReview.model),
          findings: Array.isArray(aiReview.findings)
            ? aiReview.findings.map(mapFinding)
            : [],
        }
      : null,
    policy: policy
      ? {
          decision: asString(policy.decision),
          risk: asString(policy.risk, "unknown").toLowerCase(),
          reasons: Array.isArray(policy.reasons)
            ? policy.reasons.filter((reason): reason is string => typeof reason === "string")
            : [],
          version: asString(policy.policy_version),
        }
      : null,
    mergeAttempts: Array.isArray(detail.merge_attempts) ? detail.merge_attempts : [],
  };
}
