import type { ScreenerRowDetail } from "@/lib/types";
import { fmtNum, fmtPrice, trendArrow, trendClass, riskColor } from "@/lib/format";
import { RatingBadge } from "../Badges";

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className="font-mono text-sm text-slate-100">{children}</span>
    </div>
  );
}

// Technisches Dashboard: Ratings, Trends, handelbare Level + Konfluenzzonen.
export default function TechnicalDashboard({ row }: { row: ScreenerRowDetail }) {
  const t = row.targets;
  return (
    <section>
      <h3 className="mb-3 font-serif text-lg font-bold text-slate-100">Technisches Dashboard</h3>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="flex items-center gap-2">
          <RatingBadge value={row.wlatar} />
          <span className="text-[10px] uppercase tracking-wide text-muted">WLATAR<br />Technik</span>
        </div>
        <div className="flex items-center gap-2">
          <RatingBadge value={row.wlafar} />
          <span className="text-[10px] uppercase tracking-wide text-muted">WLAFAR<br />Fundament</span>
        </div>
        <Stat label="Trend lang">
          <span className={trendClass(row.trend_long)}>{trendArrow(row.trend_long)} {row.trend_long ?? "—"}</span>
        </Stat>
        <Stat label="Trend mittel">
          <span className={trendClass(row.trend_medium)}>{trendArrow(row.trend_medium)} {row.trend_medium ?? "—"}</span>
        </Stat>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-4 rounded border border-edge bg-panel2/50 p-3 sm:grid-cols-6">
        <Stat label="Signal aggr.">{fmtNum(t.signal_aggr)}</Stat>
        <Stat label="Signal kons.">{fmtNum(t.signal_kons)}</Stat>
        <Stat label="Stop-Loss"><span className="text-bear">{fmtNum(t.stop_loss)}</span></Stat>
        <Stat label="Kursziel 1"><span className="text-bull">{fmtNum(t.target_1)}</span></Stat>
        <Stat label="Kursziel 2"><span className="text-bull">{fmtNum(t.target_2)}</span></Stat>
        <Stat label="CRV"><span className="text-accent">{fmtNum(t.crv)}</span></Stat>
      </div>

      {row.drivers.zones.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 text-[11px] uppercase tracking-wide text-muted">
            Konfluenzzonen (Stärke 0–10)
          </h4>
          <div className="space-y-1.5">
            {row.drivers.zones.slice(0, 5).map((z, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span
                  className={`w-16 font-mono ${
                    z.kind === "support" ? "text-bull" : z.kind === "resistance" ? "text-bear" : "text-muted"
                  }`}
                >
                  {fmtNum(z.center)}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-edge">
                  <div
                    className={`h-full ${z.is_entry ? "bg-accent" : "bg-slate-500"}`}
                    style={{ width: `${Math.min(z.strength * 10, 100)}%` }}
                  />
                </div>
                <span className="w-10 text-right font-mono text-slate-300">{fmtNum(z.strength, 1)}</span>
                <span className="hidden flex-1 truncate text-muted sm:block" title={z.explain ?? ""}>
                  {z.categories.join(" · ")}
                  {z.is_entry && <span className="ml-1 text-accent">◂ Einstieg</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
