"use client";

import { useState } from "react";
import { Download, Save, ShieldAlert, Trash2 } from "lucide-react";
import { apiJson, ApiError } from "@/lib/api";
import type { Organization } from "@/lib/types";
import { AlertBanner, SectionHeader, StatusPill } from "@/components/dashboard/primitives";

const demo = process.env.NEXT_PUBLIC_REVIEWRUSH_DEMO === "true";

type OrganizationForm = {
  region: string;
  retention: string;
  maxReviews: string;
  maxRepos: string;
  provider: string;
  model: string;
};

const fieldLabels: Record<keyof OrganizationForm, string> = {
  region: "Region",
  retention: "Retention days",
  maxReviews: "Max AI reviews / day",
  maxRepos: "Max repositories",
  provider: "AI provider override",
  model: "AI model override",
};

export function OrganizationPanel({ organizations }: { organizations: Organization[] }) {
  const [organization, setOrganization] = useState(organizations[0] ?? null);
  const [form, setForm] = useState<OrganizationForm>(() => organization ? {
    region: organization.region,
    retention: organization.retention_days_default?.toString() ?? "",
    maxReviews: organization.max_ai_reviews_per_day?.toString() ?? "",
    maxRepos: organization.max_repositories?.toString() ?? "",
    provider: organization.ai_provider_override ?? "",
    model: organization.ai_model_override ?? "",
  } : { region: "us", retention: "", maxReviews: "", maxRepos: "", provider: "", model: "" });
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  if (!organization) return <AlertBanner tone="info">No organization settings are available for this installation.</AlertBanner>;
  const canAdmin = ["owner", "admin"].includes(organization.role);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      if (!demo) {
        const updated = await apiJson<Organization>(`/organizations/${organization.id}/settings`, "PUT", {
          region: form.region,
          retention_days_default: form.retention ? Number(form.retention) : null,
          max_ai_reviews_per_day: form.maxReviews ? Number(form.maxReviews) : null,
          max_repositories: form.maxRepos ? Number(form.maxRepos) : null,
          ai_provider_override: form.provider,
          ai_model_override: form.model,
        });
        setOrganization(updated);
      }
      setStatus(demo ? "Demo mode: defaults saved locally." : "Organization defaults saved.");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.message : "Could not save organization settings.");
    } finally {
      setSaving(false);
    }
  }

  async function exportData() {
    setExporting(true);
    setStatus(null);
    try {
      const bundle = demo ? { organization: organization.slug, exported_at: new Date().toISOString(), demo: true } : await apiJson<Record<string, unknown>>(`/organizations/${organization.id}/export`, "POST", {});
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${organization.slug}-reviewrush-export.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus("Export downloaded.");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.message : "Could not export data.");
    } finally {
      setExporting(false);
    }
  }

  async function deleteData() {
    if (confirm !== organization.slug) return;
    setDeleting(true);
    setStatus(null);
    try {
      if (!demo) await apiJson(`/organizations/${organization.id}/delete-data`, "POST", { confirm_slug: confirm });
      setStatus(demo ? "Demo mode: deletion is visual only." : "Organization data deletion started.");
      setConfirm("");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.message : "Could not delete organization data.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      <SectionHeader eyebrow="Organization" title="Settings" description="Identity, defaults, and the irreversible actions for this installation." action={<StatusPill label={`${organization.role} · ${organization.plan}`} tone="accent" />} />
      {status && <AlertBanner tone={status.includes("Could not") ? "bad" : "good"}>{status}</AlertBanner>}
      <div className="mt-5 space-y-5">
        <section className="rr-card p-5">
          <p className="rr-eyebrow">Identity</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <div><p className="text-xs text-ink-500">Organization</p><p className="mt-1 font-display text-lg font-semibold">{organization.name}</p><p className="font-mono text-xs text-ink-500">{organization.slug}</p></div>
            <div><p className="text-xs text-ink-500">GitHub installation</p><p className="mt-1 font-mono text-sm">#{organization.id}</p></div>
            <div><p className="text-xs text-ink-500">Region</p><p className="mt-1 font-mono text-sm uppercase">{organization.region}</p></div>
          </div>
        </section>

        <section className="rr-card p-5">
          <div className="mb-5"><p className="rr-eyebrow">Organization defaults</p><h3 className="mt-1 font-display text-lg font-semibold">Applied under repository config</h3></div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(Object.keys(fieldLabels) as Array<keyof OrganizationForm>).map((field) => (
              <label key={field} className="block">
                <span className="mb-1.5 block text-sm font-semibold">{fieldLabels[field]}</span>
                <input value={form[field]} onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))} type={field === "retention" || field === "maxReviews" || field === "maxRepos" ? "number" : "text"} className="rr-focus-ring w-full rounded-xs border border-line bg-paper-0 px-3 py-2 text-sm outline-hidden transition focus:border-accent" placeholder="Use global default" />
              </label>
            ))}
          </div>
          <div className="mt-5 flex justify-end"><button type="button" disabled={!canAdmin || saving} onClick={() => void save()} className="rr-focus-ring inline-flex items-center gap-2 rounded-xs bg-accent px-4 py-2 text-sm font-semibold text-paper-0 transition hover:bg-accent/85 disabled:opacity-45"><Save size={15} aria-hidden="true" />{saving ? "Saving…" : "Save defaults"}</button></div>
          {!canAdmin && <p className="mt-3 text-right text-xs text-ink-500">Only organization admins can update defaults.</p>}
        </section>

        <section className="rounded-sm border border-bad/30 bg-bad/5 p-5">
          <div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 shrink-0 text-bad" size={20} aria-hidden="true" /><div><p className="rr-eyebrow text-bad">Danger zone</p><h3 className="mt-1 font-display text-lg font-semibold">Irreversible organization actions</h3><p className="mt-1 text-sm text-ink-500">These actions affect every repository covered by this installation.</p></div></div>
          <div className="mt-5 grid gap-4 border-t border-bad/20 pt-5 md:grid-cols-2">
            <div><p className="font-semibold">Export all data</p><p className="mt-1 text-sm text-ink-500">Download a JSON bundle of organization data.</p><button type="button" disabled={exporting} onClick={() => void exportData()} className="rr-focus-ring mt-4 inline-flex items-center gap-2 rounded-xs border border-bad/30 px-3 py-2 text-sm font-semibold text-bad transition hover:bg-bad/10 disabled:opacity-50"><Download size={15} aria-hidden="true" />{exporting ? "Preparing…" : "Export all data"}</button></div>
            <div><p className="font-semibold">Delete all data</p><p className="mt-1 text-sm text-ink-500">Type <code className="font-mono text-bad">{organization.slug}</code> to confirm.</p><input value={confirm} onChange={(event) => setConfirm(event.target.value)} className="rr-focus-ring mt-3 w-full rounded-xs border border-bad/25 bg-surface-1 px-3 py-2 font-mono text-sm outline-hidden focus:border-bad" placeholder={organization.slug} aria-label="Type organization slug to confirm deletion" /><button type="button" disabled={!canAdmin || confirm !== organization.slug || deleting} onClick={() => void deleteData()} className="rr-focus-ring mt-3 inline-flex items-center gap-2 rounded-xs bg-bad px-3 py-2 text-sm font-semibold text-paper-0 transition hover:bg-bad/85 disabled:cursor-not-allowed disabled:opacity-45"><Trash2 size={15} aria-hidden="true" />{deleting ? "Deleting…" : "Delete all data"}</button></div>
          </div>
        </section>
      </div>
    </div>
  );
}
