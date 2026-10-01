import type { NextRequest } from "next/server";
import { PROXY_SHARED_SECRET } from "./config";

/**
 * Headers that tell the API who the real client is. Behind an ingress, X-Forwarded-For is enough;
 * on platforms that overwrite it between services (Vercel), the API only trusts X-Client-IP when it
 * arrives with the shared proxy secret.
 */
export function clientIpHeaders(req: NextRequest): Record<string, string> {
  const fwd = req.headers.get("x-forwarded-for") ?? "";
  const headers: Record<string, string> = {};
  if (fwd) headers["X-Forwarded-For"] = fwd;
  const ip = fwd.split(",")[0].trim();
  if (PROXY_SHARED_SECRET && ip) {
    headers["X-Client-IP"] = ip;
    headers["X-Proxy-Secret"] = PROXY_SHARED_SECRET;
  }
  return headers;
}
