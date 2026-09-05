"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RepositoryDetail } from "@/components/RepositoryDetail";
import type { Installation, RepositorySummary } from "@/lib/types";

export function Dashboard() {
  const [installations, setInstallations] = useState<Installation[] | null>(null);
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repositories, setRepositories] = useState<RepositorySummary[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<RepositorySummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Tracks which installation the current `repositories`/`selectedRepo`
  // state belongs to, so switching installations can clear the stale
  // selection during render (React's documented pattern for "adjusting
  // state when a prop changes") rather than in an effect.
  const [repositoriesForInstallation, setRepositoriesForInstallation] = useState<number | null>(
    null,
  );
  if (installationId !== null && installationId !== repositoriesForInstallation) {
    setRepositoriesForInstallation(installationId);
    setSelectedRepo(null);
  }

  useEffect(() => {
    api<Installation[]>("/installations")
      .then((rows) => {
        setInstallations(rows);
        if (rows.length > 0) setInstallationId(rows[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "failed to load installations"));
  }, []);

  useEffect(() => {
    if (installationId === null) return;
    api<RepositorySummary[]>(`/installations/${installationId}/repositories`)
      .then(setRepositories)
      .catch((err) => setError(err instanceof Error ? err.message : "failed to load repositories"));
  }, [installationId]);

  if (error) {
    return <p className="p-5 text-red-600 text-sm">{error}</p>;
  }

  if (installations === null) {
    return <p className="p-5 text-neutral-500 text-sm">Loading…</p>;
  }

  if (installations.length === 0) {
    return (
      <p className="p-5 text-sm text-neutral-500">
        No GitHub App installations are visible to your account yet.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-[220px_1fr] gap-6 p-5">
      <nav className="space-y-3">
        <h3 className="font-medium text-sm">Installations</h3>
        <select
          value={installationId ?? ""}
          onChange={(e) => setInstallationId(Number(e.target.value))}
          className="w-full border border-neutral-200 rounded px-2 py-1 text-sm"
        >
          {installations.map((i) => (
            <option key={i.id} value={i.id}>
              {i.account_login}
            </option>
          ))}
        </select>
        <div className="space-y-1">
          {repositories.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelectedRepo(r)}
              className={`block w-full text-left text-sm px-2 py-1 rounded ${
                selectedRepo?.id === r.id ? "bg-neutral-900 text-white" : "hover:bg-neutral-100"
              }`}
            >
              {r.full_name}
              {!r.is_active && " (disconnected)"}
            </button>
          ))}
        </div>
      </nav>
      <section>
        {selectedRepo ? (
          <RepositoryDetail
            key={selectedRepo.id}
            repositoryId={selectedRepo.id}
            fullName={selectedRepo.full_name}
          />
        ) : (
          <p className="text-sm text-neutral-500">Select a repository.</p>
        )}
      </section>
    </div>
  );
}
