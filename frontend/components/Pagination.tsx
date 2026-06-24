"use client";

import { useRouter, useSearchParams } from "next/navigation";

// Seitennummerierung im Screener-Stil: "1–10 von N".
export default function Pagination({
  total,
  limit,
  offset,
}: {
  total: number;
  limit: number;
  offset: number;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  const go = (nextOffset: number) => {
    const next = new URLSearchParams(params.toString());
    next.set("offset", String(Math.max(0, nextOffset)));
    router.push(`/?${next.toString()}`);
  };

  const setLimit = (n: number) => {
    const next = new URLSearchParams(params.toString());
    next.set("limit", String(n));
    next.delete("offset");
    router.push(`/?${next.toString()}`);
  };

  const btn =
    "rounded border border-edge px-2.5 py-1 text-sm text-slate-200 enabled:hover:border-accent disabled:opacity-30";

  return (
    <div className="flex items-center justify-between gap-4 text-sm text-muted">
      <div className="flex items-center gap-2">
        <span>Zeilen:</span>
        {[10, 25, 50, 100].map((n) => (
          <button
            key={n}
            onClick={() => setLimit(n)}
            className={`rounded px-2 py-0.5 ${
              limit === n ? "bg-accent/20 text-accent" : "hover:text-slate-200"
            }`}
          >
            {n}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <span className="tabular-nums">
          <span className="text-slate-200">{from}–{to}</span> von{" "}
          <span className="text-slate-200">{total.toLocaleString("de-DE")}</span>
        </span>
        <div className="flex gap-1">
          <button className={btn} disabled={!canPrev} onClick={() => go(0)}>«</button>
          <button className={btn} disabled={!canPrev} onClick={() => go(offset - limit)}>‹</button>
          <button className={btn} disabled={!canNext} onClick={() => go(offset + limit)}>›</button>
          <button
            className={btn}
            disabled={!canNext}
            onClick={() => go(Math.floor((total - 1) / limit) * limit)}
          >
            »
          </button>
        </div>
      </div>
    </div>
  );
}
