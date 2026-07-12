"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import type { ScreenerRow, SortBy } from "@/lib/types";
import {
  fmtPrice, fmtNum, fmtPct, fmtDate, fmtAge, ageColor, totalColor, ASSET_LABEL,
} from "@/lib/format";
import { getFavorites, toggleFavorite } from "@/lib/favorites";
import { rowsToCsv, downloadCsv } from "@/lib/csv";
import {
  RatingBadge, RecommendationBadge, StrategyTag, RarityDots,
  BatteryBadge, TrendBadge, RiskDots,
} from "./Badges";
import SortHeader from "./SortHeader";

interface Col {
  key: string;
  label: string;
  title?: string;
  align?: "left" | "right" | "center";
  sort?: SortBy;
  defaultOn: boolean;
  render: (r: ScreenerRow) => ReactNode;
}

const COLS: Col[] = [
  { key: "sector", label: "Branche", align: "left", sort: "sector", defaultOn: true,
    render: (r) => r.sector ?? "—" },
  { key: "country", label: "Land", align: "left", sort: "country", defaultOn: false,
    render: (r) => r.country ?? "—" },
  { key: "asset_class", label: "Klasse", align: "left", defaultOn: false,
    render: (r) => ASSET_LABEL[r.asset_class ?? ""] ?? r.asset_class ?? "—" },
  { key: "price", label: "Kurs", align: "right", sort: "price", defaultOn: true,
    render: (r) => <span className="font-mono tabular-nums">{fmtPrice(r.price, r.currency)}</span> },
  { key: "dividend_yield", label: "Dividende", align: "right", sort: "dividend_yield", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums">{fmtPct(r.dividend_yield)}</span> },
  { key: "total_score", label: "Gesamt", title: "Gesamtrating 0–100", align: "right", sort: "total_score", defaultOn: true,
    render: (r) => <span className={`font-mono text-base font-bold tabular-nums ${totalColor(r.total_score)}`}>{r.total_score ?? "—"}</span> },
  { key: "rating", label: "Rating", align: "center", sort: "rating", defaultOn: true,
    render: (r) => <RecommendationBadge rating={r.rating} /> },
  { key: "wlatar", label: "WLATAR", title: "WLATAR – Technisches Rating (0–10)", align: "center", sort: "wlatar", defaultOn: true,
    render: (r) => <BatteryBadge value={r.wlatar} /> },
  { key: "wlafar", label: "WLAFAR", title: "WLAFAR – Fundamentales Rating (0–10)", align: "center", sort: "wlafar", defaultOn: true,
    render: (r) => <BatteryBadge value={r.wlafar} /> },
  { key: "trend_long", label: "Langfr. Trend", align: "center", defaultOn: true,
    render: (r) => <TrendBadge trend={r.trend_long} /> },
  { key: "trend_medium", label: "Mittelfr. Trend", align: "center", defaultOn: true,
    render: (r) => <TrendBadge trend={r.trend_medium} /> },
  { key: "status", label: "Status", align: "left", sort: "status", defaultOn: true,
    render: (r) => <span className="text-slate-300">{r.status ?? "—"}</span> },
  { key: "risikoklasse", label: "Risiko", title: "Risikoklasse (sehr niedrig – sehr hoch)", align: "center", sort: "risk_class", defaultOn: true,
    render: (r) => <RiskDots risk={r.risikoklasse} /> },
  { key: "strategy", label: "Strategie", align: "left", sort: "strategy", defaultOn: true,
    render: (r) => <StrategyTag tag={r.strategy_tag} /> },
  { key: "chance", label: "Chance", title: "Chance-Bewertung (Seltenheit des Setups)", align: "center", sort: "chance_dots", defaultOn: true,
    render: (r) => <RarityDots rarity={r.chance_rarity} /> },
  { key: "rarity", label: "Seltenheit", align: "left", defaultOn: false,
    render: (r) => <span className="text-muted">{r.chance_rarity ?? "—"}</span> },
  { key: "signal_aggr", label: "Signal (aggr.)", title: "Aggressives Einstiegssignal", align: "right", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums text-accent">{fmtPrice(r.targets.signal_aggr, r.currency)}</span> },
  { key: "signal_kons", label: "Signal (kons.)", title: "Konservatives Einstiegssignal", align: "right", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums text-accent">{fmtPrice(r.targets.signal_kons, r.currency)}</span> },
  { key: "target_1", label: "Kursziel 1", align: "right", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums text-bull">{fmtPrice(r.targets.target_1, r.currency)}</span> },
  { key: "target_2", label: "Kursziel 2", align: "right", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums text-bull">{fmtPrice(r.targets.target_2, r.currency)}</span> },
  { key: "crv", label: "CRV", title: "Chance-Risiko-Verhältnis", align: "right", defaultOn: false,
    render: (r) => <span className="font-mono tabular-nums">{fmtNum(r.targets.crv)}</span> },
  { key: "forecast_return", label: "Prognose", title: "Erwartete Rendite bis Prognose-Ende", align: "right", defaultOn: false,
    render: (r) => {
      const v = r.targets.forecast_return;
      return v == null
        ? <span className="text-muted">—</span>
        : <span className={`font-mono tabular-nums ${v >= 0 ? "text-bull" : "text-bear"}`}>
            {v >= 0 ? "+" : ""}{(v * 100).toFixed(1)}%
          </span>;
    } },
  { key: "data_as_of", label: "Stand", title: "Alter der Daten dieses Werts", align: "right", sort: "data_as_of", defaultOn: true,
    render: (r) => <span className={ageColor(r.data_as_of)} title={fmtDate(r.data_as_of)}>{fmtAge(r.data_as_of)}</span> },
  { key: "updated_at", label: "Letzte Änd.", align: "right", sort: "updated_at", defaultOn: false,
    render: (r) => <span className="text-muted">{fmtDate(r.updated_at)}</span> },
];

const COLS_KEY = "screener_columns_v3";
const DENSITY_KEY = "louichamp_density";

function defaultVisible(): Record<string, boolean> {
  const v: Record<string, boolean> = { ticker: true };
  for (const c of COLS) v[c.key] = c.defaultOn;
  return v;
}

export default function ScreenerBoard(
  { rows, exportRows }: { rows: ScreenerRow[]; exportRows?: ScreenerRow[] },
) {
  const router = useRouter();
  const params = useSearchParams();

  const [visible, setVisible] = useState<Record<string, boolean>>(defaultVisible);
  const [dense, setDense] = useState(false);
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    try {
      const c = localStorage.getItem(COLS_KEY);
      if (c) setVisible({ ...defaultVisible(), ...JSON.parse(c) });
      setDense(localStorage.getItem(DENSITY_KEY) === "compact");
      setFavorites(getFavorites());
    } catch { /* localStorage nicht verfügbar */ }
  }, []);

  const toggleCol = (key: string) => setVisible((prev) => {
    const next = { ...prev, [key]: !prev[key] };
    try { localStorage.setItem(COLS_KEY, JSON.stringify(next)); } catch {}
    return next;
  });

  const setDensity = (compact: boolean) => {
    setDense(compact);
    try { localStorage.setItem(DENSITY_KEY, compact ? "compact" : "comfortable"); } catch {}
  };

  const onToggleFav = useCallback((ticker: string) => {
    setFavorites((prev) => toggleFavorite(prev, ticker));
  }, []);

  const favSet = useMemo(() => new Set(favorites), [favorites]);
  const shown = useMemo(() => COLS.filter((c) => visible[c.key]), [visible]);
  const favViewActive = !!params.get("tickers");

  const showFavorites = () => {
    if (favorites.length === 0) return;
    const next = new URLSearchParams(params.toString());
    next.set("tickers", favorites.join(","));
    next.delete("offset");
    router.push(`/?${next.toString()}`);
  };
  const clearFavView = () => {
    const next = new URLSearchParams(params.toString());
    next.delete("tickers"); next.delete("offset");
    router.push(`/?${next.toString()}`);
  };

  const exportCsv = () => {
    const data = exportRows && exportRows.length ? exportRows : rows;
    downloadCsv(`louichamp_screener_${new Date().toISOString().slice(0, 10)}.csv`,
                rowsToCsv(data));
  };

  const btn = "rounded border border-edge bg-panel2 px-3 py-1.5 text-sm text-slate-200 " +
              "transition-colors hover:border-accent disabled:opacity-50";

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {favViewActive ? (
            <button onClick={clearFavView}
                    className="rounded border border-amber-500/50 bg-amber-500/10 px-3 py-1.5 text-sm text-amber-300 transition-colors hover:bg-amber-500/20">
              ★ Favoriten-Ansicht · zurück zu allen
            </button>
          ) : (
            <button onClick={showFavorites} disabled={favorites.length === 0} className={btn}>
              ★ Favoriten <span className="font-mono text-amber-300">{favorites.length}</span>
            </button>
          )}
          <button onClick={exportCsv} disabled={rows.length === 0} className={btn}>
            ⬇ CSV
          </button>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded border border-edge">
            <button onClick={() => setDensity(false)}
                    className={`px-2.5 py-1.5 text-xs transition-colors ${!dense ? "bg-accent/20 text-accent" : "text-muted hover:text-slate-200"}`}>
              Normal
            </button>
            <button onClick={() => setDensity(true)}
                    className={`px-2.5 py-1.5 text-xs transition-colors ${dense ? "bg-accent/20 text-accent" : "text-muted hover:text-slate-200"}`}>
              Kompakt
            </button>
          </div>
          <ColumnMenu visible={visible} toggle={toggleCol} />
        </div>
      </div>

      <div className="max-h-[74vh] animate-fadein overflow-auto rounded-lg border border-edge bg-panel">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-panel2 shadow-[0_1px_0_0_var(--tw-shadow-color)] shadow-edge">
              <th className="w-8 bg-panel2 px-2 py-2" />
              <th className="bg-panel2 px-3 py-2 text-left">
                <SortHeader column="name" label="Unternehmen" />
              </th>
              {shown.map((c) => (
                <th key={c.key} className={`bg-panel2 px-3 py-2 ${alignCls(c.align)}`} title={c.title}>
                  {c.sort
                    ? <SortHeader column={c.sort} label={c.label} align={c.align} numeric={c.align === "right"} />
                    : <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{c.label}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={shown.length + 2} className="px-3 py-10 text-center text-muted">
                Keine Treffer für die aktuelle Auswahl.
              </td></tr>
            )}
            {rows.map((r) => (
              <Row key={r.ticker} row={r} shown={shown} tickerVisible={!!visible.ticker}
                   dense={dense} fav={favSet.has(r.ticker)} onToggleFav={onToggleFav} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function alignCls(a?: string) {
  return a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";
}

const Row = memo(function Row({
  row, shown, tickerVisible, dense, fav, onToggleFav,
}: {
  row: ScreenerRow; shown: Col[]; tickerVisible: boolean; dense: boolean;
  fav: boolean; onToggleFav: (t: string) => void;
}) {
  const pad = dense ? "py-1" : "py-2";
  return (
    <tr className="border-b border-edge/60 transition-colors hover:bg-panel2/50">
      <td className={`px-2 ${pad} text-center`}>
        <button
          onClick={() => onToggleFav(row.ticker)}
          aria-label={fav ? "Aus Favoriten entfernen" : "Zu Favoriten"}
          className={`text-base leading-none transition-transform hover:scale-125 ${
            fav ? "text-amber-400" : "text-edge hover:text-amber-300"}`}
        >
          {fav ? "★" : "☆"}
        </button>
      </td>
      <td className={`px-3 ${pad}`}>
        <Link href={`/asset?t=${encodeURIComponent(row.ticker)}`} className="group block">
          <span className="font-semibold text-slate-100 group-hover:text-accent">
            {row.name ?? row.ticker}
          </span>
          {tickerVisible && (
            <span className="block font-mono text-[11px] text-muted">{row.ticker}</span>
          )}
        </Link>
      </td>
      {shown.map((c) => (
        <td key={c.key} className={`px-3 ${pad} ${alignCls(c.align)}`}>{c.render(row)}</td>
      ))}
    </tr>
  );
});

function ColumnMenu({
  visible, toggle,
}: { visible: Record<string, boolean>; toggle: (k: string) => void }) {
  const items = [{ key: "ticker", label: "Ticker (unter Name)" },
                 ...COLS.map((c) => ({ key: c.key, label: c.title ?? c.label }))];
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded border border-edge bg-panel2 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-accent">
        ⚙ Spalten
      </summary>
      <div className="absolute right-0 z-20 mt-1 max-h-80 w-60 overflow-auto rounded-lg border border-edge bg-panel2 p-2 shadow-xl">
        {items.map((it) => (
          <label key={it.key} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm transition-colors hover:bg-panel">
            <input type="checkbox" checked={!!visible[it.key]} onChange={() => toggle(it.key)}
                   className="accent-accent" />
            <span className="text-slate-200">{it.label}</span>
          </label>
        ))}
      </div>
    </details>
  );
}
