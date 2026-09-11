"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { demoData } from "@/lib/demo-data";
import type { AdminSurface, WorkspaceTab } from "@/lib/dashboard-types";
import type { Installation, Me, Organization, RepositorySummary, RunSummary } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { RepositoryIndex } from "@/components/RepositoryIndex";
import { RepositoryWorkspace } from "@/components/RepositoryWorkspace";
import { SignInScreen } from "@/components/SignInScreen";
import { OrganizationPanel } from "@/components/admin/OrganizationPanel";
import { EvaluationPanel } from "@/components/admin/EvaluationPanel";
import { FinetunePanel } from "@/components/admin/FinetunePanel";
import { ErrorPanel, LoadingPanel } from "@/components/dashboard/primitives";

const demoEnabled = process.env.NEXT_PUBLIC_REVIEWRUSH_DEMO === "true";
const adminEnabled = process.env.NEXT_PUBLIC_REVIEWRUSH_EVAL_ADMIN === "true" || demoEnabled;

export interface DashboardProps {
  initialInstallationId?: number | null;
  initialRepositoryId?: number | null;
  initialTab?: WorkspaceTab;
  initialRunId?: number | null;
  initialAdminSurface?: AdminSurface | null;
}

export function Dashboard(props: DashboardProps = {}) {
  const { user, loading: authLoading } = useAuth();
  const hydrated = useSyncExternalStore(noopSubscribe, () => true, () => false);
  if (demoEnabled && hydrated) {
    return <AuthenticatedDashboard {...props} user={{ github_user_id: 1, login: "sanjaijv", avatar_url: "", installation_ids: [1, 2] }} />;
  }
  if (demoEnabled && !hydrated) return <LoadingScreen />;
  if (authLoading) return <LoadingScreen />;
  if (!user) return <SignInScreen />;
  return <AuthenticatedDashboard {...props} user={user} />;
}

