import type { Summary } from "@/lib/types";
import { totalColor } from "@/lib/format";

// Marktbreite der gefilterten Menge: gestapelter Balken nach Rating + Schnitt.
const ORDER: { key: string; label: string; bar: string; text: string }[] = [
  { key: "STARK KAUFEN", label: "Stark Kaufen", bar: "bg-emerald-400", text: "text-emerald-300" },
  { key: "KAUFEN", label: "Kaufen", bar: "bg-bull", text: "text-bull" },
  { key: "HALTEN", label: "Halten", bar: "bg-warn", text: "text-warn" },
  { key: "REDUZIEREN", label: "Reduzieren", bar: "bg-orange-500", text: "text-orange-400" },
  { key: "VERKAUFEN", label: "Verkaufen", bar: "bg-bear", text: "text-bear" },
];

export default function SummaryStrip({ summary }: { summary: Summary }) {
  const total = summary.total || 0;
  if (total === 0) return null;
  const seg = ORDER.map((o) => ({ ...o, n: summary.by_rating[o.key] ?? 0 }))
    .filter((o) => o.n > 0);

  return (
    <div className="rounded-lg border border-edge bg-panel p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-muted">
          Marktbreite · {total.toLocaleString("de-DE")} Treffer
        </span>
        {summary.avg_total_score != null && (
          <span className="font-mono text-xs text-muted">
            ⌀ Gesamtrating{" "}
            <span className={totalColor(Math.round(summary.avg_total_score))}>
              {summary.avg_total_score.toLocaleString("de-DE")}
            </span>
          </span>
        )}
      </div>

      {/* gestapelter Balken */}
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-edge">
        {seg.map((o) => (
          <div key={o.key} className={`${o.bar} transition-all duration-500`}
               style={{ width: `${(o.n / total) * 100}%` }} title={`${o.label}: ${o.n}`} />
        ))}
      </div>

      {/* Legende */}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {ORDER.map((o) => (
          <span key={o.key} className="flex items-center gap-1.5 text-[11px]">
            <span className={`h-2 w-2 rounded-full ${o.bar}`} />
            <span className="text-muted">{o.label}</span>
            <span className={`font-mono font-semibold ${o.text}`}>
              {summary.by_rating[o.key] ?? 0}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
