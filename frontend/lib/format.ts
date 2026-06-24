// Darstellungs-Helfer: Farben, Labels, Zahlenformate.

export function fmtPrice(v: number | null, ccy: string | null): string {
  if (v == null) return "—";
  return `${v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${
    ccy ? " " + ccy : ""
  }`;
}

export function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPct(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return `${(v * 100).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;
}

export function fmtDate(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d.getTime()) ? v : d.toLocaleDateString("de-DE", { dateStyle: "medium" });
}

// Daten-Alter (in Tagen) + Anzeige/Farbe für den „Stand" pro Wert.
export function ageDays(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86_400_000);
}
export function fmtAge(iso: string | null | undefined): string {
  const n = ageDays(iso);
  if (n == null) return "—";
  if (n <= 0) return "heute";
  if (n === 1) return "gestern";
  return `${n} T`;
}
export function ageColor(iso: string | null | undefined): string {
  const n = ageDays(iso);
  if (n == null) return "text-muted";
  if (n <= 1) return "text-bull";
  if (n <= 3) return "text-slate-300";
  if (n <= 7) return "text-warn";
  return "text-bear";
}

// Rating-Label -> Stil (KAUFEN grün … VERKAUFEN rot)
export function ratingStyle(rating: string | null): string {
  switch (rating) {
    case "STARK KAUFEN": return "bg-bull/25 text-bull ring-1 ring-bull/50";
    case "KAUFEN": return "bg-bull/15 text-bull ring-1 ring-bull/40";
    case "HALTEN": return "bg-warn/15 text-warn ring-1 ring-warn/40";
    case "REDUZIEREN": return "bg-orange-500/15 text-orange-400 ring-1 ring-orange-500/40";
    case "VERKAUFEN": return "bg-bear/15 text-bear ring-1 ring-bear/40";
    default: return "bg-edge text-muted";
  }
}

export const ASSET_LABEL: Record<string, string> = {
  Aktie: "Aktie", ETF: "ETF", Krypto: "Krypto", Forex: "Forex", stock: "Aktie",
};

export function trendClass(trend: string | null): string {
  if (trend === "AUFWÄRTS") return "text-bull";
  if (trend === "ABWÄRTS") return "text-bear";
  return "text-muted";
}

export function trendArrow(trend: string | null): string {
  if (trend === "AUFWÄRTS") return "▲";
  if (trend === "ABWÄRTS") return "▼";
  return "▬";
}

// Rating 0..10 -> Ampelfarbe
export function ratingColor(v: number | null): string {
  if (v == null) return "bg-edge text-muted";
  if (v >= 8) return "bg-bull/20 text-bull ring-1 ring-bull/40";
  if (v >= 5) return "bg-warn/15 text-warn ring-1 ring-warn/40";
  return "bg-bear/15 text-bear ring-1 ring-bear/40";
}

// Gesamtscore 0..100
export function totalColor(v: number | null): string {
  if (v == null) return "text-muted";
  if (v >= 75) return "text-bull";
  if (v >= 50) return "text-warn";
  return "text-bear";
}

export const RISK_LEVEL: Record<string, number> = {
  "sehr niedrig": 1, niedrig: 2, mittel: 3, hoch: 4, "sehr hoch": 5,
};

export function riskColor(risk: string | null): string {
  const lvl = risk ? RISK_LEVEL[risk] ?? 3 : 3;
  return ["text-muted", "text-bull", "text-emerald-300", "text-warn", "text-orange-400", "text-bear"][lvl];
}

export const STRATEGY_STYLE: Record<string, string> = {
  WACHSTUM: "bg-sky-500/15 text-sky-300 ring-sky-500/40",
  DIVIDENDE: "bg-violet-500/15 text-violet-300 ring-violet-500/40",
  CASHFLOW: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  "HIDDEN CHAMPION": "bg-amber-500/15 text-amber-300 ring-amber-500/40",
};

// "selten" / "sehr selten" -> Anzahl gefüllter Punkte (0..5)
export const RARITY_DOTS: Record<string, number> = {
  alltäglich: 1, häufig: 2, gelegentlich: 3, selten: 4, "sehr selten": 5,
};
