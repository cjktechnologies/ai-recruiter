"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public errors?: { loc: (string | number)[]; msg: string }[],
    public extra?: Record<string, unknown>,
  ) {
    super(message);
  }
}

type Json = Record<string, unknown> | unknown[];

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Json | FormData;
  query?: Record<string, string | number | boolean | undefined | null | string[]>;
  idempotencyKey?: string;
}

export function qs(query: RequestOptions["query"]): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

const PUBLIC_PATHS = ["/login", "/careers", "/assessment", "/offer", "/reference", "/portal"];
const isStaffPath = (p: string) => !PUBLIC_PATHS.some((x) => p.startsWith(x));

/** All browser calls go through the Next.js BFF (/api/backend) which holds the session cookies. */
export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) body = opts.body;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  const res = await fetch(`/api/backend${path}${qs(opts.query)}`, { method: opts.method ?? "GET", headers, body });
  if (res.status === 401 && typeof window !== "undefined" && isStaffPath(window.location.pathname)) {
    window.location.assign(new URL(`/login?next=${encodeURIComponent(window.location.pathname)}`, window.location.origin));
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    const d = (data ?? {}) as { code?: string; detail?: string; title?: string; errors?: []; issues?: [] };
    throw new ApiError(res.status, d.code ?? "error", d.detail ?? d.title ?? res.statusText, d.errors, d as never);
  }
  return data as T;
}

export function newIdempotencyKey(prefix = "ui"): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/** Minimal data hook: loads on mount/when the path or query changes; exposes reload and error state. */
export function useApi<T>(path: string | null, query?: RequestOptions["query"]) {
  const key = path ? path + qs(query) : null;
  const [state, setState] = useState<{ key: string | null; data: T | null; error: ApiError | null }>({
    key: null, data: null, error: null,
  });
  const latest = useRef<string | null>(key);
  latest.current = key;
  const reload = useCallback(async () => {
    if (!path || !key) return;
    try {
      const d = await api<T>(path, { query });
      if (latest.current === key) setState({ key, data: d, error: null });
    } catch (e) {
      if (latest.current === key) setState((s) => ({ key, data: s.data, error: e as ApiError }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    void reload();
  }, [reload]);
  const setData = useCallback((d: T) => setState((s) => ({ ...s, data: d })), []);
  return { data: state.data, error: state.error, loading: key !== null && state.key !== key, reload, setData };
}
