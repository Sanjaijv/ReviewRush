"use client";

import { useMemo, useState } from "react";
import { Check, Clock3, Copy, FileCode2, RotateCcw } from "lucide-react";
import { parse, stringify } from "yaml";
import type { RepoConfigResponse, RepoConfigVersion } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { saveRepositoryConfig } from "@/lib/dashboard-api";
import { formatRelativeTime } from "@/lib/formatters";
import { AlertBanner, SectionHeader, StatusPill, TextButton } from "@/components/dashboard/primitives";
import { CodeEditor } from "@/components/CodeEditor";

export function ConfigPanel({ repositoryId, config, versions, demo, onSaved }: { repositoryId: number; config: RepoConfigResponse; versions: RepoConfigVersion[]; demo: boolean; onSaved: () => void }) {
  const initial = useMemo(() => stringify(config.config ?? { review: { enabled: true } }), [config.config]);
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [restoreVersion, setRestoreVersion] = useState<number | null>(null);

  const parsed = useMemo(() => {
    try {
      const result = parse(draft);
      if (result === null || typeof result !== "object" || Array.isArray(result)) return { value: null, error: "Configuration must be a YAML object." };
      return { value: result as Record<string, unknown>, error: null };
    } catch (error) {
      const message = error instanceof Error ? error.message.split("\n")[0] : "Invalid YAML.";
      return { value: null, error: message };
    }
  }, [draft]);

  async function save() {
    if (!parsed.value || parsed.error) return;
    setSaving(true); setSaveMessage(null);
    try {
      if (!demo) await saveRepositoryConfig(repositoryId, parsed.value);
      setSaveMessage("Saved as a new configuration version.");
      onSaved();
    } catch (error) {
      setSaveMessage(error instanceof ApiError ? `Save failed (${error.status}): ${error.message}` : "Save failed. Try again.");
    } finally { setSaving(false); }
  }

  function restore(version: RepoConfigVersion) {
    setDraft(stringify(version.config));
    setRestoreVersion(version.version);
    setSaveMessage(`Version ${version.version} copied into the editor as a draft.`);
  }

  return (
    <div>
      <SectionHeader eyebrow="Repository policy" title="Config" description="A dashboard override layered over the .reviewrush.yml committed to this repository." action={<StatusPill label={config.source === "dashboard_override" ? "dashboard override" : "repository file"} tone={config.source === "dashboard_override" ? "accent" : "neutral"} />} />
      {config.source === "repository_file" && <AlertBanner tone="info"><strong>Repository file is active.</strong><span className="ml-1">Dashboard edits create an override version; the repository file remains the source until that version is saved.</span></AlertBanner>}
      {saveMessage && <div className="mt-4"><AlertBanner tone={saveMessage.startsWith("Save failed") ? "bad" : "good"}>{saveMessage}</AlertBanner></div>}
      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><FileCode2 size={16} className="text-accent" aria-hidden="true" /><p className="font-display font-semibold">.reviewrush.yml</p><span className="font-mono text-[11px] text-ink-500">{restoreVersion ? `draft from v${restoreVersion}` : "editable"}</span></div><button type="button" onClick={() => setDraft(initial)} className="rr-focus-ring inline-flex items-center gap-1.5 text-xs font-semibold text-ink-500 transition hover:text-accent"><RotateCcw size={13} aria-hidden="true" />Reset draft</button></div>
          <CodeEditor value={draft} onChange={setDraft} error={parsed.error} />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-ink-500">Save creates a new version. Older versions remain append-only.</p><button type="button" disabled={Boolean(parsed.error) || saving} onClick={() => void save()} className="rr-focus-ring inline-flex items-center gap-2 rounded-xs bg-accent px-4 py-2 text-sm font-semibold text-paper-0 transition hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-45"><Check size={15} aria-hidden="true" />{saving ? "Saving…" : "Save new version"}</button></div>
        </section>
        <aside className="xl:border-l xl:border-line xl:pl-5"><div className="mb-3 flex items-center justify-between"><p className="font-display font-semibold">Version history</p><span className="font-mono text-xs text-ink-500">{versions.length} versions</span></div>{versions.length === 0 ? <p className="rounded-sm border border-dashed border-line px-4 py-5 text-sm text-ink-500">No dashboard versions yet.</p> : <div className="space-y-2">{versions.map((version) => <details key={version.version} className="group rounded-sm border border-line bg-surface-1"><summary className="rr-focus-ring flex cursor-pointer list-none items-start gap-3 p-3 [&::-webkit-details-marker]:hidden"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xs bg-paper-0 font-mono text-[11px] font-semibold">v{version.version}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{version.actor_login}</span><span className="mt-0.5 flex items-center gap-1 text-xs text-ink-500"><Clock3 size={12} aria-hidden="true" />{formatRelativeTime(version.created_at)}</span></span><span className="font-mono text-xs text-ink-500">⌄</span></summary><div className="border-t border-line p-3"><pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xs bg-ink-900 p-3 font-mono text-[11px] leading-5 text-paper-0 rr-scrollbar">{stringify(version.config)}</pre><div className="mt-3 flex gap-2"><TextButton onClick={() => restore(version)} className="no-underline">Restore to draft</TextButton><button type="button" onClick={() => void navigator.clipboard?.writeText(stringify(version.config))} className="rr-focus-ring inline-flex items-center gap-1 text-xs font-semibold text-ink-500 hover:text-accent"><Copy size={13} aria-hidden="true" />Copy</button></div></div></details>)}</div>}</aside>
      </div>
    </div>
  );
}
