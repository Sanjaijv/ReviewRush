import type { StatusTone } from "@/lib/dashboard-types";

type UnknownRecord = Record<string, unknown>;

export function asRecord(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

export function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function asString(value: unknown, fallback = "Unavailable"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export function formatNumber(value: unknown): string {
  const number = asNumber(value);
  return number === null ? "Unavailable" : new Intl.NumberFormat("en-US").format(number);
}

export function formatPercent(value: unknown): string {
  const number = asNumber(value);
  if (number === null) return "Unavailable";
  const percent = number <= 1 ? number * 100 : number;
  return `${percent.toFixed(percent >= 10 ? 0 : 1)}%`;
}

export function formatDuration(value: unknown): string {
  const milliseconds = asNumber(value);
  if (milliseconds === null) return "Unavailable";
  if (milliseconds < 1000) return "<1s";
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function shortSha(value: string | null | undefined): string {
  return value && value.trim() ? value.slice(0, 7) : "—";
}

export function displayLabel(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function statusTone(status: string | null | undefined): StatusTone {
  switch (status?.toLowerCase()) {
    case "complete":
    case "completed":
    case "approved":
    case "approve":
    case "pass":
    case "passed":
    case "done":
    case "success":
    case "merged":
      return "good";
    case "oversized":
    case "human_review":
    case "warn":
    case "running":
    case "retrying":
      return "warn";
    case "block":
    case "blocked":
    case "failed":
    case "error":
    case "fail":
      return "bad";
    case "queued":
      return "accent";
    default:
      return "neutral";
  }
}

export function severityTone(severity: string | null | undefined): StatusTone {
  switch (severity?.toLowerCase()) {
    case "critical":
      return "bad";
    case "high":
      return "bad";
    case "medium":
      return "warn";
    case "low":
      return "good";
    default:
      return "neutral";
  }
}

export function policyCopy(decision: string | null | undefined): string {
  switch (decision?.toUpperCase()) {
    case "APPROVE":
      return "Nothing blocking — safe to merge.";
    case "HUMAN_REVIEW":
      return "Needs a person to look before merging.";
    case "BLOCK":
      return "Merge is blocked until this is resolved.";
    default:
      return "Policy decision is unavailable.";
  }
}

export function formatActor(actorType: string | null | undefined, actorLogin: string | null): string {
  if (actorLogin) return actorLogin;
  if (actorType === "system") return "system";
  return actorType || "unknown";
}
