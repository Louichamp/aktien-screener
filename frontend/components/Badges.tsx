import { ratingColor, ratingStyle, STRATEGY_STYLE, RARITY_DOTS } from "@/lib/format";

export function RatingBadge({ value }: { value: number | null }) {
  return (
    <span
      className={`inline-flex h-7 w-9 items-center justify-center rounded font-mono text-sm font-semibold tabular-nums ${ratingColor(
        value,
      )}`}
    >
      {value ?? "—"}
    </span>
  );
}

// Empfehlungs-Label (KAUFEN/HALTEN/VERKAUFEN …)
export function RecommendationBadge({ rating }: { rating: string | null }) {
  if (!rating) return <span className="text-muted">—</span>;
  return (
    <span className={`whitespace-nowrap rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${ratingStyle(rating)}`}>
      {rating}
    </span>
  );
}

export function StrategyTag({ tag }: { tag: string | null }) {
  if (!tag) return <span className="text-muted">—</span>;
  const style = STRATEGY_STYLE[tag] ?? "bg-edge text-slate-300 ring-edge";
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ${style}`}>
      {tag}
    </span>
  );
}

export function RarityDots({ rarity }: { rarity: string | null }) {
  const filled = rarity ? RARITY_DOTS[rarity] ?? 0 : 0;
  return (
    <span className="inline-flex items-center gap-1" title={rarity ?? "—"}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${i <= filled ? "bg-accent" : "bg-edge"}`}
        />
      ))}
    </span>
  );
}
