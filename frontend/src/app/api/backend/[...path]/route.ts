import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, API_PREFIX, BACKEND_URL, REFRESH_COOKIE } from "@/lib/config";
import { clearSessionCookies, setSessionCookies, type TokenPair } from "@/lib/session";

/**
 * Backend-for-frontend proxy: attaches the access token from the httpOnly cookie, transparently
 * refreshes it once on 401, and streams the response back. Only /api/v1 paths are reachable.
 */
const FORWARD_HEADERS = ["content-type", "idempotency-key", "x-organization-id", "accept"];

async function forward(req: NextRequest, path: string[], token?: string): Promise<Response> {
  const url = new URL(`${BACKEND_URL}${API_PREFIX}/${path.map(encodeURIComponent).join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.append(k, v));
  const headers = new Headers();
  for (const h of FORWARD_HEADERS) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) headers.set("X-Forwarded-For", fwd);
  const hasBody = !["GET", "HEAD"].includes(req.method);
  return fetch(url, {
    method: req.method,
    headers,
    body: hasBody ? await req.clone().arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });
}

async function handler(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  let token = req.cookies.get(ACCESS_COOKIE)?.value;
  let refreshed: TokenPair | null = null;
  let upstream = await forward(req, path, token);
  const rt = req.cookies.get(REFRESH_COOKIE)?.value;
  if (upstream.status === 401 && rt) {
    const r = await fetch(`${BACKEND_URL}${API_PREFIX}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (r.ok) {
      refreshed = (await r.json()) as TokenPair;
      token = refreshed.access_token;
      upstream = await forward(req, path, token);
    }
  }
  const res = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      ...(upstream.headers.get("content-disposition")
        ? { "content-disposition": upstream.headers.get("content-disposition")! }
        : {}),
      "x-request-id": upstream.headers.get("x-request-id") ?? "",
      ...(upstream.headers.get("location") ? { location: upstream.headers.get("location")! } : {}),
    },
  });
  // OIDC state/nonce cookies set by the backend must reach the browser.
  for (const c of upstream.headers.getSetCookie?.() ?? []) res.headers.append("set-cookie", c);
  if (refreshed) setSessionCookies(res, refreshed);
  else if (upstream.status === 401) clearSessionCookies(res);
  return res;
}

export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