function AuthenticatedDashboard({
  user,
  initialInstallationId,
  initialRepositoryId,
  initialTab,
  initialRunId,
  initialAdminSurface,
}: DashboardProps & { user: Me }) {
  const router = useRouter();
  const useDemo = demoEnabled;
  const [installations, setInstallations] = useState<Installation[] | null>(useDemo ? demoData.installations : null);
  const [installationId, setInstallationId] = useState<number | null>(initialInstallationId ?? (useDemo ? demoData.installations[0]?.id ?? null : null));
  const [repositories, setRepositories] = useState<RepositorySummary[]>(useDemo ? demoData.repositoriesByInstallation[initialInstallationId ?? 1] ?? [] : []);
  const [latestRuns, setLatestRuns] = useState<Record<number, RunSummary | undefined>>(() => (useDemo ? getDemoLatestRuns(initialInstallationId ?? 1) : {}));
  const [organizations, setOrganizations] = useState<Organization[]>(useDemo ? demoData.organizations : []);
  const [selectedRepoOverride, setSelectedRepoOverride] = useState<RepositorySummary | null>(null);
  const [adminSurface, setAdminSurface] = useState<AdminSurface | null>(initialAdminSurface ?? null);
  const [installationsError, setInstallationsError] = useState<string | null>(null);
  const [repositoriesError, setRepositoriesError] = useState<string | null>(null);
  const [loadingRepositories, setLoadingRepositories] = useState(!useDemo);

  useEffect(() => {
    if (useDemo) return;
    let cancelled = false;
    Promise.all([api<Installation[]>("/installations"), api<Organization[]>("/organizations")])
      .then(([installationRows, organizationRows]) => {
        if (cancelled) return;
        setInstallations(installationRows);
        setOrganizations(organizationRows);
        setInstallationId((current) => current ?? installationRows[0]?.id ?? null);
      })
      .catch((error) => {
        if (!cancelled) setInstallationsError(error instanceof Error ? error.message : "Could not load installations.");
      });
    return () => { cancelled = true; };
  }, [useDemo]);

  useEffect(() => {
    if (installationId === null || useDemo) return;
    let cancelled = false;
    api<RepositorySummary[]>(`/installations/${installationId}/repositories`)
      .then(async (rows) => {
        if (cancelled) return;
        setRepositories(rows);
        const latestEntries = await Promise.all(rows.map(async (repository) => {
          try {
            const runs = await api<RunSummary[]>(`/repositories/${repository.id}/runs?limit=1`);
            return [repository.id, runs[0]] as const;
          } catch {
            return [repository.id, undefined] as const;
          }
        }));
        if (!cancelled) setLatestRuns(Object.fromEntries(latestEntries));
      })
      .catch((error) => {
        if (!cancelled) setRepositoriesError(error instanceof Error ? error.message : "Could not load repositories.");
      })
      .finally(() => {
        if (!cancelled) setLoadingRepositories(false);
      });
    return () => { cancelled = true; };
  }, [installationId, useDemo]);

  const installationName = useMemo(
    () => installations?.find((installation) => installation.id === installationId)?.account_login ?? "installation",
    [installations, installationId],
  );
  const visibleRepositories = useDemo ? demoData.repositoriesByInstallation[installationId ?? 0] ?? [] : repositories;
  const visibleLatestRuns = useDemo ? getDemoLatestRuns(installationId ?? 0) : latestRuns;
  const routeRepository = initialRepositoryId ? visibleRepositories.find((repository) => repository.id === initialRepositoryId && repository.is_active) ?? null : null;
  const selectedRepo = selectedRepoOverride ?? routeRepository;

  function handleInstallationChange(id: number) {
    setSelectedRepoOverride(null);
    setRepositoriesError(null);
    setLoadingRepositories(!useDemo);
    setInstallationId(id);
    setAdminSurface(null);
    router.push(`/installations/${id}/repositories`);
  }

  function handleHome() {
    setSelectedRepoOverride(null);
    setAdminSurface(null);
    router.push("/");
  }

  function handleAdminSurface(surface: AdminSurface | null) {
    setAdminSurface(surface);
    if (surface === "organization") router.push("/org");
    else if (surface === "evaluation") router.push("/admin/evaluation");
    else if (surface === "finetune") router.push("/admin/finetune");
    else router.push(`/installations/${installationId ?? ""}/repositories`);
  }

  if (installationsError) return <ErrorPanel message={installationsError} onRetry={() => window.location.reload()} />;
  if (installations === null) return <LoadingScreen />;
  const availableInstallations = installations;

  function shellProps() {
    return {
      user,
      installations: availableInstallations,
      installationId,
      onInstallationChange: handleInstallationChange,
      organizations,
      showAdmin: adminEnabled,
      adminSurface,
      onAdminSurface: handleAdminSurface,
      onHome: handleHome,
    };
  }

  let content;
  if (adminSurface === "organization") {
    content = <OrganizationPanel organizations={organizations} />;
  } else if (adminSurface === "evaluation") {
    content = <EvaluationPanel />;
  } else if (adminSurface === "finetune") {
    content = <FinetunePanel />;
  } else if (selectedRepo) {
    content = (
      <RepositoryWorkspace
        key={selectedRepo.id}
        repository={selectedRepo}
        demoData={useDemo ? demoData.repositoryData[selectedRepo.id] : undefined}
        initialTab={initialTab}
        initialRunId={initialRunId}
        onBack={handleHome}
        onDisconnect={() => {
          setRepositories((current) => current.map((repo) => repo.id === selectedRepo.id ? { ...repo, is_active: false, disconnected_at: new Date().toISOString() } : repo));
          setSelectedRepoOverride(null);
          router.push(`/installations/${installationId ?? ""}/repositories`);
        }}
      />
    );
  } else if (availableInstallations.length === 0) {
    content = <RepositoryIndex installationName={installationName} repositories={[]} latestRuns={{}} loading={false} error={null} onRetry={() => undefined} onSelect={() => undefined} />;
  } else {
    content = (
      <RepositoryIndex
        installationName={installationName}
        repositories={visibleRepositories}
        latestRuns={visibleLatestRuns}
        loading={useDemo ? false : loadingRepositories}
        error={repositoriesError}
        onRetry={() => window.location.reload()}
        onSelect={(repository) => {
          if (!repository.is_active) return;
          setSelectedRepoOverride(repository);
          router.push(`/repositories/${repository.id}/overview`);
        }}
      />
    );
  }

  return <AppShell {...shellProps()}>{content}</AppShell>;
}

function noopSubscribe() {
  return () => undefined;
}

function LoadingScreen() {
  return <main className="flex min-h-screen items-center justify-center px-5"><LoadingPanel label="Loading ReviewRush" /></main>;
}

function getDemoLatestRuns(installationId: number): Record<number, RunSummary | undefined> {
  const repositories = demoData.repositoriesByInstallation[installationId] ?? [];
  return Object.fromEntries(repositories.map((repository) => [repository.id, demoData.repositoryData[repository.id]?.runs[0]]));
}
