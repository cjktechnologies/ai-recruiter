import { NextRequest, NextResponse } from "next/server";
import { API_PREFIX, BACKEND_URL, REFRESH_COOKIE } from "@/lib/config";
import { clearSessionCookies, setSessionCookies } from "@/lib/session";

/** Login (password or candidate magic-link token) → httpOnly session cookies. */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const isMagic = typeof body.magic_token === "string";
  const upstream = await fetch(
    `${BACKEND_URL}${API_PREFIX}${isMagic ? "/auth/candidate/verify" : "/auth/login"}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Forwarded-For": req.headers.get("x-forwarded-for") ?? "" },
      body: JSON.stringify(isMagic ? { refresh_token: body.magic_token } : { email: body.email, password: body.password }),
    },
  );
  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) return NextResponse.json(data, { status: upstream.status });
  const res = NextResponse.json({ ok: true });
  setSessionCookies(res, data);
  return res;
}

export async function DELETE(req: NextRequest) {
  const rt = req.cookies.get(REFRESH_COOKIE)?.value;
  if (rt) {
    await fetch(`${BACKEND_URL}${API_PREFIX}/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    }).catch(() => undefined);
  }
  const res = NextResponse.json({ ok: true });
  clearSessionCookies(res);
  return res;
}
