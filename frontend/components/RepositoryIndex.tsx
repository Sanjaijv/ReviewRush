"use client";

import { ExternalLink, GitBranch, LockKeyhole, RefreshCw } from "lucide-react";
import type { RepositorySummary, RunSummary } from "@/lib/types";
import { formatRelativeTime, statusTone } from "@/lib/formatters";
import { EmptyState, ErrorPanel, LoadingPanel, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

export function RepositoryIndex({
  installationName,
  repositories,
  latestRuns,
  loading,
  error,
  onRetry,
  onSelect,
}: {
  installationName: string;
  repositories: RepositorySummary[];
  latestRuns: Record<number, RunSummary | undefined>;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onSelect: (repository: RepositorySummary) => void;
}) {
  const activeRepositories = repositories.filter((repository) => repository.is_active);
  const disconnectedRepositories = repositories.filter((repository) => !repository.is_active);

  if (loading) return <LoadingPanel label="Loading repositories" />;
  if (error) return <ErrorPanel message={error} onRetry={onRetry} />;

  return (
    <div>
      <SectionHeader
        eyebrow="Workspace"
        title="Repositories"
        description={`${repositories.length} ${repositories.length === 1 ? "repository" : "repositories"} covered by ${installationName}.`}
        action={
          <a
            href="https://github.com/settings/installations"
            target="_blank"
            rel="noreferrer"
            className="rr-focus-ring inline-flex items-center gap-2 rounded-xs border border-line px-3 py-2 text-sm font-semibold text-ink-700 transition hover:border-accent hover:text-accent"
          >
            <RefreshCw size={15} aria-hidden="true" />
            Manage access
            <ExternalLink size={13} aria-hidden="true" />
          </a>
        }
      />

      {repositories.length === 0 ? (
        <EmptyState
          title="No repositories yet."
          description="Grant this app access from GitHub, then return here to review your first repository."
          action={
            <a href="https://github.com/settings/installations" target="_blank" rel="noreferrer" className="rr-focus-ring font-semibold text-accent underline underline-offset-4">
              Open GitHub installation settings <ExternalLink className="ml-1 inline" size={14} aria-hidden="true" />
            </a>
          }
        />
      ) : (
        <div className="space-y-9">
          <RepositoryGroup title="Active repositories" repositories={activeRepositories} latestRuns={latestRuns} onSelect={onSelect} />
          {disconnectedRepositories.length > 0 && (
            <RepositoryGroup title="Disconnected" description="These repositories no longer receive reviews." repositories={disconnectedRepositories} latestRuns={latestRuns} onSelect={onSelect} />
          )}
        </div>
      )}
    </div>
  );
}

function RepositoryGroup({
  title,
  description,
  repositories,
  latestRuns,
  onSelect,
}: {
  title: string;
  description?: string;
  repositories: RepositorySummary[];
  latestRuns: Record<number, RunSummary | undefined>;
  onSelect: (repository: RepositorySummary) => void;
}) {
  if (repositories.length === 0) return null;
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-3">
        <h3 className="font-display text-lg font-semibold tracking-[-0.02em]">{title}</h3>
        <span className="font-mono text-xs text-ink-500">{repositories.length.toString().padStart(2, "0")}</span>
        {description && <p className="text-sm text-ink-500">{description}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {repositories.map((repository) => (
          <RepositoryCard key={repository.id} repository={repository} latestRun={latestRuns[repository.id]} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}

function RepositoryCard({ repository, latestRun, onSelect }: { repository: RepositorySummary; latestRun?: RunSummary; onSelect: (repository: RepositorySummary) => void }) {
  const inactive = !repository.is_active;
  const policyLabel = inactive ? "inactive" : latestRun?.status === "oversized" ? "human_review" : latestRun?.status === "cancelled" ? "neutral" : latestRun ? "approved" : "no runs";
  return (
    <button
      type="button"
      disabled={inactive}
      onClick={() => onSelect(repository)}
      className={`rr-focus-ring rr-card group min-h-40 text-left transition ${inactive ? "cursor-not-allowed opacity-55" : "hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-[0_8px_24px_rgba(23,27,34,0.08)]"}`}
      aria-label={inactive ? `${repository.full_name}, inactive` : `Open ${repository.full_name}`}
    >
      <div className="flex h-full flex-col justify-between p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${inactive ? "bg-ink-500/35" : "bg-good"}`} aria-hidden="true" />
              <p className="truncate font-display text-lg font-semibold tracking-[-0.025em]">{repository.full_name}</p>
            </div>
            <p className="mt-2 flex items-center gap-1.5 font-mono text-xs text-ink-500">
              <GitBranch size={13} aria-hidden="true" />
              {repository.default_branch}
            </p>
          </div>
          <StatusPill label={policyLabel} tone={inactive ? "neutral" : statusTone(policyLabel)} />
        </div>
        <div className="mt-7 flex items-center justify-between gap-3 text-xs text-ink-500">
          <span>{inactive ? `disconnected ${formatRelativeTime(repository.disconnected_at)}` : latestRun ? `last run ${formatRelativeTime(latestRun.created_at)}` : "no runs yet"}</span>
          {!inactive && <LockKeyhole size={14} className="text-ink-500/60 transition group-hover:text-accent" aria-hidden="true" />}
        </div>
      </div>
    </button>
  );
}
