"use client";

import { useAuth } from "@/lib/auth";
import { loginUrl, logout } from "@/lib/api";

export function Header() {
  const { user, loading } = useAuth();

  return (
    <header className="border-b border-neutral-200 bg-white px-5 py-3 flex items-center justify-between">
      <span className="font-semibold">ReviewRush Dashboard</span>
      {!loading && (
        <div className="text-sm">
          {user ? (
            <span className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element -- avatar host is arbitrary (GitHub CDN), not worth configuring next/image remotePatterns for */}
              <img
                src={user.avatar_url}
                alt=""
                width={24}
                height={24}
                className="rounded-full"
              />
              {user.login}
              <button
                type="button"
                onClick={async () => {
                  await logout();
                  window.location.reload();
                }}
                className="text-neutral-500 hover:text-neutral-900 underline underline-offset-2"
              >
                log out
              </button>
            </span>
          ) : (
            <a href={loginUrl} className="text-blue-600 hover:underline">
              Log in with GitHub
            </a>
          )}
        </div>
      )}
    </header>
  );
}
