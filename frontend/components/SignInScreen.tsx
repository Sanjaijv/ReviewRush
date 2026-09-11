"use client";

import { useSyncExternalStore } from "react";
import Image from "next/image";
import { ArrowRight, Github } from "lucide-react";
import { loginUrl } from "@/lib/api";

function noopSubscribe() {
  return () => undefined;
}

function getDefaultAuthQueryState() {
  return "";
}

function getAuthQueryState() {
  return window.location.search;
}

export function SignInScreen() {
  const query = useSyncExternalStore(noopSubscribe, getAuthQueryState, getDefaultAuthQueryState);
  const params = new URLSearchParams(query);
  const returning = params.get("auth") === "loading";
  const hasError = params.get("auth_error") === "1" || params.get("error") === "1";

  if (returning) {
    return (
      <main className="flex min-h-screen items-center justify-center px-5">
        <div className="flex items-center gap-3 text-sm text-ink-500" role="status" aria-live="polite">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent/25 border-t-accent" aria-hidden="true" />
          Returning from GitHub…
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-5 py-12">
      <section className="w-full max-w-[360px]">
        <div className="mb-10">
          <Image src="/logo-reviewrush.png" alt="ReviewRush" width={2172} height={724} priority className="h-8 w-auto" />
        </div>

        <p className="rr-eyebrow mb-3">Operator console</p>
        <h1 className="font-display text-4xl font-extrabold leading-[1.02] tracking-[-0.055em]">
          Ship with a second set of eyes.
        </h1>
        <p className="mt-4 text-base text-ink-500">
          AI-assisted code review for your GitHub organization.
        </p>

        {hasError && (
          <div className="mt-6 rounded-sm border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad" role="alert">
            Something went wrong signing you in. Try again.
          </div>
        )}

        <a
          href={loginUrl}
          className="rr-focus-ring mt-8 flex min-h-12 items-center justify-center gap-3 rounded-sm bg-ink-900 px-4 py-3 font-semibold text-paper-0 transition hover:bg-ink-700"
        >
          <Github size={18} aria-hidden="true" />
          Continue with GitHub
          <ArrowRight className="ml-auto" size={17} aria-hidden="true" />
        </a>
        <p className="mt-4 text-xs leading-5 text-ink-500">
          ReviewRush uses GitHub OAuth. No password or separate account is required.
        </p>
      </section>
    </main>
  );
}
