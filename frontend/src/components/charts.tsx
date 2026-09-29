"use client";

/**
 * Minimal, accessible single-series charts. One hue (series-1) encodes magnitude; values are
 * direct-labelled, every bar has a hover tooltip, and each chart can toggle to a table view.
 */
import { useState } from "react";

export interface Datum {
  label: string;
  value: number;
  hint?: string;
}

function TableView({ data, unit }: { data: Datum[]; unit?: string }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {data.map((d) => (
          <tr key={d.label} className="border-b border-line last:border-0">
            <td className="py-1 text-ink-2">{d.label}</td>
            <td className="py-1 text-right tabular-nums">{d.value}{unit}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BarList({ data, unit = "", title }: { data: Datum[]; unit?: string; title: string }) {
  const [table, setTable] = useState(false);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <figure aria-label={title}>
      <div className="mb-2 flex justify-end">
        <button className="text-xs text-ink-3 hover:text-ink" onClick={() => setTable(!table)}>{table ? "Chart" : "Table"}</button>
      </div>
      {table ? <TableView data={data} unit={unit} /> : (
        <ul className="space-y-1.5">
          {data.map((d) => (
            <li key={d.label} className="group grid grid-cols-[8rem_1fr_3.5rem] items-center gap-2 text-sm"
              title={`${d.label}: ${d.value}${unit}${d.hint ? ` — ${d.hint}` : ""}`}>
              <span className="truncate text-ink-2">{d.label}</span>
              <span className="h-3.5 rounded-r bg-surface-2">
                <span className="block h-full rounded-r-[4px] bg-[var(--series-1)] transition-opacity group-hover:opacity-80"
                  style={{ width: `${(d.value / max) * 100}%` }} />
              </span>
              <span className="text-right tabular-nums text-ink">{d.value}{unit}</span>
            </li>
          ))}
          {data.length === 0 && <li className="text-sm text-ink-3">No data</li>}
        </ul>
      )}
    </figure>
  );
}

export function ColumnChart({ data, title, height = 140 }: { data: Datum[]; title: string; height?: number }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <figure aria-label={title}>
      <div className="mb-2 flex justify-end">
        <button className="text-xs text-ink-3 hover:text-ink" onClick={() => setTable(!table)}>{table ? "Chart" : "Table"}</button>
      </div>
      {table ? <TableView data={data} /> : (
        <div className="relative">
          <div className="flex items-end gap-[2px] border-b border-line" style={{ height }}>
            {data.map((d, i) => (
              <div key={d.label} className="flex h-full max-w-12 flex-1 items-end" onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} tabIndex={0}
                aria-label={`${d.label}: ${d.value}`}>
                <div className="w-full rounded-t-[4px] bg-[var(--series-1)]"
                  style={{ height: `${(d.value / max) * 100}%`, opacity: hover === null || hover === i ? 1 : 0.55 }} />
              </div>
            ))}
          </div>
          {hover !== null && data[hover] && (
            <div className="pointer-events-none absolute -top-2 right-0 rounded border border-line bg-surface px-2 py-1 text-xs shadow">
              <span className="text-ink-2">{data[hover].label}</span> <span className="font-medium tabular-nums">{data[hover].value}</span>
            </div>
          )}
          <div className="mt-1 flex justify-between text-[11px] text-ink-3">
            <span>{data[0]?.label}</span>
            <span>{data[data.length - 1]?.label}</span>
          </div>
        </div>
      )}
    </figure>
  );
}
