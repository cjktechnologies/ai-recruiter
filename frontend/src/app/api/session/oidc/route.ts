import { NextRequest, NextResponse } from "next/server";
import { API_PREFIX, BACKEND_URL } from "@/lib/config";
import { setSessionCookies } from "@/lib/session";

/** OIDC redirect URI: exchanges the authorization code via the backend, then starts a session. */
export async function GET(req: NextRequest) {
  const url = new URL(`${BACKEND_URL}${API_PREFIX}/auth/oidc/callback`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));
  const upstream = await fetch(url, { headers: { cookie: req.headers.get("cookie") ?? "" } });
  if (!upstream.ok) return NextResponse.redirect(new URL("/login?error=sso", req.url));
  const res = NextResponse.redirect(new URL("/dashboard", req.url));
  setSessionCookies(res, await upstream.json());
  return res;
}
