"""Risk: 10 = geringstes Risiko.

Risiko ist mehrdimensional und asymmetrisch. Eine symmetrische ATR/Vola bestraft
Aufwärts- wie Abwärtsbewegung gleich und ignoriert Pfadabhängigkeit. Dieser Score
kombiniert daher vier komplementäre, robuste Risikoquellen:

  • ATR%            — kurzfristige Schwankungsbreite (Stopp-Dimensionierung)
  • Downside-Dev    — annualisierte Verlust-Volatilität (Sortino-Logik)
  • Max-Drawdown    — tatsächlich erlittenes Tail-/Pfad-Risiko
  • Debt/Equity     — bilanzielles/finanzielles Risiko

Downside-Deviation und Max-Drawdown erfassen reales Abwärtsrisiko deutlich besser
als die symmetrische Standardabweichung.
"""
from __future__ import annotations

from ..computor import BaseComputor
from ..context import InstrumentData, ScoringContext
from ..domain import ScoreResult
from ..normalization import band
from ..registry import register_score


@register_score
class RiskComputor(BaseComputor):
    slug = "risk"
    label = "Risk"
    family = "risk"

    def compute(self, data: InstrumentData, ctx: ScoringContext) -> ScoreResult:
        m = data.metric
        close, atr = m("close"), m("atr")
        dd = m("downside_dev")          # annualisiert, Fraktion
        mdd = m("max_drawdown")         # Fraktion 0..1
        de = m("debt_equity")

        num = den = 0.0
        drivers = []

        # ── Kurzfrist-Schwankung (ATR%) ─────────────────────────────────────
        if close and atr:
            atr_pct = atr / close
            rs = band(atr_pct, [(0.01, 10), (0.02, 8), (0.03, 6),
                                 (0.05, 4), (0.08, 2), (0.12, 0)])
            num += 0.25 * rs; den += 0.25
            if atr_pct >= 0.05:
                drivers.append(self.neg("high_vola",
                    f"Hohe Schwankungsbreite (ATR {atr_pct:.1%})",
                    min(atr_pct / 0.1, 1.0), atr_pct=atr_pct))

        # ── Downside-Deviation (Verlust-Volatilität) ────────────────────────
        if dd is not None:
            rs = band(dd, [(0.10, 10), (0.15, 8), (0.22, 6),
                            (0.32, 4), (0.45, 2), (0.65, 0)])
            num += 0.30 * rs; den += 0.30
            if dd >= 0.40:
                drivers.append(self.neg("high_downside",
                    f"Hohe Verlust-Volatilität (Downside-Dev {dd:.0%} p.a.)",
                    min(dd / 0.6, 1.0), downside_dev=dd))
            elif dd <= 0.15:
                drivers.append(self.pos("low_downside",
                    f"Geringe Verlust-Volatilität (Downside-Dev {dd:.0%} p.a.)",
                    1.0 - dd / 0.15, downside_dev=dd))

        # ── Max-Drawdown (Tail-/Pfad-Risiko) ────────────────────────────────
        if mdd is not None:
            rs = band(mdd, [(0.05, 10), (0.10, 9), (0.20, 7),
                             (0.35, 5), (0.50, 3), (0.70, 1)])
            num += 0.25 * rs; den += 0.25
            if mdd >= 0.40:
                drivers.append(self.neg("deep_drawdown",
                    f"Tiefer Drawdown der letzten 6 Monate ({mdd:.0%})",
                    min(mdd / 0.7, 1.0), max_drawdown=mdd))

        # ── Verschuldung (bilanzielles Risiko) ──────────────────────────────
        if de is not None:
            rs = band(de, [(0.0, 10), (1.0, 8), (2.0, 5), (3.0, 2)])
            num += 0.20 * rs; den += 0.20
            if de >= 2.0:
                drivers.append(self.neg("high_debt",
                    f"Hohe Verschuldung (D/E {de:.1f})",
                    min((de - 1.0) / 2.0, 1.0), debt_equity=de))

        if den == 0:
            return self.missing("Keine Risikodaten")

        score = num / den               # 10 = sicher
        state = "defensiv" if score >= 7 else "riskant" if score <= 3 else "mittel"
        return self.result(score, state, drivers,
                           atr=atr, downside_dev=dd, max_drawdown=mdd, debt_equity=de)
