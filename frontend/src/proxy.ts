import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";

/** Redirect unauthenticated users away from the staff app; public/candidate pages stay open. */
const PUBLIC_PREFIXES = ["/login", "/careers", "/assessment", "/offer", "/reference", "/portal", "/api", "/_next"];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p)) || pathname === "/favicon.ico") {
    return NextResponse.next();
  }
  if (!req.cookies.get(ACCESS_COOKIE) && !req.cookies.get(REFRESH_COOKIE)) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
