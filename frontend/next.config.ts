import type { NextConfig } from "next";

// The backend session cookie is SameSite=Lax, which browsers withhold from
// cross-origin fetch(). Rewriting /api/* to the FastAPI backend keeps the
// browser's view of the origin single, so the existing GitHub-OAuth cookie
// (app/api/v1/dashboard.py) works with no new auth code on this side.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
