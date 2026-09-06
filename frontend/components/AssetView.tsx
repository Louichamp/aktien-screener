"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchNews, fetchTicker } from "@/lib/api";
import type { NewsItem, ScreenerRowDetail } from "@/lib/types";
import { fmtPrice, totalColor, fmtDate, fmtAge, ageColor } from "@/lib/format";
import { RecommendationBadge } from "@/components/Badges";
import KronosForecast from "@/components/tearsheet/KronosForecast";
import ScoreBreakdownPanel from "@/components/tearsheet/ScoreBreakdown";
import TechnicalDashboard from "@/components/tearsheet/TechnicalDashboard";
import FundamentalData from "@/components/tearsheet/FundamentalData";
import BullBearMemo from "@/components/tearsheet/BullBearMemo";
import NewsFeed from "@/components/tearsheet/NewsFeed";

export default function AssetView() {
  const params = useSearchParams();
  const ticker = (params.get("t") ?? "").toUpperCase();
  const [row, setRow] = useState<ScreenerRowDetail | null>(null);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [newsNote, setNewsNote] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "missing">("loading");

  useEffect(() => {
    if (!ticker) { setState("missing"); return; }
    // Bei Ticker-Wechsel (z.B. Browser-Vor/Zurück zwischen zwei /asset?t=X-URLs,
    // oder manuell in der Adresszeile) sofort zurück auf "loading" — sonst
    // bleibt das TEARSHEET DES VORHERIGEN TICKERS sichtbar, bis der neue Fetch
    // auflöst (row/state wurden vorher nicht zurückgesetzt).
    setState("loading");
    setRow(null);
    let cancelled = false;
    fetchTicker(ticker).then((d) => {
      if (cancelled) return;
      if (d) { setRow(d); setState("ok"); } else setState("missing");
    }).catch(() => { if (!cancelled) setState("missing"); });
    return () => { cancelled = true; };
  }, [ticker]);

  // Live-Nachrichten separat (eigener Endpoint, on-demand — nicht Teil des
  // Detail-Objekts wie im statischen Export-Modus).
  useEffect(() => {
    if (!ticker || state !== "ok") return;
    setNews([]);
    setNewsNote(null);
    fetchNews(ticker).then((r) => { setNews(r.items); setNewsNote(r.note ?? null); })
      .catch(() => setNews([]));
  }, [ticker, state]);

  if (state === "loading") {
    return <div className="mx-auto max-w-[920px] animate-pulse rounded-lg border border-edge bg-panel p-8">
      <div className="h-8 w-48 rounded bg-panel2" /><div className="mt-4 h-48 rounded bg-panel2/60" />
    </div>;
  }
  if (state === "missing" || !row) {
    return (
      <div className="mx-auto max-w-[920px] rounded-lg border border-edge bg-panel p-8">
        <Link href="/" className="text-xs text-muted hover:text-accent">‹ zurück zum Screener</Link>
        <p className="mt-4 text-slate-300">Kein Tearsheet für „{ticker || "—"}" gefunden.</p>
      </div>
    );
  }

  return (
    <article className="mx-auto max-w-[920px] animate-fadein rounded-lg border border-edge bg-panel px-8 py-6">
      <Link href="/" className="text-xs text-muted transition-colors hover:text-accent">‹ zurück zum Screener</Link>

      <header className="mt-3 border-b-2 border-slate-300/50 pb-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="font-serif text-4xl font-black tracking-tight text-slate-50">
              {row.name ?? row.ticker}
            </h1>
            <p className="font-serif text-sm italic text-muted">
              <span className="font-mono not-italic">{row.ticker}</span>
              {row.sector && <> · {row.sector}</>}
              {row.country && <> · {row.country}</>}
              {" "}· {row.status ?? "—"}
              {row.data_as_of && (
                <> · <span className={`not-italic ${ageColor(row.data_as_of)}`}>
                  Daten {fmtAge(row.data_as_of)} ({fmtDate(row.data_as_of)})</span></>
              )}
            </p>
          </div>
          <div className="text-right">
            <div className="font-mono text-2xl font-bold text-slate-100">
              {fmtPrice(row.price, row.currency)}
            </div>
            <div className="mt-1 flex items-center justify-end gap-2">
              <RecommendationBadge rating={row.rating} />
              <span className={`font-mono text-sm ${totalColor(row.total_score)}`}>
                {row.total_score ?? "—"}/100
              </span>
            </div>
          </div>
        </div>
      </header>

      <div className="py-6">
        <ScoreBreakdownPanel breakdown={row.score_breakdown} total={row.total_score} />
      </div>
      <div className="rule" />
      <div className="py-6"><KronosForecast row={row} /></div>
      <div className="rule" />
      <div className="grid grid-cols-1 gap-8 py-6 lg:grid-cols-2">
        <TechnicalDashboard row={row} />
        <FundamentalData row={row} />
      </div>
      <div className="rule-thick" />
      <div className="py-6"><BullBearMemo bull={row.drivers.bull} bear={row.drivers.bear} /></div>
      <div className="rule" />
      <div className="py-6"><NewsFeed items={news} note={newsNote} /></div>

      {row.drivers.status_note && (
        <p className="border-t border-edge pt-3 text-xs italic text-muted">
          Anmerkung: {row.drivers.status_note}
        </p>
      )}
    </article>
  );
}
