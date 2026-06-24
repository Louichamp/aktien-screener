import type { ScreenerRowDetail } from "@/lib/types";
import { fmtPrice } from "@/lib/format";
import { smoothLinePath, smoothAreaPath, type Pt } from "@/lib/smooth";

// Durchgängiger „Kursverlauf → Prognose"-Chart:
//   * echte Schlusskurs-Historie (price_history) als Linie links,
//   * Prognose (forecast_history) als geglätteter Mittelpfad + Konfidenzkanal rechts,
//   * Kanal als Kegel, am letzten Kurs verankert -> visuell stetig.
// Mittelpfad und Bandränder werden kubisch (Catmull-Rom→Bézier) geglättet; die
// Kanalbreite ergibt sich aus den echten Inferenzbändern.
const W = 760;
const H = 280;
const PAD = { l: 56, r: 92, t: 22, b: 26 };

const METHOD_LABEL: Record<string, string> = {
  statistical: "statistische Projektion (GBM, aus echter Vola)",
  kronos: "Kronos-KI-Prognose",
};

export default function KronosForecast({ row }: { row: ScreenerRowDetail }) {
  const hist = row.price_history ?? [];
  const fc = row.forecast_history ?? [];
  const hasHist = hist.length >= 2;
  const hasFc = fc.length >= 2;

  if (!hasHist && !hasFc) {
    return (
      <div>
        <h3 className="mb-3 font-serif text-lg font-bold text-slate-100">Kursverlauf &amp; Prognose</h3>
        <div className="flex h-32 items-center justify-center rounded border border-dashed border-edge text-sm text-muted">
          Keine Verlaufs-/Prognosedaten für {row.ticker}. (Sync mit Forecast-Band ausführen.)
        </div>
      </div>
    );
  }

  const N = hist.length;
  const F = fc.length;
  const price = row.price ?? (hasHist ? hist[N - 1] : fc[0].mean);
  const lastClose = hasHist ? hist[N - 1] : price;

  const refs = [
    { v: row.targets.target_1, label: "KZ1", color: "#22c55e" },
    { v: row.targets.signal_aggr, label: "Signal", color: "#38bdf8" },
    { v: row.targets.stop_loss, label: "Stop", color: "#ef4444" },
  ].filter((r) => r.v != null) as { v: number; label: string; color: string }[];

  const allVals = [
    ...hist,
    ...fc.flatMap((p) => [p.upper, p.lower]),
    price, ...refs.map((r) => r.v),
  ];
  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const range = max - min || 1;

  const lastIdx = (hasHist ? N - 1 : 0) + (hasFc ? F : 0);
  const x = (i: number) => PAD.l + (lastIdx === 0 ? 0 : i / lastIdx) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - min) / range) * (H - PAD.t - PAD.b);

  const histPts: Pt[] = hist.map((c, i) => ({ x: x(i), y: y(c) }));
  const histPath = hasHist ? smoothLinePath(histPts) : "";

  const anchorX = hasHist ? N - 1 : 0;
  const anchor: Pt = { x: x(anchorX), y: y(lastClose) };
  const meanPts: Pt[] = hasFc
    ? [anchor, ...fc.map((p, j) => ({ x: x(anchorX + 1 + j), y: y(p.mean) }))] : [];
  const upperPts: Pt[] = hasFc
    ? [anchor, ...fc.map((p, j) => ({ x: x(anchorX + 1 + j), y: y(p.upper) }))] : [];
  const lowerPts: Pt[] = hasFc
    ? [anchor, ...fc.map((p, j) => ({ x: x(anchorX + 1 + j), y: y(p.lower) }))] : [];
  const meanPath = hasFc ? smoothLinePath(meanPts) : "";
  const bandPath = hasFc ? smoothAreaPath(upperPts, lowerPts) : "";

  const expReturn = row.targets.forecast_return != null
    ? row.targets.forecast_return * 100
    : (hasFc ? (fc[F - 1].mean / price - 1) * 100 : null);
  const channelPct = hasFc
    ? ((fc[F - 1].upper - fc[F - 1].lower) / fc[F - 1].mean) * 100 : null;
  const methodLabel = METHOD_LABEL[row.targets.forecast_method ?? ""] ?? "Prognose";

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-serif text-lg font-bold text-slate-100">Kursverlauf &amp; Prognose</h3>
        <div className="flex gap-4 font-mono text-xs">
          {hasFc && <span className="text-muted">Horizont <span className="text-slate-200">{F} T</span></span>}
          {expReturn != null && (
            <span className="text-muted">Erwartung{" "}
              <span className={expReturn >= 0 ? "text-bull" : "text-bear"}>
                {expReturn >= 0 ? "+" : ""}{expReturn.toFixed(1)}%
              </span>
            </span>
          )}
          {channelPct != null && (
            <span className="text-muted">Kanal <span className="text-accent">±{channelPct.toFixed(1)}%</span></span>
          )}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Kursverlauf und Prognose">
        <defs>
          <linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.24" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {/* Konfidenzkanal + Mittelpfad (Prognose) */}
        {hasFc && <path d={bandPath} fill="url(#band)" stroke="#38bdf8" strokeOpacity="0.30" strokeWidth="1" />}
        {hasFc && <path d={meanPath} fill="none" stroke="#38bdf8" strokeWidth="2" strokeDasharray="5 3" />}

        {/* Historie */}
        {hasHist && <path d={histPath} fill="none" stroke="#e2e8f0" strokeWidth="1.8" />}

        {/* „Heute"-Trennlinie */}
        {hasHist && hasFc && (
          <g>
            <line x1={x(anchorX)} x2={x(anchorX)} y1={PAD.t} y2={H - PAD.b}
                  stroke="#8b97a8" strokeOpacity="0.4" strokeDasharray="3 3" />
            <circle cx={x(anchorX)} cy={y(lastClose)} r="3.5" fill="#e2e8f0" />
            <text x={x(anchorX)} y={PAD.t - 6} textAnchor="middle" fill="#8b97a8" fontSize="9">heute</text>
          </g>
        )}

        {/* Referenz-Level */}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(r.v)} y2={y(r.v)}
                  stroke={r.color} strokeOpacity="0.4" strokeDasharray="4 4" strokeWidth="1" />
            <text x={W - PAD.r + 6} y={y(r.v) + 3} fill={r.color} fontSize="10" className="font-mono">
              {r.label} {r.v.toFixed(2)}
            </text>
          </g>
        ))}
      </svg>

      <p className="mt-1 text-[11px] text-muted">
        Weiße Linie = realer Kursverlauf · schattierter Kegel = {methodLabel}
        {hasHist && <> · aktueller Kurs {fmtPrice(price, row.currency)}</>}.
      </p>
    </div>
  );
}
