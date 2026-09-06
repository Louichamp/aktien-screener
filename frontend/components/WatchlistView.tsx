"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchWatchlist } from "@/lib/api";
import type { SectorRank, WatchCandidate, WatchlistResponse } from "@/lib/types";
import { fmtPrice, fmtDate, qualityColor, totalColor } from "@/lib/format";
import { SignalBadge } from "@/components/Badges";
import Loading from "@/app/loading";

// Die Wochen-Watchlist nach der Vier-Schritte-Methodik: erst der Markt, dann
// die Sektoren, dann die Titel — geordnet nach Priorität.
//
// Der Aufbau folgt bewusst der Lesereihenfolge eines Fünf-Minuten-Blicks:
// ganz oben, was den Rahmen setzt, darunter die Kandidaten, bei denen als
// Nächstes etwas passieren könnte.

const PRIO = {
  1: { titel: "Priorität 1", unter: "Kurz vor dem Einstieg",
       ring: "ring-bull/40", text: "text-bull", bg: "bg-bull/10" },
  2: { titel: "Priorität 2", unter: "Nahe am relevanten Bereich",
       ring: "ring-warn/40", text: "text-warn", bg: "bg-warn/10" },
  3: { titel: "Priorität 3", unter: "Noch weiter entfernt",
       ring: "ring-edge", text: "text-muted", bg: "bg-panel2/60" },
} as const;

