// Zentrales API-Fetch-Handling für die FastAPI-Lese-Schicht.
// Filter/Sort/Pagination werden als Query-Parameter an /api/v1/screener gereicht
// — die DB erledigt WHERE/ORDER BY/LIMIT/OFFSET (siehe api/queries.py).

import type {
  Facets,
  NewsResponse,
  ScreenerListResponse,
  ScreenerQuery,
  ScreenerRowDetail,
  Summary,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

function buildQuery(q: ScreenerQuery): string {
  const sp = new URLSearchParams();
  const set = (k: string, v: unknown) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  };
  set("search", q.search);
  set("strategy", q.strategy);
  set("risk_class", q.risk_class);
  set("sector", q.sector);
  set("country", q.country);
  set("asset_class", q.asset_class);
  set("status", q.status);
  set("rating", q.rating);
  set("trend_long", q.trend_long);
  set("trend_medium", q.trend_medium);
  set("min_total_score", q.min_total_score);
  set("min_wlatar", q.min_wlatar);
  set("min_wlafar", q.min_wlafar);
  set("min_dividend_yield", q.min_dividend_yield);
  set("max_risk_level", q.max_risk_level);
  set("tickers", q.tickers);
  set("sort_by", q.sort_by);
  set("sort_dir", q.sort_dir);
  sp.set("limit", String(q.limit ?? 25));
  sp.set("offset", String(q.offset ?? 0));
  return sp.toString();
}

export async function fetchScreener(q: ScreenerQuery): Promise<ScreenerListResponse> {
  const res = await fetch(`${API_BASE}/api/v1/screener?${buildQuery(q)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Screener-Liste fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchFacets(): Promise<Facets> {
  const res = await fetch(`${API_BASE}/api/v1/screener/facets`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Facetten fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchSummary(q: ScreenerQuery): Promise<Summary> {
  const res = await fetch(`${API_BASE}/api/v1/screener/summary?${buildQuery(q)}`,
    { cache: "no-store" });
  if (!res.ok) throw new Error(`Summary fehlgeschlagen: ${res.status}`);
  return res.json();
}

// Für den CSV-Export: ruft die API mit aktuellen Filtern, aber großer Seite.
export async function fetchScreenerAll(q: ScreenerQuery, cap = 1000): Promise<ScreenerListResponse> {
  return fetchScreener({ ...q, limit: Math.min(cap, 500), offset: 0 });
}

export async function fetchTicker(ticker: string): Promise<ScreenerRowDetail | null> {
  const res = await fetch(`${API_BASE}/api/v1/screener/${encodeURIComponent(ticker)}`,
    { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Detail fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchNews(ticker: string): Promise<NewsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/screener/${encodeURIComponent(ticker)}/news`,
    { cache: "no-store" });
  if (!res.ok) throw new Error(`News fehlgeschlagen: ${res.status}`);
  return res.json();
}
