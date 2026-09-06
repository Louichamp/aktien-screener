"""Datenqualität je Instrument — wie belastbar ist die Grundlage des Scores?

Ein Score von 87/100 sieht identisch aus, ob er auf zwölf Jahren lückenloser
Historie mit vollständigen Fundamentaldaten beruht oder auf acht Wochen Kursen
ohne jede Kennzahl. Genau diese Verwechslung soll dieses Modul unmöglich machen:
Die Zahl bleibt, aber daneben steht, worauf sie sich stützt.

Bewertet werden ausschließlich Dinge, die aus den vorhandenen Rohdaten
NACHPRÜFBAR sind — keine Schätzungen, keine Annahmen über die Datenquelle:

  Historientiefe   Indikatoren brauchen Vorlauf. Ein RSI aus 20 Bars ist
                   rechnerisch gültig und trotzdem wenig wert; EMA200 und
                   Jahresrenditen fehlen ganz.
  Aktualität       Ein Kurs von vor sechs Wochen beschreibt nicht den Markt
                   von heute.
  Indikatoren      Wie viele der erwarteten Kennzahlen tatsächlich berechnet
                   werden konnten.
  Fundamentaldaten Vorhanden oder nicht — ohne sie ist das Fundamental-Rating
                   Raten.
  Reihenqualität   Handelslücken, Nulltage und verdächtige Sprünge, die auf
                   eine fehlerhafte Split-/Dividendenbereinigung hindeuten.

Die Faktor-Abdeckung des Scores selbst steckt bewusst NICHT hier, sondern in
`explain.py` — sie ist eine Eigenschaft der Bewertung, nicht der Daten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .zones import Candle

# Vorlauf, ab dem alle Indikatoren (inkl. EMA200 und 1-Jahres-Rendite) tragen.
FULL_HISTORY_BARS = 260
# Kennzahlen, die `technicals_from_candles` bei ausreichender Historie liefert.
EXPECTED_INDICATORS = (
    "atr", "ema_20", "ema_50", "ema_200", "ema_200_slope", "sma_200", "rsi",
    "macd_hist", "bb_width", "bb_pct", "stoch_k", "adx", "chop", "volume_ratio",
    "obv_slope", "up_vol_ratio", "ret_1m", "ret_3m", "ret_6m", "ret_1y",
    "efficiency_ratio", "trend_r2", "realized_vol", "max_drawdown",
)
EXPECTED_FUNDAMENTALS = (
    "net_margin", "roic", "revenue_growth", "pe", "ev_ebitda", "p_b",
    "debt_to_equity", "fcf_margin",
)

# Ab dieser Tagesbewegung wird genauer hingesehen — NICHT bestraft. Die
# Klassifikation in `_classify_move` entscheidet, ob es ein Datenproblem ist.
LARGE_MOVE = 0.35

# Glatte Split-Verhältnisse. Ein echter Split wäre von der Datenquelle
# bereinigt worden; bleibt das Verhältnis stehen, ist die Bereinigung
# fehlgeschlagen — das IST ein Datenproblem.
SPLIT_RATIOS = (2, 3, 4, 5, 6, 8, 10, 20)
SPLIT_TOLERANCE = 0.06

# Ein großer Move gilt als marktbestätigt, wenn der Umsatz deutlich über dem
# lokalen Normalmaß liegt — dann hat tatsächlich jemand gehandelt.
CONFIRM_VOLUME = 1.5


class QualityLabel:
    FULL = "vollständig"
    LIMITED = "eingeschränkt"
    POOR = "unzureichend"


@dataclass(slots=True)
class DataQuality:
    score: int                              # 0..100
    label: str
    components: dict[str, float] = field(default_factory=dict)   # je 0..1
    issues: list[str] = field(default_factory=list)
    bars: int = 0
    age_days: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "label": self.label,
                "components": {k: round(v, 3) for k, v in self.components.items()},
                "issues": list(self.issues), "bars": self.bars,
                "age_days": (round(self.age_days, 1) if self.age_days is not None else None)}


def _age_days(as_of: str | None) -> float | None:
    if not as_of:
        return None
    try:
        stamp = datetime.fromisoformat(str(as_of))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400.0


def _split_ratio(r: float) -> str | None:
    """Liegt das Kursverhältnis nahe an einem glatten Split-Faktor?"""
    for f in SPLIT_RATIOS:
        if abs(r - f) / f < SPLIT_TOLERANCE:
            return f"1:{f}"
        if abs(r - 1.0 / f) * f < SPLIT_TOLERANCE:
            return f"{f}:1"
    return None


def _classify_move(candles: list[Candle], i: int) -> str:
    """Klassifiziert eine Tagesbewegung über `LARGE_MOVE` am Index i.

    Ein großer Kurssprung ist für sich genommen KEIN Datenfehler. Die
    Live-Analyse über 2170 solcher Sprünge ergab: 65,3 % sind echte
    Bewegungen, nur rund 20 % sind tatsächliche Datenprobleme. Eine Biotech-
    Aktie, die auf eine Zulassung 60 % steigt, darf dafür nicht abgewertet
    werden. Unterschieden wird deshalb nach dem, was die Reihe selbst hergibt:

      "real"      Bewegung mit Umsatz, die Bestand hat -> keine Abwertung
      "confirmed" zusätzlich mit deutlichem Volumenanstieg -> keine Abwertung
      "split"     glattes Split-Verhältnis -> Bereinigung fehlgeschlagen
      "reverted"  am Folgetag fast vollständig zurückgenommen -> Ausreißer
      "no_volume" Sprung ohne jeden Umsatz -> kein Handel, also kein Kurs
      "unconfirmed" Sprung verpufft und ohne Volumenbestätigung -> unklar
    """
    prev, cur = candles[i - 1], candles[i]
    ratio = cur.c / prev.c

    if not cur.v:
        return "no_volume"

    # Glattes Split-Verhältnis: hätte bereinigt sein müssen.
    if _split_ratio(ratio) is not None:
        return "split"

    # Kehrt der Sprung am Folgetag fast vollständig um, war es ein Ausreißer.
    if i + 1 < len(candles) and cur.c > 0:
        back = candles[i + 1].c / cur.c
        if abs(back * ratio - 1.0) < 0.12:
            return "reverted"

    # Volumenbestätigung gegen das lokale Normalmaß der 20 Tage davor.
    ref = candles[max(0, i - 20):i]
    vols = sorted(c.v for c in ref if c.v)
    median_v = vols[len(vols) // 2] if vols else 0.0
    confirmed = median_v > 0 and cur.v >= CONFIRM_VOLUME * median_v

    # Hat die Bewegung nach fünf Tagen Bestand?
    if i + 5 < len(candles):
        after = candles[i + 5].c / prev.c
        persists = (after > 1.15) if ratio > 1 else (after < 0.85)
        if persists:
            return "confirmed" if confirmed else "real"
        return "real" if confirmed else "unconfirmed"
    # Am Reihenende lässt sich Bestand nicht prüfen — Volumen entscheidet.
    return "confirmed" if confirmed else "unconfirmed"


def _series_quality(candles: list[Candle]) -> tuple[float, list[str]]:
    """Prüft die Kursreihe auf Lücken, Nulltage und echte Datenfehler."""
    issues: list[str] = []
    n = len(candles)
    if n < 2:
        return 0.0, ["zu wenige Kerzen für eine Prüfung"]

    zero_vol = sum(1 for c in candles if not c.v)
    # Wiederholte identische Schlusskurse deuten auf ausgesetzten Handel oder
    # eine fortgeschriebene Reihe hin — beides macht Indikatoren wertlos.
    flat = sum(1 for a, b in zip(candles, candles[1:]) if a.c == b.c)

    kinds: dict[str, int] = {}
    for i in range(1, n):
        if candles[i - 1].c > 0 and abs(candles[i].c / candles[i - 1].c - 1.0) > LARGE_MOVE:
            k = _classify_move(candles, i)
            kinds[k] = kinds.get(k, 0) + 1

    # Unmögliche Kerzen: Hoch unter Tief, Schluss außerhalb der Spanne.
    broken = sum(1 for c in candles
                 if c.h < c.l or c.c > c.h * 1.001 or c.c < c.l * 0.999)

    zero_share = zero_vol / n
    flat_share = flat / n
    if zero_share > 0.05:
        issues.append(f"{zero_share:.0%} der Tage ohne Umsatz")
    if flat_share > 0.15:
        issues.append(f"{flat_share:.0%} der Tage ohne Kursänderung")
    if kinds.get("split"):
        issues.append(f"{kinds['split']} Kurssprung/-sprünge mit glattem "
                      "Split-Verhältnis — Bereinigung vermutlich fehlgeschlagen")
    if kinds.get("reverted"):
        issues.append(f"{kinds['reverted']} Kurssprung/-sprünge am Folgetag "
                      "zurückgenommen — Ausreißer in der Reihe")
    if kinds.get("no_volume"):
        issues.append(f"{kinds['no_volume']} Kurssprung/-sprünge ganz ohne Umsatz")
    if kinds.get("unconfirmed"):
        issues.append(f"{kinds['unconfirmed']} große Bewegung(en) ohne "
                      "Volumenbestätigung")
    if broken:
        issues.append(f"{broken} widersprüchliche Kerze(n) (Hoch/Tief/Schluss)")

    # Nur echte Datenprobleme werden bestraft. "real" und "confirmed" gehen
    # bewusst NICHT ein — ein großer Kursmove ist eine Markttatsache.
    hard = kinds.get("split", 0) + kinds.get("reverted", 0) + kinds.get("no_volume", 0)
    soft = kinds.get("unconfirmed", 0)
    penalty = (min(zero_share * 2, 0.4) + min(flat_share, 0.3)
               + min(hard * 0.06, 0.25) + min(soft * 0.02, 0.10)
               + min(broken * 0.1, 0.3))
    return max(0.0, 1.0 - penalty), issues


def assess(candles: list[Candle], technicals: dict[str, float],
           fundamentals: dict[str, float] | None = None,
           *, as_of: str | None = None) -> DataQuality:
    """Datenqualität eines Instruments aus seinen Rohdaten."""
    fundamentals = fundamentals or {}
    n = len(candles)
    issues: list[str] = []
    comp: dict[str, float] = {}

    # Historientiefe
    comp["historie"] = min(n / FULL_HISTORY_BARS, 1.0)
    if n < 60:
        issues.append(f"nur {n} Handelstage Historie — Indikatoren wenig aussagekräftig")
    elif n < FULL_HISTORY_BARS:
        issues.append(f"{n} Handelstage — Jahreswerte (EMA200, 1-J-Rendite) unvollständig")

    # Aktualität
    age = _age_days(as_of)
    if age is None:
        comp["aktualitaet"] = 0.5
        issues.append("kein Zeitstempel der Datenbeschaffung")
    else:
        # Bis 3 Tage voll, danach linear bis 30 Tage auf 0.
        comp["aktualitaet"] = max(0.0, min(1.0, (30.0 - age) / 27.0)) if age > 3 else 1.0
        if age > 7:
            issues.append(f"Daten {age:.0f} Tage alt")

    # Indikatoren
    have = sum(1 for k in EXPECTED_INDICATORS if technicals.get(k) is not None)
    comp["indikatoren"] = have / len(EXPECTED_INDICATORS)
    if comp["indikatoren"] < 0.75:
        issues.append(f"nur {have} von {len(EXPECTED_INDICATORS)} Kennzahlen berechenbar")

    # Fundamentaldaten
    have_f = sum(1 for k in EXPECTED_FUNDAMENTALS if fundamentals.get(k) is not None)
    comp["fundamental"] = have_f / len(EXPECTED_FUNDAMENTALS)
    if have_f == 0:
        issues.append("keine Fundamentaldaten — Fundamental-Rating nicht belegt")
    elif comp["fundamental"] < 0.5:
        issues.append(f"nur {have_f} von {len(EXPECTED_FUNDAMENTALS)} Fundamentalkennzahlen")

    # Reihenqualität
    q, series_issues = _series_quality(candles)
    comp["reihe"] = q
    issues.extend(series_issues)

    # Gewichtung: Historie und Indikatoren tragen den technischen Teil, der im
    # Gesamtrating mit 60 % dominiert — entsprechend höher gewichtet.
    weights = {"historie": 0.28, "indikatoren": 0.24, "reihe": 0.20,
               "aktualitaet": 0.16, "fundamental": 0.12}
    score = sum(weights[k] * comp[k] for k in weights) * 100.0

    # Eine kaputte Kursreihe darf nicht weggemittelt werden. Bei 53 % Nulltagen
    # und 30 Sprüngen über 35 % ergab die reine Gewichtung noch 76/100, weil
    # Historie, Aktualität und Indikatoren voll punkteten — obwohl genau diese
    # Indikatoren auf einer unbrauchbaren Reihe berechnet wurden. Die
    # Reihenqualität deckelt deshalb das Gesamtergebnis, statt nur einzugehen.
    score = min(score, 40.0 + 60.0 * comp["reihe"])

    label = (QualityLabel.FULL if score >= 85
             else QualityLabel.LIMITED if score >= 60
             else QualityLabel.POOR)
    return DataQuality(score=round(score), label=label, components=comp,
                       issues=issues, bars=n, age_days=age)
