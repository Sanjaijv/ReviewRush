import { Dashboard } from "@/components/Dashboard";

export default async function InstallationRepositoriesPage({ params }: { params: Promise<{ installationId: string }> }) {
  const { installationId } = await params;
  const parsedId = Number(installationId);
  return <Dashboard initialInstallationId={Number.isFinite(parsedId) ? parsedId : null} />;
}
