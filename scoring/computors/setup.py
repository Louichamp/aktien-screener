"""Setup-Qualität: RSI-Position, BB-%B, MACD-Histogram, Stochastic, Volumen-Kontraktion, Chartstruktur."""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class SetupComputor(BaseComputor):
    """Kombinierter Einstiegs-Score: niedrige Bewertung, positives Momentum, Volumen-Coiling,
    bullische Chartstruktur. Wird auch in _compute_chance() als 'setup'-Ergebnis genutzt."""
    slug = "setup"
    label = "Setup Quality"
    family = "trend_leadership"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        rsi_v = m("rsi")           # 40–60 optimal: Momentum ohne Overbought
        bb_pct = m("bb_pct")       # 0..1: niedriger = bessere Einstiegsposition
        macd_h = m("macd_hist_pct")  # % vom Preis: positiv = wachsendes Momentum
        stoch_k = m("stoch_k")    # Stochastic %K
        stoch_d = m("stoch_d")    # Stochastic %D (Signal)
        vr = m("volume_ratio")    # < 0.8 = Kontraktion (Coiling)
        hh = m("hh_count")        # bullische Chartstruktur (HH)
        hl = m("hl_count")        # bullische Chartstruktur (HL)
        lh = m("lh_count")        # bärische Chartstruktur (LH)
        ll = m("ll_count")        # bärische Chartstruktur (LL)

        num = den = 0.0
        drivers = []

        # RSI-Position (22 %): 40–60 ideal — Momentum vorhanden, nicht überhitzt
        if rsi_v is not None:
            rs = band(rsi_v, [(10, 3), (30, 5), (40, 9), (50, 10), (60, 9),
                               (70, 6), (80, 3), (90, 1)])
            num += 0.22 * rs; den += 0.22
            if rsi_v > 75:
                drivers.append(self.neg("rsi_overbought",
                    f"RSI überhitzt ({rsi_v:.0f}) — Einstieg suboptimal",
                    min((rsi_v - 70) / 20, 1.0), rsi=rsi_v))
            elif rsi_v < 30:
                drivers.append(self.neg("rsi_oversold",
                    f"RSI überverkauft ({rsi_v:.0f}) — erhöhtes Risiko bei Einstieg",
                    min((30 - rsi_v) / 30, 1.0), rsi=rsi_v))

        # Bollinger %B (18 %): Je tiefer im Band, desto besser der Einstieg
        if bb_pct is not None:
            rs = band(bb_pct, [(-0.10, 8), (0.0, 10), (0.20, 9), (0.40, 7),
                                (0.60, 5), (0.80, 3), (1.0, 2), (1.20, 1)])
            num += 0.18 * rs; den += 0.18
            if bb_pct <= 0.20:
                drivers.append(self.pos("bb_low_entry",
                    f"Preis im unteren Bollinger-Bereich (BB %B {bb_pct:.0%}) — günstiger Einstieg",
                    0.80 - bb_pct if bb_pct < 0.80 else 0.0, bb_pct=bb_pct))
            elif bb_pct >= 0.85:
                drivers.append(self.neg("bb_high_entry",
                    f"Preis im oberen Bollinger-Bereich (BB %B {bb_pct:.0%}) — schlechtes Einstiegsrisiko",
                    bb_pct - 0.85, bb_pct=bb_pct))

        # MACD-Histogramm % vom Preis (20 %): positiv = Momentum wächst
        if macd_h is not None:
            rs = band(macd_h, [(-2.0, 0), (-0.5, 2), (-0.1, 4), (0.0, 5),
                                (0.1, 7), (0.3, 9), (0.8, 10), (1.5, 8)])
            num += 0.20 * rs; den += 0.20
            if macd_h > 0.1:
                drivers.append(self.pos("macd_bull",
                    f"MACD-Histogramm positiv ({macd_h:+.2f} %) — Momentum steigt",
                    min(macd_h / 1.0, 1.0), macd_hist_pct=macd_h))
            elif macd_h < -0.1:
                drivers.append(self.neg("macd_bear",
                    f"MACD-Histogramm negativ ({macd_h:+.2f} %) — Momentum fällt",
                    min(-macd_h / 1.0, 1.0), macd_hist_pct=macd_h))

        # Stochastic (18 %): Überverkauft + K>D = bullischer Cross
        if stoch_k is not None and stoch_d is not None:
            rs = band(stoch_k, [(0, 7), (20, 9), (40, 8), (50, 7), (60, 6),
                                  (75, 4), (85, 2), (100, 1)])
            num += 0.18 * rs; den += 0.18
            if stoch_k > stoch_d and stoch_k < 50:
                drivers.append(self.pos("stoch_bull_cross",
                    f"Stochastic K ({stoch_k:.0f}) kreuzt D ({stoch_d:.0f}) von unten — Trendwende",
                    min((stoch_d - stoch_k + 20) / 40, 1.0),
                    stoch_k=stoch_k, stoch_d=stoch_d))
            elif stoch_k < stoch_d and stoch_k > 50:
                drivers.append(self.neg("stoch_bear_cross",
                    f"Stochastic K ({stoch_k:.0f}) unter D ({stoch_d:.0f}) — bärisches Signal",
                    min((stoch_k - stoch_d + 20) / 40, 1.0),
                    stoch_k=stoch_k, stoch_d=stoch_d))

        # Volumen-Kontraktion (12 %): Niedrigvolumen = Coiling-Phase vor Ausbruch
        if vr is not None:
            rs = band(vr, [(0.1, 9), (0.5, 10), (0.7, 9), (1.0, 7),
                            (1.5, 5), (2.5, 3), (4.0, 1)])
            num += 0.12 * rs; den += 0.12

        # Chartstruktur HH/HL vs. LH/LL (10 %)
        if hh is not None and hl is not None and lh is not None and ll is not None:
            bull = (hh or 0) + (hl or 0)
            bear = (lh or 0) + (ll or 0)
            total = bull + bear
            if total > 0:
                ratio = bull / total
                rs = band(ratio, [(0.0, 0), (0.25, 2), (0.40, 4), (0.50, 5),
                                   (0.65, 8), (0.80, 10), (1.0, 10)])
                num += 0.10 * rs; den += 0.10
                if ratio >= 0.65:
                    drivers.append(self.pos("bull_structure",
                        f"Bullische Chartstruktur: {bull} HH/HL vs {bear} LH/LL",
                        ratio - 0.5, hh=hh, hl=hl, lh=lh, ll=ll))
                elif ratio <= 0.35:
                    drivers.append(self.neg("bear_structure",
                        f"Bärische Chartstruktur: {bear} LH/LL vs {bull} HH/HL",
                        0.5 - ratio, hh=hh, hl=hl, lh=lh, ll=ll))

        if den == 0:
            return self.missing("Keine Setup-Indikatoren verfügbar")

        score = num / den
        state = "Top-Setup" if score >= 7.5 else "kein Setup" if score <= 3 else "neutral"
        return self.result(score, state, drivers,
                           rsi=rsi_v, bb_pct=bb_pct, macd_hist_pct=macd_h,
                           stoch_k=stoch_k, stoch_d=stoch_d, volume_ratio=vr)
