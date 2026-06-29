import { ratingColor, ratingStyle, RISK_LEVEL, STRATEGY_STYLE, RARITY_DOTS } from "@/lib/format";

// ── Einfaches Zahl-Badge (Fallback) ─────────────────────────────────────────
export function RatingBadge({ value }: { value: number | null }) {
  return (
    <span className={`inline-flex h-7 w-9 items-center justify-center rounded font-mono text-sm font-semibold tabular-nums ${ratingColor(value)}`}>
      {value ?? "—"}
    </span>
  );
}

// ── Batterie-Visualisierung für 0–10-Scores (WLATAR / WLAFAR) ───────────────
function BatterySvg({ value }: { value: number }) {
  const fillW = Math.round((value / 10) * 14);
  return (
    <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true" className="shrink-0">
      <rect x="0.5" y="0.5" width="17" height="11" rx="2" stroke="currentColor" strokeOpacity="0.5" fill="none" />
      <rect x="19" y="3.5" width="2.5" height="5" rx="1" fill="currentColor" fillOpacity="0.45" />
      {fillW > 0 && <rect x="1.5" y="1.5" width={fillW} height="9" rx="1.5" fill="currentColor" />}
    </svg>
  );
}

export function BatteryBadge({ value }: { value: number | null }) {
  if (value == null) return <span className="font-mono text-sm text-muted">—</span>;
  const color = value >= 8 ? "text-bull" : value >= 5 ? "text-warn" : "text-bear";
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-xs font-semibold tabular-nums ${color}`}>
      <BatterySvg value={value} />
      {value}/10
    </span>
  );
}

// ── Trend-Pill (AUFWÄRTS / NEUTRAL / ABWÄRTS) ───────────────────────────────
export function TrendBadge({ trend }: { trend: string | null }) {
  if (!trend) return <span className="text-xs text-muted">—</span>;
  if (trend === "AUFWÄRTS")
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-bold bg-bull/15 text-bull ring-1 ring-inset ring-bull/30">
        ↗ AUFWÄRTS
      </span>
    );
  if (trend === "ABWÄRTS")
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-bold bg-bear/15 text-bear ring-1 ring-inset ring-bear/30">
        ↘ ABWÄRTS
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-bold bg-edge text-muted ring-1 ring-inset ring-edge">
      → NEUTRAL
    </span>
  );
}

// ── Risiko-Dots: 5 Punkte, Grün→Rot je Level ────────────────────────────────
const RISK_DOT_COLORS = ["bg-bull", "bg-emerald-400", "bg-warn", "bg-orange-400", "bg-bear"];

export function RiskDots({ risk }: { risk: string | null }) {
  const level = risk ? RISK_LEVEL[risk] ?? 0 : 0;
  return (
    <span className="inline-flex items-center gap-1" title={risk ?? "—"}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i}
          className={`h-2 w-2 rounded-full transition-colors ${i < level ? RISK_DOT_COLORS[i] : "bg-edge"}`}
        />
      ))}
    </span>
  );
}

// ── Chance-Dots: 5 grüne Punkte ─────────────────────────────────────────────
export function RarityDots({ rarity }: { rarity: string | null }) {
  const filled = rarity ? RARITY_DOTS[rarity] ?? 0 : 0;
  return (
    <span className="inline-flex items-center gap-1" title={rarity ?? "—"}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={`h-2 w-2 rounded-full ${i <= filled ? "bg-accent" : "bg-edge"}`} />
      ))}
    </span>
  );
}

// ── Empfehlungs-Label (KAUFEN / HALTEN / VERKAUFEN …) ───────────────────────
export function RecommendationBadge({ rating }: { rating: string | null }) {
  if (!rating) return <span className="text-muted">—</span>;
  return (
    <span className={`whitespace-nowrap rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${ratingStyle(rating)}`}>
      {rating}
    </span>
  );
}

// ── Strategie-Tag ────────────────────────────────────────────────────────────
export function StrategyTag({ tag }: { tag: string | null }) {
  if (!tag) return <span className="text-muted">—</span>;
  const style = STRATEGY_STYLE[tag] ?? "bg-edge text-slate-300 ring-edge";
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ${style}`}>
      {tag}
    </span>
  );
}
