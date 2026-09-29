"use client";

import Link from "next/link";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { titleCase } from "@/lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";
export function Button({
  variant = "primary", className, loading, children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-white hover:opacity-90",
    secondary: "bg-surface border border-line text-ink hover:bg-surface-2",
    danger: "bg-critical text-white hover:opacity-90",
    ghost: "text-ink-2 hover:bg-surface-2",
  };
  return (
    <button
      className={cx("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition",
        "disabled:cursor-not-allowed disabled:opacity-50", styles[variant], className)}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  neutral: "bg-surface-2 text-ink-2",
  good: "bg-good/15 text-good",
  warn: "bg-warn/15 text-warn",
  serious: "bg-serious/15 text-serious",
  critical: "bg-critical/15 text-critical",
  info: "bg-accent/15 text-accent",
  ai: "bg-ai/15 text-ai",
};
const STATUS_TONE: Record<string, keyof typeof TONES> = {
  approved: "good", published: "good", hired: "good", accepted: "good", completed: "good", done: "good",
  scored: "good", clear: "good", strong_yes: "good", yes: "good", succeeded: "good", sent: "info",
  pending_approval: "warn", pending_review: "warn", pending: "warn", waiting_human: "warn", maybe: "warn",
  submitted: "warn", draft: "neutral", invited: "info", scheduled: "info", in_progress: "info", running: "info",
  rejected: "critical", declined: "critical", failed: "critical", no: "serious", strong_no: "critical",
  cancelled: "neutral", withdrawn: "neutral", closed: "neutral", overridden: "ai", blocked: "serious",
  expired: "neutral", on_hold: "warn", filled: "good", adverse: "critical", consider: "warn",
};
export function Badge({ children, tone }: { children: ReactNode; tone?: keyof typeof TONES }) {
  return <span className={cx("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium", TONES[tone ?? "neutral"])}>{children}</span>;
}
export function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{titleCase(status)}</Badge>;
}
/** Marks AI-generated content so it is never confused with facts extracted from candidate data. */
export function AIBadge({ label = "AI-generated" }: { label?: string }) {
  return <Badge tone="ai">✦ {label}</Badge>;
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-ink-2">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-critical">{error}</span>}
    </label>
  );
}
const inputCls = "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm placeholder:text-ink-3";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(inputCls, p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea rows={4} {...p} className={cx(inputCls, p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(inputCls, p.className)} />;

export function Table({ head, rows, empty = "Nothing here yet." }: { head: ReactNode[]; rows: ReactNode[][]; empty?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-ink-3">
          <tr>{head.map((h, i) => <th key={i} className="border-b border-line px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={head.length} className="px-3 py-6 text-center text-ink-3">{empty}</td></tr>}
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0 hover:bg-surface-2/60">
              {r.map((c, j) => <td key={j} className="px-3 py-2 align-top">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-2">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: { message: string; errors?: { loc: (string | number)[]; msg: string }[] } | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-3 rounded-md border border-critical/40 bg-critical/10 px-3 py-2 text-sm text-critical">
      {error.message}
      {error.errors?.length ? (
        <ul className="mt-1 list-disc pl-5 text-xs">
          {error.errors.map((e, i) => <li key={i}>{e.loc.slice(1).join(".")}: {e.msg}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-ink-3">Loading…</div>;
}

export function A({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className="text-accent hover:underline">{children}</Link>;
}

export function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t} role="tab" aria-selected={t === active} onClick={() => onChange(t)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm", t === active ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink")}>
          {t}
        </button>
      ))}
    </div>
  );
}
