// Gemessene Basisraten des Zonen-Handelsplans.
//
// Das CRV (Chance-Risiko-Verhältnis) ist ein reines Verhältnis aus Kursziel,
// Einstieg und Stopp. Es sagt NICHTS darüber, wie wahrscheinlich das Ziel
// überhaupt erreicht wird — und genau so wurde es bisher gelesen.
//
// Grundlage der Zahlen unten: `scripts/backtest_zones.py`, 400 Titel über
// 12 Jahre, 8.925 simulierte Trades. Simuliert wurde, wie der Plan real
// genutzt würde: Limit-Einstieg an der Support-Konfluenz (gültig 20 Bars),
// danach entscheidet, was ZUERST berührt wird — Stopp oder Ziel.
// Vollständige Methodik und Grenzen: docs/AUDIT_2026-09.md.
//
// Wichtig: Das sind universumsweite Basisraten, KEINE Wahrscheinlichkeiten für
// einen einzelnen Titel. Eine titelbezogene Wahrscheinlichkeit wird bewusst
// nicht ausgewiesen — dafür gibt es kein belastbares Modell.

export const CRV_BASE_RATES = {
  /** Anzahl der simulierten Trades, auf denen die Basisraten beruhen. */
  sample: 8925,
  /** Anteil der Fälle, in denen das Kursziel zuerst erreicht wurde. */
  pTarget: 0.388,
  /** Anteil der Fälle, in denen der Stopp zuerst erreicht wurde. */
  pStop: 0.612,
  /** Median des ausgewiesenen CRV in derselben Stichprobe. */
  medianCrv: 1.99,
  /** Realisierter Erwartungswert je Trade in Risiko-Einheiten (R). */
  evPerTrade: -0.038,
  /** Unterstellte Handelskosten je Seite, in Basispunkten. */
  costBps: 15,
  /** Derselbe Erwartungswert ohne Handelskosten. */
  evPerTradeNoCost: 0.11,
  measuredOn: "2026-09-13",
} as const;

/** Kurzform für Spaltenüberschriften und `title`-Attribute. */
export const CRV_TOOLTIP =
  `Chance-Risiko-Verhältnis: (Kursziel − Einstieg) ÷ (Einstieg − Stopp). ` +
  `Ein Verhältnis, keine Wahrscheinlichkeit. In ${CRV_BASE_RATES.sample.toLocaleString("de-DE")} ` +
  `historisch simulierten Plänen wurde das Ziel in ` +
  `${(CRV_BASE_RATES.pTarget * 100).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} % ` +
  `der Fälle zuerst erreicht, der Stopp in ` +
  `${(CRV_BASE_RATES.pStop * 100).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %. ` +
  `Der realisierte Erwartungswert lag nach Handelskosten bei ` +
  `${CRV_BASE_RATES.evPerTrade.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} R je Trade.`;
