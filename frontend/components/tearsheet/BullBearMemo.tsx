import type { Driver } from "@/lib/types";

function Memo({
  title,
  drivers,
  tone,
}: {
  title: string;
  drivers: Driver[];
  tone: "bull" | "bear";
}) {
  const color = tone === "bull" ? "text-bull" : "text-bear";
  const bar = tone === "bull" ? "bg-bull" : "bg-bear";
  return (
    <div className="flex-1">
      <h4 className={`mb-2 font-serif text-base font-bold ${color}`}>
        {title}
      </h4>
      {drivers.length === 0 ? (
        <p className="text-sm text-muted">Keine markanten Treiber.</p>
      ) : (
        <ul className="space-y-2">
          {drivers.map((d, i) => (
            <li key={i} className="text-sm leading-snug text-slate-300">
              <div className="flex items-center gap-2">
                {/* Wirkungsstärke als kleiner Balken (magnitude 0..1) */}
                <span className="h-1 w-10 overflow-hidden rounded bg-edge">
                  <span
                    className={`block h-full ${bar}`}
                    style={{ width: `${Math.round(d.magnitude * 100)}%` }}
                  />
                </span>
                <span className="font-mono text-[10px] text-muted">{d.code}</span>
              </div>
              <p className="mt-0.5">{d.statement}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Ausformulierte Bull-/Bear-Memos (von der Score-Engine generierte Treiber).
export default function BullBearMemo({ bull, bear }: { bull: Driver[]; bear: Driver[] }) {
  return (
    <section>
      <h3 className="mb-3 font-serif text-lg font-bold text-slate-100">Bull- &amp; Bear-Memo</h3>
      <div className="flex flex-col gap-8 sm:flex-row sm:gap-12">
        <Memo title="Bull-Case" drivers={bull} tone="bull" />
        <div className="hidden w-px bg-edge sm:block" />
        <Memo title="Bear-Case" drivers={bear} tone="bear" />
      </div>
    </section>
  );
}
