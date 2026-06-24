import type { ScreenerRow } from "./types";

const COLUMNS: { key: string; get: (r: ScreenerRow) => unknown }[] = [
  { key: "Ticker", get: (r) => r.ticker },
  { key: "Name", get: (r) => r.name },
  { key: "Branche", get: (r) => r.sector },
  { key: "Land", get: (r) => r.country },
  { key: "Klasse", get: (r) => r.asset_class },
  { key: "Preis", get: (r) => r.price },
  { key: "Waehrung", get: (r) => r.currency },
  { key: "Dividende", get: (r) => r.dividend_yield },
  { key: "WLATAR", get: (r) => r.wlatar },
  { key: "WLAFAR", get: (r) => r.wlafar },
  { key: "Gesamt", get: (r) => r.total_score },
  { key: "Rating", get: (r) => r.rating },
  { key: "Status", get: (r) => r.status },
  { key: "Risiko", get: (r) => r.risikoklasse },
  { key: "Strategie", get: (r) => r.strategy_tag },
  { key: "TrendLang", get: (r) => r.trend_long },
  { key: "Signal", get: (r) => r.targets.signal_aggr },
  { key: "Kursziel1", get: (r) => r.targets.target_1 },
  { key: "Kursziel2", get: (r) => r.targets.target_2 },
  { key: "CRV", get: (r) => r.targets.crv },
  { key: "Stand", get: (r) => r.data_as_of },
];

function esc(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function rowsToCsv(rows: ScreenerRow[]): string {
  const header = COLUMNS.map((c) => c.key).join(",");
  const lines = rows.map((r) => COLUMNS.map((c) => esc(c.get(r))).join(","));
  return [header, ...lines].join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  // BOM, damit Excel UTF-8 (Umlaute) korrekt erkennt.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
