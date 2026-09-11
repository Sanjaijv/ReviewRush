"use client";

import { useState, type ReactNode } from "react";
import Image from "next/image";
import { ChevronDown, LogOut, Settings2, ShieldCheck } from "lucide-react";
import { logout } from "@/lib/api";
import type { Installation, Me, Organization } from "@/lib/types";
import type { AdminSurface } from "@/lib/dashboard-types";

export function AppShell({
  user,
  installations,
  installationId,
  onInstallationChange,
  organizations,
  showAdmin,
  adminSurface,
  onAdminSurface,
  onHome,
  children,
}: {
  user: Me;
  installations: Installation[];
  installationId: number | null;
  onInstallationChange: (id: number) => void;
  organizations: Organization[];
  showAdmin: boolean;
  adminSurface: AdminSurface | null;
  onAdminSurface: (surface: AdminSurface | null) => void;
  onHome: () => void;
  children: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const currentInstallation = installations.find((installation) => installation.id === installationId);
  const canManageOrganization = organizations.some((organization) => ["owner", "admin"].includes(organization.role));

  async function signOut() {
    await logout();
    window.location.reload();
  }

  return (
    <div className="min-h-screen bg-paper-0">
      <header className="sticky top-0 z-30 border-b border-line/90 bg-paper-0/95 backdrop-blur-sm">
        <div className="mx-auto flex min-h-16 w-full max-w-[1440px] items-center gap-4 px-5 lg:px-8">
          <button type="button" onClick={onHome} className="rr-focus-ring flex shrink-0 items-center rounded-xs">
            <Image src="/logo-reviewrush.png" alt="ReviewRush" width={2172} height={724} priority className="h-6 w-auto" />
          </button>

          <div className="h-5 w-px bg-line" aria-hidden="true" />

          <label className="relative flex min-w-0 items-center">
            <span className="sr-only">Switch installation</span>
            <select
              value={installationId ?? ""}
              onChange={(event) => onInstallationChange(Number(event.target.value))}
              className="rr-focus-ring max-w-[210px] appearance-none rounded-xs border border-transparent bg-transparent py-2 pl-2 pr-8 font-mono text-xs font-medium text-accent transition hover:border-line hover:bg-surface-1"
            >
              {installations.map((installation) => (
                <option key={installation.id} value={installation.id}>
                  {installation.account_login}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="pointer-events-none absolute right-2 text-accent" aria-hidden="true" />
          </label>

          <div className="flex-1" />

          {showAdmin && (
            <details className="relative hidden sm:block">
              <summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-1.5 rounded-xs px-2 py-2 text-xs font-semibold text-ink-500 transition hover:text-ink-900 [&::-webkit-details-marker]:hidden">
                <ShieldCheck size={15} aria-hidden="true" />
                Admin
                <ChevronDown size={13} aria-hidden="true" />
              </summary>
              <div className="absolute right-0 top-11 w-48 rounded-sm border border-line bg-surface-1 p-1.5 shadow-[0_12px_32px_rgba(23,27,34,0.12)]">
                <AdminItem active={adminSurface === "evaluation"} onClick={() => onAdminSurface("evaluation")}>
                  Evaluation admin
                </AdminItem>
                <AdminItem active={adminSurface === "finetune"} onClick={() => onAdminSurface("finetune")}>
                  Fine-tune admin
                </AdminItem>
              </div>
            </details>
          )}

          <details open={menuOpen} onToggle={(event) => setMenuOpen((event.currentTarget as HTMLDetailsElement).open)} className="relative">
            <summary className="rr-focus-ring flex cursor-pointer list-none items-center gap-2 rounded-xs p-1 text-left [&::-webkit-details-marker]:hidden">
              <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-accent/15 font-mono text-xs font-semibold text-accent">
                {user.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element -- GitHub avatar host is user-controlled.
                  <img src={user.avatar_url} alt="" width={32} height={32} className="h-full w-full object-cover" />
                ) : (
                  user.login.slice(0, 2).toUpperCase()
                )}
              </span>
              <span className="hidden max-w-28 truncate text-sm font-semibold text-ink-700 md:block">{user.login}</span>
              <ChevronDown size={14} className="text-ink-500" aria-hidden="true" />
            </summary>
            <div className="absolute right-0 top-12 w-52 rounded-sm border border-line bg-surface-1 p-1.5 shadow-[0_12px_32px_rgba(23,27,34,0.12)]">
              <div className="border-b border-line px-3 py-2">
                <p className="font-mono text-[11px] text-ink-500">SIGNED IN AS</p>
                <p className="mt-1 truncate text-sm font-semibold">@{user.login}</p>
              </div>
              {canManageOrganization && (
                <AdminItem active={adminSurface === "organization"} onClick={() => onAdminSurface("organization")}>
                  <Settings2 size={14} aria-hidden="true" />
                  Organization settings
                </AdminItem>
              )}
              <button
                type="button"
                onClick={() => void signOut()}
                className="rr-focus-ring mt-1 flex w-full items-center gap-2 rounded-xs px-3 py-2 text-left text-sm text-ink-500 transition hover:bg-bad/5 hover:text-bad"
              >
                <LogOut size={14} aria-hidden="true" />
                Sign out
              </button>
            </div>
          </details>
        </div>
      </header>
      <div className="mx-auto w-full max-w-[1440px] px-5 pb-16 pt-8 lg:px-8">{children}</div>
      {currentInstallation && <span className="sr-only">Current installation: {currentInstallation.account_login}</span>}
    </div>
  );
}

function AdminItem({ active, onClick, children }: { active?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rr-focus-ring flex w-full items-center gap-2 rounded-xs px-3 py-2 text-left text-sm transition ${active ? "bg-accent/10 font-semibold text-accent" : "text-ink-700 hover:bg-paper-0"}`}
    >
      {children}
    </button>
  );
}
