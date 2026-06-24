"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Facets } from "@/lib/types";
import { RISK_CLASSES, TRENDS } from "@/lib/types";

const RATING_ORDER = ["STARK KAUFEN", "KAUFEN", "HALTEN", "REDUZIEREN", "VERKAUFEN"];

// Reiche Filterleiste: Suche + Dropdowns (Strategie, Branche, Land, Anlageklasse,
// Risiko, Status, Rating, Trend) + Mindest-Schwellen. Der Zustand liegt komplett
// in der URL — der Server-Component refetcht. Facetten kommen aus der API.
export default function FilterBar({ facets }: { facets: Facets }) {
  const router = useRouter();
  const params = useSearchParams();

  const update = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      next.delete("offset");                       // neuer Filter -> Seite 1
      router.push(`/?${next.toString()}`);
    },
    [params, router],
  );

  // Suche: lokal gepuffert, debounced in die URL geschrieben.
  const [search, setSearch] = useState(params.get("search") ?? "");
  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get("search") ?? "") !== search) update("search", search);
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Tastatur-Shortcut „/" fokussiert die Suche (wie in Profi-Terminals).
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

  const activeCount = [
    "strategy", "risk_class", "sector", "country", "asset_class", "status",
    "rating", "trend_long", "min_total_score", "min_dividend_yield", "search",
  ].filter((k) => params.get(k)).length;

  const orderRisk = facets.risk_classes.slice().sort(
    (a, b) => RISK_CLASSES.indexOf(a as any) - RISK_CLASSES.indexOf(b as any));
  const orderRating = facets.ratings.slice().sort(
    (a, b) => RATING_ORDER.indexOf(a) - RATING_ORDER.indexOf(b));

  return (
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
        <div className="mt-2 flex items-center gap-3">
          <span className="text-xs text-muted">{activeCount} Filter aktiv</span>
          <button
            onClick={() => { setSearch(""); router.push("/"); }}
            className="rounded border border-edge px-2 py-0.5 text-xs text-muted hover:text-slate-200"
          >
            Alle Filter löschen
          </button>
        </div>
      )}
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
