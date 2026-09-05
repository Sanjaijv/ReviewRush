"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, UnauthorizedError } from "./api";
import type { Me } from "./types";

interface AuthState {
  user: Me | null;
  loading: boolean;
}

const AuthContext = createContext<AuthState>({ user: null, loading: true });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    api<Me>("/me")
      .then((user) => {
        if (!cancelled) setState({ user, loading: false });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          setState({ user: null, loading: false });
        } else {
          // A non-auth failure (network error, 500) shouldn't be silently
          // treated as "logged out" - surface it by leaving user null but
          // logging, so the login screen at least explains something's wrong.
          console.error("failed to load current user", err);
          setState({ user: null, loading: false });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
