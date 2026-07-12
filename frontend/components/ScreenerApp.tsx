"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchFacets, fetchScreener, fetchScreenerAll, fetchSummary } from "@/lib/api";
import { queryFromParams } from "@/lib/clientQuery";
import { fmtAge, fmtDate } from "@/lib/format";
import type { Facets, ScreenerQuery, ScreenerRow, SortBy, SortDir, Summary } from "@/lib/types";
import FilterBar from "@/components/FilterBar";
import Pagination from "@/components/Pagination";
import ScreenerBoard from "@/components/ScreenerBoard";
import SummaryStrip from "@/components/SummaryStrip";
import Loading from "@/app/loading";

// Live-API-Modus: Filter/Sort/Pagination laufen serverseitig (api/queries.py
// macht WHERE/ORDER BY/LIMIT/OFFSET auf der DB) — das Frontend hält nur noch
// die aktuelle Seite im State, nicht mehr das gesamte Universum im Browser.
export default function ScreenerApp() {
  const params = useSearchParams();
  const [rows, setRows] = useState<ScreenerRow[] | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [total, setTotal] = useState(0);
  const [exportRows, setExportRows] = useState<ScreenerRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const query: ScreenerQuery = useMemo(() => queryFromParams(params), [params]);
  const limit = Math.min(Math.max(Number(params.get("limit")) || 25, 1), 500);
  const offset = Math.max(Number(params.get("offset")) || 0, 0);
  const sortBy = (params.get("sort_by") as SortBy) ?? "total_score";
  const sortDir: SortDir = (params.get("sort_dir") as SortDir | null) ?? "desc";
  const fullQuery: ScreenerQuery = { ...query, sort_by: sortBy, sort_dir: sortDir, limit, offset };

  // Facetten einmalig laden (ändern sich nicht mit Filtern/Pagination).
  useEffect(() => {
    fetchFacets().then(setFacets).catch((e) => {
      console.error("fetchFacets failed:", e);
      setError(String(e));
    });
  }, []);

  // Zeilen + Summary serverseitig neu holen, sobald sich Query/Sort/Page ändert.
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchScreener(fullQuery), fetchSummary(query)])
      .then(([list, sum]) => {
        if (cancelled) return;
        setRows(list.items);
        setTotal(list.total);
        setSummary(sum);
      })
      .catch((e) => {
        if (cancelled) return;
        console.error("fetchScreener/fetchSummary failed:", e);
        setError(String(e));
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(fullQuery)]);

  // CSV-Export braucht die volle gefilterte Menge, nicht nur die aktuelle Seite.
  useEffect(() => {
    fetchScreenerAll(query).then((r) => setExportRows(r.items)).catch(() => setExportRows([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(query)]);

  if (error) {
    return (
      <div className="rounded-lg border border-bear/40 bg-bear/10 p-6 text-bear">
        API nicht erreichbar. Prüfe <code>NEXT_PUBLIC_API_BASE</code> und ob das Backend läuft.
        <div className="mt-1 font-mono text-xs opacity-70">{error}</div>
      </div>
    );
  }
  if (!rows || !facets || !summary) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">Screener</h1>
          <p className="text-sm text-muted">
            {facets.total.toLocaleString("de-DE")} Instrumente · {summary.total.toLocaleString("de-DE")} Treffer ·
            Tippe eine Zeile für das Tearsheet
          </p>
        </div>
        <div className="text-right font-mono text-[11px] text-muted">
          <div>neuester Stand: {summary.newest_data_as_of ? fmtDate(summary.newest_data_as_of) : "—"}</div>
          {summary.oldest_data_as_of && (
            <div>rollierend · ältester Wert: {fmtAge(summary.oldest_data_as_of)} alt</div>
          )}
        </div>
      </div>

      <FilterBar facets={facets} />
      <SummaryStrip summary={summary} />
      <ScreenerBoard rows={rows} exportRows={exportRows} />
      <Pagination total={total} limit={limit} offset={offset} />
    </div>
  );
}
