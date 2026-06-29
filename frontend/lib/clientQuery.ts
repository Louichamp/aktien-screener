// Client-seitiges Filtern/Sortieren/Paginieren — spiegelt api/queries.py, damit
// die statische Seite sich exakt wie der Live-Screener verhält (für 5.000+ Zeilen
// im Browser problemlos schnell).

import type { ScreenerQuery, ScreenerRow, SortBy, Summary } from "./types";

const RISK_LEVEL: Record<string, number> = {
  "sehr niedrig": 1, niedrig: 2, mittel: 3, hoch: 4, "sehr hoch": 5,
};

const SORT_ACCESS: Record<SortBy, (r: ScreenerRow) => string | number | null> = {
  ticker: (r) => r.ticker,
  name: (r) => r.name,
  sector: (r) => r.sector,
  country: (r) => r.country,
  price: (r) => r.price,
  dividend_yield: (r) => r.dividend_yield,
  wlatar: (r) => r.wlatar,
  wlafar: (r) => r.wlafar,
  total_score: (r) => r.total_score,
  rating: (r) => r.rating,
  status: (r) => r.status,
  strategy: (r) => r.strategy_tag,
  risk_class: (r) => r.risikoklasse,
  data_as_of: (r) => r.data_as_of,
  updated_at: (r) => r.updated_at,
  chance_dots: (r) => r.targets.chance_dots,
};

export function applyFilters(items: ScreenerRow[], q: ScreenerQuery): ScreenerRow[] {
  const search = q.search?.trim().toLowerCase();
  const tickers = q.tickers
    ? new Set(q.tickers.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean))
    : null;
  const maxRisk = q.max_risk_level ?? null;

  return items.filter((r) => {
    if (search && !(`${r.name ?? ""} ${r.ticker}`.toLowerCase().includes(search))) return false;
    if (q.strategy && r.strategy_tag !== q.strategy) return false;
    if (q.risk_class && r.risikoklasse !== q.risk_class) return false;
    if (q.sector && r.sector !== q.sector) return false;
    if (q.country && r.country !== q.country) return false;
    if (q.asset_class && r.asset_class !== q.asset_class) return false;
    if (q.status && r.status !== q.status) return false;
    if (q.rating && r.rating !== q.rating) return false;
    if (q.trend_long && r.trend_long !== q.trend_long) return false;
    if (q.min_total_score != null && (r.total_score ?? -1) < q.min_total_score) return false;
    if (q.min_wlatar != null && (r.wlatar ?? -1) < q.min_wlatar) return false;
    if (q.min_wlafar != null && (r.wlafar ?? -1) < q.min_wlafar) return false;
    if (q.min_dividend_yield != null && (r.dividend_yield ?? -1) < q.min_dividend_yield) return false;
    if (maxRisk != null && (RISK_LEVEL[r.risikoklasse ?? ""] ?? 99) > maxRisk) return false;
    if (tickers && !tickers.has(r.ticker)) return false;
    if (q.rare_only) {
      const rarity = r.chance_rarity ?? "";
      if (rarity !== "selten" && rarity !== "sehr selten") return false;
      if (r.rating !== "KAUFEN" && r.rating !== "STARK KAUFEN") return false;
    }
    return true;
  });
}

export function sortRows(items: ScreenerRow[], sortBy: SortBy, descending: boolean): ScreenerRow[] {
  const get = SORT_ACCESS[sortBy] ?? SORT_ACCESS.total_score;
  const dir = descending ? -1 : 1;
  return items.slice().sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    // NULLS LAST (unabhängig von der Richtung)
    if (va == null && vb == null) return a.ticker.localeCompare(b.ticker);
    if (va == null) return 1;
    if (vb == null) return -1;
    let cmp: number;
    if (typeof va === "number" && typeof vb === "number") cmp = va - vb;
    else cmp = String(va).localeCompare(String(vb));
    if (cmp !== 0) return cmp * dir;
    return a.ticker.localeCompare(b.ticker);          // stabiler Tie-Break
  });
}

export function computeSummary(filtered: ScreenerRow[]): Summary {
  const by_rating: Record<string, number> = {};
  let sum = 0;
  let n = 0;
  for (const r of filtered) {
    if (r.rating) by_rating[r.rating] = (by_rating[r.rating] ?? 0) + 1;
    if (r.total_score != null) { sum += r.total_score; n++; }
  }
  return {
    total: filtered.length,
    avg_total_score: n ? Math.round((sum / n) * 10) / 10 : null,
    by_rating,
  };
}

export function queryFromParams(p: URLSearchParams): ScreenerQuery {
  const numKeys = new Set(["min_total_score", "min_dividend_yield", "max_risk_level",
    "min_wlatar", "min_wlafar", "limit", "offset"]);
  const boolKeys = new Set(["rare_only"]);
  const q: Record<string, unknown> = {};
  p.forEach((v, k) => {
    if (v === "") return;
    if (boolKeys.has(k)) { q[k] = v === "1" || v === "true"; return; }
    q[k] = numKeys.has(k) ? Number(v) : v;
  });
  return q as ScreenerQuery;
}
