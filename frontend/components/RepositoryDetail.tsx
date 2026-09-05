"use client";

import { useEffect, useState } from "react";
import { api, apiJson, ApiError } from "@/lib/api";
import { JsonBlock } from "@/components/JsonBlock";
import type {
  AuditEvent,
  RepoConfigResponse,
  RepositoryMetrics,
  RunDetail,
  RunSummary,
  TaskFailure,
} from "@/lib/types";

interface Props {
  repositoryId: number;
  fullName: string;
}

interface LoadedState {
  runs: RunSummary[];
  metrics: RepositoryMetrics;
  auditLog: AuditEvent[];
  config: RepoConfigResponse;
  taskFailures: TaskFailure[];
}

// A plain (non-hook) fetch, kept outside the component so both the
// mount-time effect and the post-action reload calls share one
// implementation without going through a memoized callback - the extra
// function-call indirection of useCallback obscures from the effect-linter
// that the resulting setState calls happen inside a .then(), not
// synchronously in the effect body.
async function fetchRepositoryData(repositoryId: number): Promise<LoadedState> {
  const [runs, metrics, auditLog, config, taskFailures] = await Promise.all([
    api<RunSummary[]>(`/repositories/${repositoryId}/runs`),
    api<RepositoryMetrics>(`/repositories/${repositoryId}/metrics`),
    api<AuditEvent[]>(`/repositories/${repositoryId}/audit-log`),
    api<RepoConfigResponse>(`/repositories/${repositoryId}/config`),
    api<TaskFailure[]>(`/repositories/${repositoryId}/task-failures`),
  ]);
  return { runs, metrics, auditLog, config, taskFailures };
}

