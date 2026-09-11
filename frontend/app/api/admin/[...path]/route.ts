import { NextRequest, NextResponse } from "next/server";

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8010";

async function proxy(request: NextRequest, path: string[]) {
  const token = process.env.REVIEWRUSH_ADMIN_TOKEN;
  if (!token) {
    return NextResponse.json({ detail: "admin token is not configured" }, { status: 503 });
  }

  const upstreamUrl = `${BACKEND_ORIGIN}/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.text();
  const upstream = await fetch(upstreamUrl, { method: request.method, headers, body, cache: "no-store" });
  const responseHeaders = new Headers();
  const upstreamContentType = upstream.headers.get("content-type");
  if (upstreamContentType) responseHeaders.set("Content-Type", upstreamContentType);
  return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}

export async function PUT(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await context.params).path);
}
