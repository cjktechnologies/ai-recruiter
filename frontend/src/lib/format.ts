export const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";
export const fmtDateTime = (s?: string | null) =>
  s
    ? new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "—";
export const fmtMoney = (v?: string | number | null, currency = "USD") =>
  v === null || v === undefined || v === ""
    ? "—"
    : new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(v));
export const titleCase = (s?: string | null) =>
  (s ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const pct = (v?: number | null) => (v === null || v === undefined ? "—" : `${v.toFixed(1)}%`);
