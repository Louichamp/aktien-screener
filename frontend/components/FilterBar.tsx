"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Facets } from "@/lib/types";
import { RISK_CLASSES, TRENDS } from "@/lib/types";

const RATING_ORDER = ["STARK KAUFEN", "KAUFEN", "HALTEN", "REDUZIEREN", "VERKAUFEN"];

const FILTER_KEYS = [
  "strategy", "risk_class", "sector", "country", "asset_class", "status",
  "rating", "trend_long", "min_total_score", "min_dividend_yield", "search", "rare_only",
  "min_signal",
];

// „Mindestens moderat" ist die praktisch nützliche Abfrage: Sie blendet
// Treffer aus, die nur auf einer einzelnen technischen Bedingung beruhen.
const SIGNAL_OPTIONS = [
  { value: "stark", label: "nur starke" },
  { value: "moderat", label: "mind. moderat" },
  { value: "schwach", label: "mind. schwach" },
];

export default function FilterBar({ facets }: { facets: Facets }) {
  const router = useRouter();
  const params = useSearchParams();

  const update = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      next.delete("offset");
      router.push(`/?${next.toString()}`);
    },
    [params, router],
  );

  const [search, setSearch] = useState(params.get("search") ?? "");
  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get("search") ?? "") !== search) update("search", search);
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "SELECT" && tag !== "TEXTAREA") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const activeCount = FILTER_KEYS.filter((k) => params.get(k)).length;
  const isRareActive = params.get("rare_only") === "1";

  const clearAll = () => {
    setSearch("");
    router.push("/");
  };

  const toggleRarePreset = () => {
    setSearch("");
    if (isRareActive) {
      router.push("/");
    } else {
      router.push("/?rare_only=1");
    }
  };

  const orderRisk = facets.risk_classes.slice().sort(
    (a, b) => RISK_CLASSES.indexOf(a as never) - RISK_CLASSES.indexOf(b as never));
  const orderRating = facets.ratings.slice().sort(
    (a, b) => RATING_ORDER.indexOf(a) - RATING_ORDER.indexOf(b));

  return (
    <div className="space-y-2">
      {/* Preset-Buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={clearAll}
          disabled={activeCount === 0}
          className="rounded border border-edge bg-panel2 px-4 py-2 text-sm font-semibold uppercase tracking-wide text-slate-300 transition-colors hover:border-slate-400 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Alle Filter löschen
        </button>
        <button
          onClick={toggleRarePreset}
          className={`rounded border px-4 py-2 text-sm font-semibold uppercase tracking-wide transition-colors ${
            isRareActive
              ? "border-bear/60 bg-bear/20 text-bear hover:bg-bear/30"
              : "border-bear/40 bg-bear/10 text-bear/80 hover:border-bear/60 hover:bg-bear/20 hover:text-bear"
          }`}
        >
          Limitierte Marktchancen
        </button>
      </div>

      {/* Filter-Grid */}
      <div className="rounded-lg border border-edge bg-panel/60 p-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Suche" full>
            <input
              ref={searchRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Name oder Ticker…  ( / )"
              className="w-full rounded border border-edge bg-panel2 px-2 py-1.5 text-sm text-slate-200 outline-none transition-colors focus:border-accent"
            />
          </Field>

          <Select label="Strategie" k="strategy" params={params} update={update} options={facets.strategies} />
          <Select label="Branche" k="sector" params={params} update={update} options={facets.sectors} />
          <Select label="Land" k="country" params={params} update={update} options={facets.countries} />
          <Select label="Anlageklasse" k="asset_class" params={params} update={update} options={facets.asset_classes} />
          <Select label="Risikoklasse" k="risk_class" params={params} update={update} options={orderRisk} />
          <Select label="Status" k="status" params={params} update={update} options={facets.statuses} />
          <Select label="Rating" k="rating" params={params} update={update} options={orderRating} />
          <Select label="Langfr. Trend" k="trend_long" params={params} update={update} options={[...TRENDS]} />
          <Field label="Signalstärke">
            <select
              value={params.get("min_signal") ?? ""}
              onChange={(e) => update("min_signal", e.target.value)}
              className="rounded border border-edge bg-panel2 px-2 py-1.5 text-sm text-slate-200 focus:border-accent focus:outline-none"
              title="Wie viele unabhängige Faktoren müssen sich bestätigen?"
            >
              <option value="">alle</option>
              {SIGNAL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>

          <Field label="Min. Gesamt">
            <input
              type="number" min={0} max={100}
              defaultValue={params.get("min_total_score") ?? ""}
              onChange={(e) => update("min_total_score", e.target.value)}
              placeholder="0–100"
              className="w-full rounded border border-edge bg-panel2 px-2 py-1.5 text-sm tabular-nums text-slate-200 outline-none focus:border-accent"
            />
          </Field>
          <Field label="Min. Dividende %">
            <input
              type="number" min={0} step={0.5}
              defaultValue={params.get("min_dividend_yield")
                ? String(Number(params.get("min_dividend_yield")) * 100) : ""}
              onChange={(e) => update("min_dividend_yield",
                e.target.value ? String(Number(e.target.value) / 100) : "")}
              placeholder="z.B. 2.5"
              className="w-full rounded border border-edge bg-panel2 px-2 py-1.5 text-sm tabular-nums text-slate-200 outline-none focus:border-accent"
            />
          </Field>
        </div>

        {activeCount > 0 && (
          <p className="mt-2 text-[11px] text-muted">
            {activeCount} Filter aktiv
            {isRareActive && <span className="ml-2 text-bear/80">· Limitierte Marktchancen aktiv</span>}
          </p>
        )}
      </div>
    </div>
  );
}

function Field({ label, children, full }: { label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 ${full ? "col-span-2 sm:col-span-1" : ""}`}>
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      {children}
    </label>
  );
}

function Select({
  label, k, params, update, options,
}: {
  label: string; k: string; params: URLSearchParams;
  update: (k: string, v: string) => void; options: string[];
}) {
  return (
    <Field label={label}>
      <select
        value={params.get(k) ?? ""}
        onChange={(e) => update(k, e.target.value)}
        className="w-full rounded border border-edge bg-panel2 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent"
      >
        <option value="">Alle</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </Field>
  );
}