export function RepositoryDetail({ repositoryId, fullName }: Props) {
  const [data, setData] = useState<LoadedState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [configDraft, setConfigDraft] = useState("");
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  function applyLoaded(loaded: LoadedState) {
    setData(loaded);
    setConfigDraft(JSON.stringify(loaded.config.config ?? { version: 1 }, null, 2));
  }

  function load() {
    setError(null);
    return fetchRepositoryData(repositoryId)
      .then(applyLoaded)
      .catch((err) => setError(err instanceof Error ? err.message : "failed to load repository"));
  }

  // No explicit reset-on-repositoryId-change needed here: the parent
  // remounts this component with `key={repositoryId}` (see Dashboard.tsx),
  // so every piece of state above already starts fresh per repository.
  useEffect(() => {
    // No setError(null) needed here: this component remounts fresh (see
    // the `key={repositoryId}` note above), so `error` already starts null.
    fetchRepositoryData(repositoryId)
      .then(applyLoaded)
      .catch((err) => setError(err instanceof Error ? err.message : "failed to load repository"));
  }, [repositoryId]);

  useEffect(() => {
    if (selectedRunId === null) return;
    let cancelled = false;
    api<RunDetail>(`/repositories/${repositoryId}/runs/${selectedRunId}`)
      .then((detail) => {
        if (!cancelled) setRunDetail(detail);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load run");
      });
    return () => {
      cancelled = true;
    };
  }, [repositoryId, selectedRunId]);

  async function runAction(runId: number, action: "rerun" | "cancel") {
    try {
      await api(`/repositories/${repositoryId}/runs/${runId}/${action}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : `failed to ${action} run`);
    }
  }

  async function resolveTaskFailure(id: number) {
    try {
      await api(`/repositories/${repositoryId}/task-failures/${id}/resolve`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to resolve task failure");
    }
  }

  async function disconnectRepository() {
    if (!window.confirm("Disconnect this repository from ReviewRush?")) return;
    try {
      await apiJson(`/repositories/${repositoryId}/disconnect`, "POST", {});
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to disconnect repository");
    }
  }

  async function saveConfig() {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(configDraft);
    } catch {
      setConfigError("invalid JSON");
      return;
    }
    setConfigSaving(true);
    setConfigError(null);
    try {
      await apiJson(`/repositories/${repositoryId}/config`, "PUT", { config: parsed });
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        setConfigError(`save failed (${err.status}): ${err.message}`);
      } else {
        setConfigError(err instanceof Error ? err.message : "save failed");
      }
    } finally {
      setConfigSaving(false);
    }
  }

  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-red-600 text-sm">{error}</p>
        <button onClick={() => void load()} className="text-sm underline">
          retry
        </button>
      </div>
    );
  }

  if (!data) {
    return <p className="text-neutral-500 text-sm">Loading…</p>;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{fullName}</h2>
        <button
          onClick={() => void disconnectRepository()}
          className="text-sm text-red-600 border border-red-200 rounded px-3 py-1 hover:bg-red-50"
        >
          Disconnect repository
        </button>
      </div>

      <Section title="Metrics">
        <JsonBlock value={data.metrics} />
      </Section>

      <Section title="Review runs">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-neutral-200 text-left">
              <th className="py-1 pr-3">SHA</th>
              <th className="py-1 pr-3">Status</th>
              <th className="py-1 pr-3">Files</th>
              <th className="py-1 pr-3">When</th>
              <th className="py-1"></th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id} className="border-b border-neutral-100">
                <td className="py-1 pr-3 font-mono">{r.head_sha.slice(0, 7)}</td>
                <td className="py-1 pr-3">
                  <span className="inline-block px-2 py-0.5 rounded-full bg-neutral-100 text-xs">
                    {r.status}
                  </span>
                </td>
                <td className="py-1 pr-3">{r.file_count}</td>
                <td className="py-1 pr-3">{new Date(r.created_at).toLocaleString()}</td>
                <td className="py-1 space-x-2 whitespace-nowrap">
                  <button
                    onClick={() => setSelectedRunId(r.id)}
                    className="text-blue-600 hover:underline"
                  >
                    view
                  </button>
                  <button
                    onClick={() => void runAction(r.id, "rerun")}
                    className="text-blue-600 hover:underline"
                  >
                    rerun
                  </button>
                  <button
                    onClick={() => void runAction(r.id, "cancel")}
                    className="text-blue-600 hover:underline"
                  >
                    cancel
                  </button>
                </td>
              </tr>
            ))}
            {data.runs.length === 0 && (
              <tr>
                <td colSpan={5} className="py-3 text-neutral-500">
                  No runs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {runDetail && (
          <div className="mt-3">
            <h4 className="font-medium text-sm mb-1">Run detail</h4>
            <JsonBlock value={runDetail} />
          </div>
        )}
      </Section>

      <Section title="Configuration override">
        <p className="text-sm text-neutral-500 mb-2">
          Source: {data.config.source}
          {data.config.version ? ` (v${data.config.version})` : ""}
        </p>
        <textarea
          value={configDraft}
          onChange={(e) => setConfigDraft(e.target.value)}
          className="w-full h-64 font-mono text-xs border border-neutral-200 rounded p-2"
        />
        {configError && <p className="text-red-600 text-sm mt-1">{configError}</p>}
        <button
          onClick={() => void saveConfig()}
          disabled={configSaving}
          className="mt-2 text-sm bg-neutral-900 text-white rounded px-3 py-1.5 disabled:opacity-50"
        >
          {configSaving ? "Saving…" : "Save new version"}
        </button>
      </Section>

      <Section title="Unresolved task failures">
        {data.taskFailures.length === 0 ? (
          <p className="text-sm text-neutral-500">None.</p>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-neutral-200 text-left">
                <th className="py-1 pr-3">Task</th>
                <th className="py-1 pr-3">Error</th>
                <th className="py-1 pr-3">Retries</th>
                <th className="py-1 pr-3">When</th>
                <th className="py-1"></th>
              </tr>
            </thead>
            <tbody>
              {data.taskFailures.map((f) => (
                <tr key={f.id} className="border-b border-neutral-100">
                  <td className="py-1 pr-3">{f.task_name}</td>
                  <td className="py-1 pr-3">
                    {f.exception_type}: {f.exception_message.slice(0, 120)}
                  </td>
                  <td className="py-1 pr-3">{f.retry_count}</td>
                  <td className="py-1 pr-3">{new Date(f.created_at).toLocaleString()}</td>
                  <td className="py-1">
                    <button
                      onClick={() => void resolveTaskFailure(f.id)}
                      className="text-blue-600 hover:underline"
                    >
                      resolve
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Audit log">
        <JsonBlock value={data.auditLog} />
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-medium mb-2">{title}</h3>
      {children}
    </section>
  );
}
