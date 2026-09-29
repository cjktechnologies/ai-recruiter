"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import type { Me } from "@/lib/types";
import { cx, Loading } from "./ui";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);
export const useCan = () => {
  const me = useMe();
  return (perm: string) => !!me?.permissions.includes(perm);
};

const NAV: { href: string; label: string; perm: string }[] = [
  { href: "/dashboard", label: "Dashboard", perm: "analytics:read" },
  { href: "/requisitions", label: "Requisitions", perm: "requisitions:read" },
  { href: "/jobs", label: "Jobs & pipeline", perm: "jobs:read" },
  { href: "/candidates", label: "Candidates", perm: "candidates:read" },
  { href: "/screening", label: "AI screening", perm: "screening:review" },
  { href: "/assessments", label: "Assessments", perm: "assessments:read" },
  { href: "/interviews", label: "Interviews", perm: "interviews:read" },
  { href: "/offers", label: "Offers", perm: "offers:read" },
  { href: "/onboarding", label: "Onboarding", perm: "onboarding:read" },
  { href: "/analytics", label: "Analytics", perm: "analytics:read" },
  { href: "/agents", label: "AI agents", perm: "agents:read" },
  { href: "/audit", label: "Audit log", perm: "audit:read" },
  { href: "/admin", label: "Administration", perm: "org:update" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { data: me, loading } = useApi<Me>("/auth/me");
  const { data: unread } = useApi<{ total: number }>("/notifications", { unread: true, page_size: 1 });
  const path = usePathname();
  const router = useRouter();
  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    router.push("/login");
  }
  if (loading && !me) return <Loading />;
  return (
    <MeContext.Provider value={me}>
      <div className="flex min-h-screen">
        <aside className="hidden w-56 shrink-0 border-r border-line bg-surface md:block">
          <div className="px-4 py-4">
            <div className="text-sm font-semibold">AI Recruiter</div>
            <div className="truncate text-xs text-ink-3">{me?.organization_name}</div>
          </div>
          <nav className="space-y-0.5 px-2" aria-label="Main">
            {NAV.filter((n) => me?.permissions.includes(n.perm)).map((n) => (
              <Link key={n.href} href={n.href}
                className={cx("block rounded-md px-2.5 py-1.5 text-sm",
                  path.startsWith(n.href) ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2")}>
                {n.label}
              </Link>
            ))}
          </nav>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2">
            <select className="rounded border border-line bg-surface px-2 py-1 text-sm md:hidden" value={path}
              onChange={(e) => router.push(e.target.value)} aria-label="Navigate">
              {NAV.filter((n) => me?.permissions.includes(n.perm)).map((n) => <option key={n.href} value={n.href}>{n.label}</option>)}
            </select>
            <div className="hidden text-xs text-ink-3 md:block">AI recommendations are advisory — people make hiring decisions.</div>
            <div className="flex items-center gap-3 text-sm">
              <Link href="/notifications" className="text-ink-2 hover:text-ink">
                Notifications{unread?.total ? <span className="ml-1 rounded-full bg-accent px-1.5 text-xs text-white">{unread.total}</span> : null}
              </Link>
              <span className="text-ink-2">{me?.full_name}</span>
              <button onClick={logout} className="text-ink-3 hover:text-ink">Sign out</button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        </div>
      </div>
    </MeContext.Provider>
  );
}

export async function markAllRead() {
  await api("/notifications/read-all", { method: "POST" });
}
