import type { ScreenerRowDetail } from "@/lib/types";
import { StrategyTag } from "../Badges";

// SEC-EDGAR-Fundamentaldaten. Die Lese-API liefert derzeit die abgeleiteten
// Größen (WLAFAR, Strategie-Tags, Rationale); die rohen EDGAR-Kennzahlen
// (Umsatz, Marge, ROIC, D/E …) werden ergänzt, sobald der Ingest sie persistiert.
export default function FundamentalData({ row }: { row: ScreenerRowDetail }) {
  return (
    <section>
      <h3 className="mb-3 font-serif text-lg font-bold text-slate-100">
        Fundamentaldaten <span className="text-xs font-normal text-muted">(SEC EDGAR)</span>
      </h3>

      <div className="flex flex-wrap items-center gap-2">
        {row.strategy_tags.length > 0 ? (
          row.strategy_tags.map((t) => <StrategyTag key={t} tag={t} />)
        ) : (
          <span className="text-sm text-muted">Kein Strategie-Tag qualifiziert.</span>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <div className="flex justify-between border-b border-edge/60 py-1">
          <dt className="text-muted">Fundamental-Rating</dt>
          <dd className="font-mono text-slate-100">{row.wlafar ?? "—"} / 10</dd>
        </div>
        <div className="flex justify-between border-b border-edge/60 py-1">
          <dt className="text-muted">Gesamtrating</dt>
          <dd className="font-mono text-slate-100">{row.total_score ?? "—"} / 100</dd>
        </div>
        <div className="flex justify-between border-b border-edge/60 py-1">
          <dt className="text-muted">Status</dt>
          <dd className="text-slate-100">{row.status ?? "—"}</dd>
        </div>
        <div className="flex justify-between border-b border-edge/60 py-1">
          <dt className="text-muted">Risikoklasse</dt>
          <dd className="text-slate-100">{row.risikoklasse ?? "—"}</dd>
        </div>
      </dl>

      {row.drivers.rationale.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm text-slate-300">
          {row.drivers.rationale.map((r, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-muted">›</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
