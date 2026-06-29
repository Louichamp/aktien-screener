"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { loadScreenerData, type ScreenerData } from "@/lib/staticData";
import { applyFilters, computeSummary, queryFromParams, sortRows } from "@/lib/clientQuery";
import { fmtAge, fmtDate } from "@/lib/format";
import type { ScreenerQuery, SortBy, SortDir } from "@/lib/types";
import FilterBar from "@/components/FilterBar";
import Pagination from "@/components/Pagination";
import ScreenerBoard from "@/components/ScreenerBoard";
import SummaryStrip from "@/components/SummaryStrip";
import Loading from "@/app/loading";

export default function ScreenerApp() {
  const params = useSearchParams();
  const [data, setData] = useState<ScreenerData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadScreenerData()
  .then(setData)
  .catch((e) => {
    console.error("loadScreenerData failed:", e);
    setError(String(e));
  });
  }, []);

  const query: ScreenerQuery = useMemo(() => queryFromParams(params), [params]);
  const limit = Math.min(Math.max(Number(params.get("limit")) || 25, 1), 500);
  const offset = Math.max(Number(params.get("offset")) || 0, 0);
  const sortBy = (params.get("sort_by") as SortBy) ?? "total_score";
  const descending = (params.get("sort_dir") as SortDir | null) !== "asc";

  const { pageRows, filtered, summary } = useMemo(() => {
    if (!data) return { pageRows: [], filtered: [], summary: null };
    const f = sortRows(applyFilters(data.items, query), sortBy, descending);
    return { pageRows: f.slice(offset, offset + limit), filtered: f, summary: computeSummary(f) };
  }, [data, query, sortBy, descending, limit, offset]);

  if (error) {
    return (
      <div className="rounded-lg border border-bear/40 bg-bear/10 p-6 text-bear">
        Daten nicht gefunden. Lege sie mit{" "}
        <code>python scripts/export_static.py</code> an (siehe README, Abschnitt „Deployment").
      </div>
    );
  }
  if (!data || !summary) return <Loading />;

  // Datenabdeckung (rollierend): neuester + ältester Stand über alle Werte.
  const stamps = data.items.map((r) => r.data_as_of).filter(Boolean) as string[];
  const newest = stamps.length ? stamps.reduce((a, b) => (a > b ? a : b)) : null;
  const oldest = stamps.length ? stamps.reduce((a, b) => (a < b ? a : b)) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">Screener</h1>
          <p className="text-sm text-muted">
            {data.total.toLocaleString("de-DE")} Instrumente · {summary.total.toLocaleString("de-DE")} Treffer ·
            Tippe eine Zeile für das Tearsheet
          </p>
        </div>
        <div className="text-right font-mono text-[11px] text-muted">
          <div>neuester Stand: {newest ? fmtDate(newest) : "—"}</div>
          {oldest && (
            <div>rollierend · ältester Wert: {fmtAge(oldest)} alt</div>
          )}
        </div>
      </div>

      <FilterBar facets={data.facets} />
      <SummaryStrip summary={summary} />
      <ScreenerBoard rows={pageRows} exportRows={filtered} />
      <Pagination total={filtered.length} limit={limit} offset={offset} />
    </div>
  );
}
