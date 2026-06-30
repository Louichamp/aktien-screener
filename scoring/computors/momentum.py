"""Momentum: risiko-adjustierte Intermediate-Term-Rendite + RSI-Sweetspot.

Akademisch robustes Momentum ist NICHT die rohe Rendite, sondern die
volatilitäts-normierte Rendite über einen mittelfristigen Horizont (3–6 Monate).
Eine reine ROC-Bewertung belohnt hochvolatile Titel systematisch über; durch die
Division durch die realisierte Volatilität (Sharpe-artig) werden Bewegungen
vergleichbar und nachhaltige Trends von zufälligen Ausschlägen getrennt.
"""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class MomentumComputor(BaseComputor):
    slug = "momentum"
    label = "Momentum"
    family = "momentum_flow"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        # ret_* liegen in PROZENT vor (z. B. 30.0 = +30 %).
        ret_6m = m("ret_6m")
        ret_3m = m("ret_3m")
        rsi = m("rsi")
        rvol = m("realized_vol")          # annualisiert, Fraktion (z. B. 0.30)

        if ret_6m is None and ret_3m is None and rsi is None:
            return self.missing("Keine Momentum-Daten")

        num = den = 0.0
        drivers = []

        # 1) Risiko-adjustiertes 6-Monats-Momentum (Sharpe-artig). ───────────
        #    ratio = 6M-Rendite / 6M-Volatilität  →  z-artiges Bewegungsmaß.
        primary_ret = ret_6m if ret_6m is not None else ret_3m
        horizon_frac = 0.5 if ret_6m is not None else 0.25   # 6M bzw. 3M Anteil v. Jahr
        if primary_ret is not None:
            if rvol is not None and rvol > 1e-6:
                vol_h_pct = rvol * (horizon_frac ** 0.5) * 100.0   # Vola über Horizont, %
                ratio = primary_ret / vol_h_pct
                rs = band(ratio, [(-1.5, 0), (-0.5, 3), (0.0, 5),
                                   (0.5, 7), (1.0, 8.5), (2.0, 10)])
                if ratio >= 1.0:
                    drivers.append(self.pos("radj_mom_strong",
                        f"Starkes risiko-adjustiertes Momentum (Rendite/Vola {ratio:.2f})",
                        min(ratio / 2.0, 1.0), ratio=ratio, ret=primary_ret, vol=rvol))
                elif ratio <= -0.5:
                    drivers.append(self.neg("radj_mom_weak",
                        f"Negatives risiko-adjustiertes Momentum (Rendite/Vola {ratio:.2f})",
                        min(-ratio / 1.5, 1.0), ratio=ratio, ret=primary_ret, vol=rvol))
            else:
                # Fallback ohne Vola: rohe Rendite in Prozent banden.
                rs = band(primary_ret, [(-30, 1), (-10, 3), (0, 4),
                                         (10, 6), (30, 9), (60, 10)])
            num += 0.55 * rs; den += 0.55

        # 2) Kurzfristige Bestätigung (3M-Rendite, Prozent). ─────────────────
        if ret_3m is not None and ret_6m is not None:
            rs3 = band(ret_3m, [(-25, 1), (-8, 3), (0, 4), (8, 6), (20, 9), (40, 10)])
            num += 0.25 * rs3; den += 0.25

        # 3) RSI-Sweetspot: Momentum ohne Überhitzung. ──────────────────────
        if rsi is not None:
            rss = band(rsi, [(30, 4), (50, 7), (60, 9), (70, 8), (80, 5), (90, 2)])
            num += 0.20 * rss; den += 0.20

        if den == 0:
            return self.missing("Momentum unbestimmbar")

        score = num / den
        state = "stark" if score >= 7 else "schwach" if score <= 3 else "neutral"
        return self.result(score, state, drivers,
                           ret_6m=ret_6m, ret_3m=ret_3m, rsi=rsi, realized_vol=rvol)
