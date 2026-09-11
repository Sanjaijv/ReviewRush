import { AlertTriangle, Check, Info, X } from "lucide-react";
import type { ReactNode } from "react";
import type { StatusTone } from "@/lib/dashboard-types";
import { displayLabel, statusTone } from "@/lib/formatters";

const toneClasses: Record<StatusTone, string> = {
  good: "border-good/25 bg-good/10 text-good",
  warn: "border-warn/25 bg-warn/10 text-warn",
  bad: "border-bad/25 bg-bad/10 text-bad",
  neutral: "border-ink-500/20 bg-ink-500/10 text-ink-700",
  accent: "border-accent/30 bg-accent/10 text-accent",
};

export function StatusPill({
  label,
  tone,
  className = "",
}: {
  label: string;
  tone?: StatusTone;
  className?: string;
}) {
  const resolvedTone = tone ?? statusTone(label);
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded-xs border px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] ${toneClasses[resolvedTone]} ${className}`}
    >
      <span className="truncate">{label.replace(/_/g, " ")}</span>
    </span>
  );
}

export function MetricTile({
  label,
  value,
  hint,
  unavailable,
  loading,
}: {
  label: string;
  value?: string;
  hint?: string;
  unavailable?: boolean;
  loading?: boolean;
}) {
  return (
    <div className="rr-card min-h-32 p-4">
      <p className="rr-eyebrow">{label}</p>
      {loading ? (
        <div className="mt-4 h-8 w-24 animate-pulse rounded-xs bg-ink-500/10" />
      ) : (
        <p className={`mt-3 font-display text-3xl font-bold tracking-[-0.04em] ${unavailable ? "text-ink-500" : "text-ink-900"}`}>
          {value ?? "Unavailable"}
        </p>
      )}
      {hint && <p className="mt-2 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export function AlertBanner({
  tone = "warn",
  children,
  action,
  onDismiss,
}: {
  tone?: "info" | "warn" | "bad" | "good";
  children: ReactNode;
  action?: ReactNode;
  onDismiss?: () => void;
}) {
  const Icon = tone === "info" ? Info : tone === "good" ? Check : tone === "bad" ? X : AlertTriangle;
  const styles = toneClasses[tone === "info" ? "accent" : tone];
  return (
    <div className={`flex items-start gap-3 rounded-sm border px-4 py-3 text-sm ${styles}`} role="status">
      <Icon aria-hidden="true" size={16} strokeWidth={1.8} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
      {action}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss alert"
          className="rr-focus-ring shrink-0 rounded-xs p-0.5 opacity-70 transition hover:opacity-100"
        >
          <X aria-hidden="true" size={15} />
        </button>
      )}
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="rr-eyebrow mb-2">{eyebrow}</p>}
        <h2 className="font-display text-2xl font-bold tracking-[-0.03em] text-ink-900">{title}</h2>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rr-card border-dashed px-6 py-12 text-center">
      <p className="font-display text-lg font-semibold text-ink-900">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function LoadingPanel({ label = "Loading" }: { label?: string }) {
  return (
    <div className="rr-card flex min-h-40 items-center justify-center gap-3 p-8 text-sm text-ink-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent/25 border-t-accent" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rr-card border-bad/30 bg-bad/5 p-5" role="alert">
      <p className="font-display font-semibold text-bad">Something needs attention</p>
      <p className="mt-1 text-sm text-ink-700">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rr-focus-ring mt-4 rounded-xs border border-bad/30 px-3 py-1.5 text-sm font-semibold text-bad transition hover:bg-bad/10"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function TextButton({
  children,
  onClick,
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rr-focus-ring rounded-xs font-semibold text-accent underline decoration-accent/40 underline-offset-4 transition hover:decoration-accent disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}

export function formatStatusLabel(value: string) {
  return displayLabel(value);
}
