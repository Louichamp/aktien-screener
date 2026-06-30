"""Trend: EMA-Struktur + Kursposition, gewichtet mit Trend-QUALITÄT.

Eine reine EMA-Stapelung sagt nur die Richtung, nicht die Tragfähigkeit eines
Trends. Zwei Titel mit identischer EMA-Ordnung können völlig unterschiedlich sein:
ein sauberer, geradliniger Aufwärtstrend vs. ein verrauschtes Zickzack knapp über
den Linien. Deshalb fließt zusätzlich die Trend-QUALITÄT ein — Kaufman Efficiency
Ratio (Geradlinigkeit der Bewegung) und das Regressions-R² (Persistenz). So werden
hochwertige Trends von fragilen unterschieden.
"""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..registry import register_score


@register_score
class TrendComputor(BaseComputor):
    slug = "trend"
    label = "Trend"
    family = "trend_leadership"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        close, e20, e50 = m("close"), m("ema_20"), m("ema_50")
        e100, e200, slope = m("ema_100"), m("ema_200"), m("ema_200_slope")
        er, r2 = m("efficiency_ratio"), m("trend_r2")
        if None in (close, e50, e200):
            return self.missing("Kurs oder EMA50/EMA200 fehlt")

        drivers = []
        struct = 0.0                       # Struktur-Punkte (max 7)

        # ── EMA-Stapelung: abgestufte Gutschrift über benachbarte Ordnungen ──
        chain = [e for e in (e20, e50, e100, e200) if e is not None]
        if len(chain) >= 2:
            pairs = list(zip(chain, chain[1:]))            # absteigend: schnell→langsam
            bull_pairs = sum(1 for a, b in pairs if a > b)
            bear_pairs = sum(1 for a, b in pairs if a < b)
            frac = bull_pairs / len(pairs)
            struct += 2.8 * frac
            if bull_pairs == len(pairs):
                drivers.append(self.pos("ema_stack_bull",
                    "Bullische EMA-Stapelung (vollständig geordnet)", 0.9))
            elif bear_pairs == len(pairs):
                drivers.append(self.neg("ema_stack_bear",
                    "Bärische EMA-Stapelung (vollständig invertiert)", 0.9))

        # ── Kursposition relativ zu EMA50 / EMA200 ──────────────────────────
        if close > e50:
            struct += 1.4
            drivers.append(self.pos("above_ema50", "Kurs über EMA50", 0.5))
        else:
            drivers.append(self.neg("below_ema50", "Kurs unter EMA50", 0.5))

        primary_up = close > e200
        if primary_up:
            struct += 1.4
            drivers.append(self.pos("above_ema200", "Kurs über EMA200 (Primärtrend)", 0.6))
        else:
            drivers.append(self.neg("below_ema200", "Kurs unter EMA200 (Primärtrend)", 0.6))

        if slope is not None and slope > 0:
            struct += 1.4
            drivers.append(self.pos("ema200_rising", "EMA200 steigt", 0.4))
        elif slope is not None:
            drivers.append(self.neg("ema200_falling", "EMA200 fällt", 0.4))

        # ── Trend-Qualität (max 3 Punkte), nur im Aufwärtskontext gutgeschrieben.
        #    ER und R² sind richtungsneutral; ein sauberer Abwärtstrend soll den
        #    (bullischen) Trend-Score NICHT anheben — dort ist die Struktur schon ~0.
        quality = 0.0
        if er is not None or r2 is not None:
            q = 0.6 * (er if er is not None else 0.0) + 0.4 * (r2 if r2 is not None else 0.0)
            q = max(0.0, min(1.0, q))
            if primary_up and (slope or 0) >= 0:
                quality = 3.0 * q
                if q >= 0.5:
                    drivers.append(self.pos("clean_trend",
                        f"Sauberer, persistenter Aufwärtstrend (ER {er or 0:.2f}, R² {r2 or 0:.2f})",
                        q, efficiency_ratio=er, trend_r2=r2))
            elif not primary_up and q >= 0.5:
                drivers.append(self.neg("clean_downtrend",
                    f"Sauberer Abwärtstrend (ER {er or 0:.2f}, R² {r2 or 0:.2f})",
                    q, efficiency_ratio=er, trend_r2=r2))

        score = struct + quality
        state = "Aufwärts" if score >= 7 else "Abwärts" if score <= 3 else "Neutral"
        return self.result(score, state, drivers,
                           close=close, ema50=e50, ema200=e200, slope200=slope,
                           efficiency_ratio=er, trend_r2=r2)
