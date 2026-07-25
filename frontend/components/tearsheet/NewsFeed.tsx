import type { NewsItem } from "@/lib/types";
import { fmtDate } from "@/lib/format";

// Nachrichten kommen live vom /news-Endpoint (api/routes.py:get_screener_news).
// `note` ist dessen Erklärung, WARUM ggf. keine Nachrichten da sind (kein
// News-Provider konfiguriert, Abruf fehlgeschlagen, oder wirklich keine News) —
// vorher wurde das verworfen und stattdessen immer derselbe veraltete
// Static-Export-Hinweis gezeigt, unabhängig vom tatsächlichen Grund.
export default function NewsFeed({ items, note }: { items?: NewsItem[]; note?: string | null }) {
  const news = items ?? [];
  return (
    <section>
      <h3 className="mb-3 font-serif text-lg font-bold text-slate-100">Nachrichten</h3>
      {news.length === 0 ? (
        <p className="text-sm text-muted">{note || "Keine Nachrichten verfügbar."}</p>
      ) : (
        <ul className="space-y-3">
          {news.map((n, i) => (
            <li key={i} className="border-b border-edge/60 pb-3 last:border-0">
              <a href={n.url ?? "#"} target="_blank" rel="noopener noreferrer"
                 className="font-medium text-slate-100 transition-colors hover:text-accent">
                {n.title}
              </a>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                {n.source && <span>{n.source}</span>}
                {n.published_at && <span>· {fmtDate(n.published_at)}</span>}
              </div>
              {n.snippet && <p className="mt-1 line-clamp-2 text-sm text-slate-400">{n.snippet}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
