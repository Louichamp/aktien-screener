// Statische Datenquelle: das Frontend liest die vom Export erzeugten JSON-Dateien
// (public/data/…) zur Laufzeit im Browser. Kein Backend nötig — Netlify-tauglich.

import type { Facets, ScreenerRow, ScreenerRowDetail } from "./types";

export interface ScreenerData {
  generated_at: string;
  total: number;
  items: ScreenerRow[];
  facets: Facets;
}

// Optionaler Pfad-Präfix, falls die Daten woanders liegen (sonst gleiche Origin).
const BASE = process.env.NEXT_PUBLIC_DATA_BASE?.replace(/\/$/, "") ?? "";

let _cache: ScreenerData | null = null;

export async function loadScreenerData(force = false): Promise<ScreenerData> {
  if (_cache && !force) return _cache;
  // Cache-Bust pro Tag-Stunde, damit ein Neuladen nach Redeploy frische JSON zieht.
  const v = Math.floor(Date.now() / 60000);
  const res = await fetch(`${BASE}/data/screener.json?v=${v}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`screener.json nicht gefunden (${res.status})`);
  _cache = await res.json();
  return _cache!;
}

export async function loadDetail(ticker: string): Promise<ScreenerRowDetail | null> {
  const t = ticker.toUpperCase();
  const res = await fetch(`${BASE}/data/detail/${encodeURIComponent(t)}.json`,
    { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}
