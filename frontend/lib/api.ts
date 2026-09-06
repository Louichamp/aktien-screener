// Zentrales API-Fetch-Handling für die FastAPI-Lese-Schicht.
// Filter/Sort/Pagination werden als Query-Parameter an /api/v1/screener gereicht
// — die DB erledigt WHERE/ORDER BY/LIMIT/OFFSET (siehe api/queries.py).
//
// Backend ist ein EIGENES, zweites Vercel-Projekt (Root Directory = Repo-Root,
// api/main.py läuft dort unverändert), NICHT im selben Projekt wie dieses
// Frontend — next.config.mjs proxied per rewrites() zu dessen URL
// (BACKEND_URL). Der Browser sieht dadurch trotzdem nur EINE Origin (dieses
// Frontend), daher kein CORS-Problem — aber same-origin kommt vom Next.js-
// Server-Proxy, nicht davon, dass Backend+Frontend dasselbe Deployment wären.
// NEXT_PUBLIC_API_BASE bleibt nur für lokale Entwicklung ohne diesen Proxy
// (z. B. separat laufendes `uvicorn api.main:app`) relevant.

import type {
  Facets,
  ScreenerRow,
  NewsResponse,
  ScreenerListResponse,
  ScreenerQuery,
  ScreenerRowDetail,
  Summary,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";

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
  if (q.rare_only) sp.set("rare_only", "true");
  set("min_signal", q.min_signal);
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

// Facetten aendern sich nur nach einem Pipeline-Lauf. `no-store` hier hiess:
// jeder Seitenwechsel holt dieselbe Liste erneut. Der Cache-Control-Header des
// Backends (private, 10 min) darf jetzt greifen.
export async function fetchFacets(): Promise<Facets> {
  const res = await fetch(`${API_BASE}/api/v1/screener/facets`);
  if (!res.ok) throw new Error(`Facetten fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchSummary(q: ScreenerQuery): Promise<Summary> {
  const res = await fetch(`${API_BASE}/api/v1/screener/summary?${buildQuery(q)}`,
    { cache: "no-store" });
  if (!res.ok) throw new Error(`Summary fehlgeschlagen: ${res.status}`);
  return res.json();
}

// Für den CSV-Export: holt ALLE zur Filterung passenden Zeilen, nicht nur eine
// Seite. api/routes.py deckelt `limit` hart auf 500 (Performance-Schutz für den
// normalen Listen-Endpoint) — ein einzelner fetchScreener-Call kappte den Export
// still bei 500 Zeilen, in Backend-Sortierung statt der auf dem Bildschirm
// gewählten.
//
// Wird NUR beim Klick auf „CSV" aufgerufen (ScreenerBoard). Früher lief das
// vorsorglich bei jeder Filter-/Sortier-/Seitenänderung im Hintergrund.
//
// Die Folgeseiten laufen PARALLEL: Nach der ersten Antwort ist `total` bekannt,
// also stehen alle Offsets fest. Sequenziell kostete ein 5366-Zeilen-Export
// 11 × Round-Trip (~18 s gemessen); parallel ist es effektiv ein Round-Trip.
// `concurrency` begrenzt die gleichzeitigen Anfragen, damit ein großer Export
// die Serverless-Funktion nicht überfährt.
export async function fetchScreenerAll(
  q: ScreenerQuery, cap = 10_000, concurrency = 4,
): Promise<ScreenerListResponse> {
  const pageSize = 500;
  const first = await fetchScreener({ ...q, limit: pageSize, offset: 0 });
  const target = Math.min(first.total, cap);
  if (first.items.length >= target) return { ...first, limit: first.items.length };

  const offsets: number[] = [];
  for (let o = pageSize; o < target; o += pageSize) offsets.push(o);

  const pages: ScreenerRow[][] = new Array(offsets.length);
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const i = cursor++;
      if (i >= offsets.length) return;
      const page = await fetchScreener({ ...q, limit: pageSize, offset: offsets[i] });
      pages[i] = page.items;
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, offsets.length) }, worker));

  const items = [...first.items, ...pages.flat().filter(Boolean)];
  return { ...first, items, limit: items.length };
}

export async function fetchTicker(ticker: string): Promise<ScreenerRowDetail | null> {
  // Tearsheets aendern sich einmal taeglich — Zurueck/Vor zwischen Aktien soll
  // nicht jedes Mal die Datenbank treffen (Backend-Header: private, 5 min).
  const res = await fetch(`${API_BASE}/api/v1/screener/${encodeURIComponent(ticker)}`);
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
