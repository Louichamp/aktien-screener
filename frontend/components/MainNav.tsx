"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Reiter zwischen dem Screener (gesamtes Universum) und der Wochen-Watchlist
// (die kuratierte Auswahl daraus). Bewusst nur zwei — mehr Navigation als
// Inhalt wäre hier verlorene Fläche.
const TABS = [
  { href: "/", label: "Screener", hint: "Alle Instrumente durchsuchen" },
  { href: "/watchlist", label: "Woche", hint: "Kandidaten der Woche, nach Priorität" },
];

export default function MainNav() {
  const path = usePathname();
  return (
    <nav className="flex items-center gap-1" aria-label="Hauptbereiche">
      {TABS.map((t) => {
        const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            title={t.hint}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${
              active
                ? "bg-accent/15 text-accent ring-1 ring-inset ring-accent/40"
                : "text-muted hover:bg-panel2 hover:text-slate-200"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
