"use client";

import { useAuth } from "@/lib/auth";
import { loginUrl } from "@/lib/api";
import { Dashboard } from "@/components/Dashboard";

export default function HomePage() {
  const { user, loading } = useAuth();

  if (loading) {
    return <p className="p-5 text-neutral-500 text-sm">Loading…</p>;
  }

  if (!user) {
    return (
      <p className="p-5">
        <a href={loginUrl} className="text-blue-600 hover:underline">
          Log in with GitHub
        </a>
      </p>
    );
  }

  return <Dashboard />;
}