function VerdictBadge({ v }: { v: string | null }) {
  const cls = v === "freundlich" || v === "stark" ? "bg-bull/15 text-bull ring-bull/40"
    : v === "defensiv" || v === "schwach" ? "bg-bear/15 text-bear ring-bear/40"
    : "bg-warn/15 text-warn ring-warn/40";
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ring-1 ring-inset ${cls}`}>
      {v ?? "—"}
    </span>
  );
}

function SectorRow({ s, max }: { s: SectorRank; max: number }) {
  const w = max > 0 ? (s.median_score / max) * 100 : 0;
  return (
    <li className="flex items-center gap-2 py-1 sm:gap-3">
      <span className="w-4 shrink-0 text-right font-mono text-[11px] text-muted">{s.rank}</span>
      <span className="min-w-0 flex-1 truncate text-xs text-slate-300 sm:w-44 sm:flex-none"
            title={s.sector}>
        {s.sector}
      </span>
      {/* Der Balken ist Beiwerk — auf schmalen Geräten weicht er den Zahlen. */}
      <span className="relative hidden h-1.5 flex-1 overflow-hidden rounded-full bg-edge/50 sm:block">
        <span
          className={`absolute inset-y-0 left-0 rounded-full ${
            s.verdict === "stark" ? "bg-bull" : s.verdict === "schwach" ? "bg-bear/70" : "bg-warn/70"}`}
          style={{ width: `${Math.max(2, w)}%` }}
        />
      </span>
      <span className="shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
        <span className="font-semibold text-slate-300">{s.median_score.toFixed(0)}</span>
        {" · "}{(s.share_uptrend * 100).toFixed(0)}%
        {" · "}{s.n_candidates}
      </span>
    </li>
  );
}

function CandidateCard({ c }: { c: WatchCandidate }) {
  const p = PRIO[(c.priority as 1 | 2 | 3)] ?? PRIO[3];
  return (
    <li className={`rounded-lg border border-edge bg-panel p-3 ring-1 ring-inset ${p.ring}`}>
      <div className="flex items-start justify-between gap-3">
        <Link href={`/asset?t=${encodeURIComponent(c.ticker)}`} className="group min-w-0">
          <div className="truncate font-semibold text-slate-100 group-hover:text-accent">
            {c.name ?? c.ticker}
          </div>
          <div className="font-mono text-[11px] text-muted">
            {c.ticker}{c.sector && <> · {c.sector}</>}
          </div>
        </Link>
        <div className="shrink-0 text-right">
          <div className="font-mono text-sm font-bold text-slate-100">
            {fmtPrice(c.price, c.currency)}
          </div>
          <div className={`font-mono text-xs font-bold ${totalColor(c.total_score)}`}>
            {c.total_score ?? "—"}/100
          </div>
        </div>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-slate-400">{c.reason}</p>

      {(c.buy_zone_low || c.stop) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-edge/60 pt-2 font-mono text-[11px] tabular-nums">
          {c.buy_zone_low != null && (
            <span className="text-accent">
              Kaufzone {c.buy_zone_low.toFixed(2)}
              {c.buy_zone_high != null && `–${c.buy_zone_high.toFixed(2)}`}
            </span>
          )}
          {c.stop != null && <span className="text-bear">Stopp {c.stop.toFixed(2)}</span>}
          {c.risk_pct != null && (
            <span className="text-muted">Risiko {(c.risk_pct * 100).toFixed(1)} %</span>
          )}
          {c.dist_to_pivot_pct != null && c.dist_to_pivot_pct > 0 && (
            <span className="text-muted">noch {c.dist_to_pivot_pct.toFixed(1)} %</span>
          )}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <SignalBadge strength={c.signal_strength} />
        {c.data_quality != null && (
          <span className={`font-mono ${qualityColor(c.data_quality)}`}
                title="Belastbarkeit der Datengrundlage">
            Daten {c.data_quality}
          </span>
        )}
        {c.status && <span className="text-muted">{c.status}</span>}
        {c.liquidity_segment && (
          <span className="text-muted" title="Tagesumsatz-Segment">{c.liquidity_segment}</span>
        )}
      </div>
    </li>
  );
}

export default function WatchlistView() {
  const [data, setData] = useState<WatchlistResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [week, setWeek] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchWatchlist(week || undefined)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [week]);

  if (error) {
    return (
      <div className="rounded-lg border border-bear/40 bg-bear/10 p-6 text-bear">
        Watchlist nicht erreichbar.
        <div className="mt-1 font-mono text-xs opacity-70">{error}</div>
      </div>
    );
  }
  if (!data) return <Loading />;

  if (!data.generated_at) {
    return (
      <div className="rounded-lg border border-edge bg-panel p-8 text-center">
        <h1 className="font-serif text-xl font-bold text-slate-100">Wochen-Watchlist</h1>
        <p className="mt-2 text-sm text-muted">{data.note}</p>
      </div>
    );
  }

  const m = data.market;
  const maxScore = Math.max(...data.sectors.map((s) => s.median_score), 1);

  return (
    <div className="space-y-5">
      {/* Kopf */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">
            Watchlist · {data.week_label}
          </h1>
          <p className="text-sm text-muted">
            {data.candidates.length} Kandidaten aus {data.passed_filter.toLocaleString("de-DE")} gefilterten
            {" "}von {data.universe_size.toLocaleString("de-DE")} Instrumenten
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data.available_weeks.length > 1 && (
            <select
              value={week}
              onChange={(e) => { setData(null); setWeek(e.target.value); }}
              className="rounded border border-edge bg-panel2 px-2 py-1.5 text-sm text-slate-200 focus:border-accent focus:outline-none"
            >
              <option value="">neueste</option>
              {data.available_weeks.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          )}
          <span className="font-mono text-[11px] text-muted">
            erstellt {fmtDate(data.generated_at)}
          </span>
        </div>
      </div>

      {/* Schritt 1: Marktüberblick */}
      <section className="rounded-lg border border-edge bg-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-serif text-lg font-bold text-slate-100">Marktüberblick</h2>
          <VerdictBadge v={m.breadth_verdict} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ["im Aufwärtstrend", `${(m.share_uptrend * 100).toFixed(0)} %`, "text-bull"],
            ["im Abwärtstrend", `${(m.share_downtrend * 100).toFixed(0)} %`, "text-bear"],
            ["Median-Score", m.median_score.toFixed(0), "text-slate-200"],
            ["Instrumente", m.n_total.toLocaleString("de-DE"), "text-slate-200"],
          ].map(([label, wert, cls]) => (
            <div key={label as string}>
              <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
              <div className={`font-mono text-lg font-bold ${cls}`}>{wert}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs leading-relaxed text-slate-400">{m.note}</p>
      </section>

      {/* Schritt 2: Sektoren */}
      <section className="rounded-lg border border-edge bg-panel p-4">
        <div className="mb-2 flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between">
          <h2 className="font-serif text-lg font-bold text-slate-100">Sektoren</h2>
          <span className="font-mono text-[11px] text-muted">
            Median-Score · Aufwärtstrend · Kandidaten
          </span>
        </div>
        <ul>{data.sectors.map((s) => <SectorRow key={s.sector} s={s} max={maxScore} />)}</ul>
        <p className="mt-3 text-[11px] leading-relaxed text-muted">
          Die drei bestbewerteten Sektoren werden bei der Titelauswahl bevorzugt —
          erst der Sektor, dann die Aktie.
        </p>
      </section>

      {/* Schritt 3/4: Kandidaten nach Priorität */}
      {([1, 2, 3] as const).map((p) => {
        const ks = data.candidates.filter((c) => c.priority === p);
        if (ks.length === 0) return null;
        const meta = PRIO[p];
        return (
          <section key={p}>
            <div className={`mb-2 flex items-baseline gap-3 rounded-md px-3 py-1.5 ${meta.bg}`}>
              <h2 className={`font-serif text-lg font-bold ${meta.text}`}>{meta.titel}</h2>
              <span className="text-xs text-muted">{meta.unter}</span>
              <span className="ml-auto font-mono text-xs text-muted">{ks.length}</span>
            </div>
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {ks.map((c) => <CandidateCard key={c.ticker} c={c} />)}
            </ul>
          </section>
        );
      })}

      {/* Der zentrale Vorbehalt aus dem Guide */}
      <p className="rounded-lg border border-warn/30 bg-warn/10 px-4 py-3 text-xs leading-relaxed text-warn">
        <strong>Priorität ≠ Trade.</strong> {data.note?.replace("Priorität ≠ Trade. ", "")}
      </p>
      <p className="text-[11px] leading-relaxed text-muted">
        Die Liste entsteht montags automatisch aus den Screener-Daten und wird nicht
        von Hand kuratiert. Sie sagt nicht, welche Aktien steigen — sie zeigt, wo sich
        laut den vorliegenden Daten am ehesten ein Setup entwickeln könnte. Im
        Walk-Forward-Test lag der Unterschied zwischen starken und schwachen Signalen
        bei rund einem Prozentpunkt über 60 Handelstage: eine Tendenz, kein Beweis.
      </p>
    </div>
  );
}
