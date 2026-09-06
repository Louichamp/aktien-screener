import type { Metadata } from "next";
import Link from "next/link";
import MainNav from "@/components/MainNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Louichamp Screener",
  description: "Louichamp Screener — Aktien-Research: Technik, Fundament & Kronos-Prognose",
};

// Optionale, datenschutzfreundliche Besucher-Statistik (GoatCounter, gratis).
// Aktiv, sobald NEXT_PUBLIC_GOATCOUNTER gesetzt ist (zur Build-Zeit eingebettet).
const GOATCOUNTER = process.env.NEXT_PUBLIC_GOATCOUNTER;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body>
        {GOATCOUNTER && (
          <script
            data-goatcounter={GOATCOUNTER}
            async
            src="//gc.zgo.at/count.js"
          />
        )}
        <header className="sticky top-0 z-30 border-b border-edge bg-ink/80 backdrop-blur">
          <div className="mx-auto flex max-w-[1500px] items-center justify-between px-6 py-3">
            <Link href="/" className="group flex items-baseline gap-2">
              <span className="bg-gradient-to-r from-amber-300 via-amber-400 to-yellow-500 bg-clip-text text-lg font-black tracking-tight text-transparent">
                LOUICHAMP
              </span>
              <span className="text-xs font-semibold uppercase tracking-[0.3em] text-muted transition-colors group-hover:text-accent">
                Screener
              </span>
            </Link>
            <div className="flex items-center gap-4">
              <MainNav />
              <span className="hidden font-mono text-xs text-muted lg:block">
                Technik · Fundament · Kronos
              </span>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
