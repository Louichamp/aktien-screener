import type { ScoreBreakdown as Breakdown, ScoreComponent } from "@/lib/types";
import { SignalBadge } from "@/components/Badges";

// Beantwortet „warum 87?" aus den tatsächlich gespeicherten Sub-Scores
// (screener/explain.py). Vorher stand dort nur die verdichtete Zahl — die
// Einzelwerte wurden nach jedem Lauf verworfen und waren nicht rekonstruierbar.
//
// Die Balkenlänge ist der WERT des Faktors, die Zahl rechts sein BEITRAG zum
// Gesamtscore. Beides zu zeigen ist der Punkt: Ein Faktor kann stark sein und
// trotzdem kaum durchschlagen, weil sein Gewicht klein ist.

function barColor(v: number): string {
  return v >= 75 ? "bg-bull" : v >= 50 ? "bg-warn" : "bg-bear";
}

function Row({ c }: { c: ScoreComponent }) {
  if (!c.available) {
    return (
      <li className="flex items-center gap-3 py-1 opacity-50">
        <span className="w-36 shrink-0 truncate text-xs text-muted" title={c.label}>{c.label}</span>
        <span className="h-1.5 flex-1 rounded-full bg-edge/40" />
        <span className="w-24 shrink-0 text-right font-mono text-[11px] text-muted">
          keine Daten
        </span>
      </li>
    );
  }
  return (
    <li className="flex items-center gap-3 py-1">
      <span className="w-36 shrink-0 truncate text-xs text-slate-300" title={c.state ?? c.label}>
        {c.label}
      </span>
      <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-edge/50">
        <span className={`absolute inset-y-0 left-0 rounded-full ${barColor(c.score)}`}
              style={{ width: `${Math.max(1, Math.min(100, c.score))}%` }} />
      </span>
      <span className="w-24 shrink-0 text-right font-mono text-[11px] tabular-nums">
        <span className="font-semibold text-slate-200">{c.score.toFixed(0)}</span>
        <span className="text-muted"> · {(c.weight * 100).toFixed(0)}%</span>
      </span>
    </li>
  );
}

function Block({ title, items, sum }: { title: string; items: ScoreComponent[]; sum: number | null }) {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</h4>
        {sum != null && (
          <span className="font-mono text-xs font-bold tabular-nums text-slate-200">
            {sum.toFixed(0)}/100
          </span>
        )}
      </div>
      <ul>{items.map((c) => <Row key={c.slug} c={c} />)}</ul>
    </div>
  );
}

export default function ScoreBreakdownPanel(
  { breakdown, total }: { breakdown?: Breakdown | null; total: number | null },
) {
  const b = breakdown;
  const hasData = b && (b.technical?.length || b.fundamental?.length);
  if (!hasData) {
    return (
      <section>
        <h3 className="mb-2 font-serif text-lg font-bold text-slate-100">Warum dieser Score?</h3>
        <p className="text-sm text-muted">
          Für diesen Wert liegt noch keine Aufschlüsselung vor — sie entsteht beim
          nächsten Durchlauf.
        </p>
      </section>
    );
  }

  const weighted = (items: ScoreComponent[]) => {
    const live = items.filter((c) => c.available);
    const w = live.reduce((a, c) => a + c.weight, 0);
    return w > 0 ? live.reduce((a, c) => a + c.contribution, 0) / w : null;
  };

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-serif text-lg font-bold text-slate-100">Warum dieser Score?</h3>
        <div className="flex items-center gap-3">
          <SignalBadge strength={b.signal_strength} confirming={b.confirming} />
          {total != null && (
            <span className="font-mono text-sm font-bold text-slate-200">{total}/100</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <Block title="Technisch" items={b.technical ?? []} sum={weighted(b.technical ?? [])} />
        <Block title="Fundamental" items={b.fundamental ?? []} sum={weighted(b.fundamental ?? [])} />
      </div>

      {(b.confirming?.length > 0 || b.contradicting?.length > 0) && (
        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs">
          {b.confirming?.length > 0 && (
            <p className="text-bull">
              <span className="font-semibold">Bestätigt:</span> {b.confirming.join(", ")}
            </p>
          )}
          {b.contradicting?.length > 0 && (
            <p className="text-bear">
              <span className="font-semibold">Dagegen:</span> {b.contradicting.join(", ")}
            </p>
          )}
        </div>
      )}

      {b.note && (
        <p className="mt-3 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {b.note}
        </p>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-muted">
        Balken = Wert des Faktors (0–100), Zahl rechts = Wert · Gewicht am Rating.
        Faktoren ohne Daten fließen nicht ein und werden nicht geschätzt.
      </p>
    </section>
  );
}
