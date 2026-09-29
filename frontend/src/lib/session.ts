import type { NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, SECURE_COOKIES } from "./config";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** Tokens live only in httpOnly cookies; browser JS never sees them (XSS cannot exfiltrate). */
export function setSessionCookies(res: NextResponse, t: TokenPair): void {
  const base = { httpOnly: true, secure: SECURE_COOKIES, sameSite: "lax" as const, path: "/" };
  res.cookies.set(ACCESS_COOKIE, t.access_token, { ...base, maxAge: t.expires_in });
  res.cookies.set(REFRESH_COOKIE, t.refresh_token, { ...base, maxAge: 60 * 60 * 24 * 14 });
}

export function clearSessionCookies(res: NextResponse): void {
  res.cookies.delete(ACCESS_COOKIE);
  res.cookies.delete(REFRESH_COOKIE);
}
