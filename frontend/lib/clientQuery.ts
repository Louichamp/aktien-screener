// URL-Query-Parameter -> ScreenerQuery. Filterung/Sortierung/Pagination laufen
// im Live-API-Modus serverseitig (api/queries.py); dieser Helfer bleibt, weil
// sowohl ScreenerApp.tsx (Board) als auch die API-Aufrufe dieselbe Query-Form
// aus der URL brauchen.

import type { ScreenerQuery } from "./types";

export function queryFromParams(p: URLSearchParams): ScreenerQuery {
  const numKeys = new Set(["min_total_score", "min_dividend_yield", "max_risk_level",
    "min_wlatar", "min_wlafar", "limit", "offset", "min_data_quality"]);
  const boolKeys = new Set(["rare_only"]);
  const q: Record<string, unknown> = {};
  p.forEach((v, k) => {
    if (v === "") return;
    if (boolKeys.has(k)) { q[k] = v === "1" || v === "true"; return; }
    q[k] = numKeys.has(k) ? Number(v) : v;
  });
  return q as ScreenerQuery;
}
