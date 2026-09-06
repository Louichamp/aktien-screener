"""Basis-Struktur am rechten Chartrand — Ableitung von Pivot, Kaufzone und Stopp.

ROLLE DIESES MODULS (bewusst eng): Es liefert die LEVEL eines Trades — wo
liegt der Deckel der Konsolidierung (Pivot), wo beginnt die Kaufzone, wo
gehört der Stopp hin, ab wo ist die These tot. Es liefert KEINE Bewertung,
ob ein Setup gut ist.

WARUM SO ENG — Messergebnis vom 2026-09-05 (`scripts/backtest_base.py`):
Eine frühere Fassung bewertete Basen mit einem Qualitäts-Score aus Dauer,
Tiefe, steigenden Tiefs, VCP-Kontraktion, Volumen-Dry-up und Pivot-Tests.
Der Score wurde über 15.193 Ausbrüche (318 Ticker, 12 Jahre) gemessen:

  * Korrelation zur Vorwärtsrendite: -0,061 — praktisch null.
  * Das scheinbare Muster „hohe Qualität → häufiger ausgestoppt" war
    vollständig ein Confounder der Stopp-Weite; innerhalb gleicher
    Stopp-Weiten-Bänder diskriminierte der Score nicht.
  * Gegen ein simples 60-Tage-Hoch verlor der Pivot dieses Moduls dort,
    wo der Ausbruchseffekt überhaupt existiert (Small/Mid Caps, 250 Bars):
    +1,13 pp gegen +1,56 pp.

Der Score wurde deshalb entfernt. Die beschreibenden Kennzahlen bleiben —
als ehrliche Beobachtung für die Anzeige, nicht als Prognose. Wer hier
wieder eine Bewertung einbaut, misst sie bitte vorher mit dem Backtest.

Die Fensterauswahl unten ist eine STRUKTURREGEL (welcher Bereich ist die
aktuelle Konsolidierung?), keine Aussage über Erfolgswahrscheinlichkeit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from scoring.normalization import band

from .zones import Candle

MIN_BASE_LEN = 15
MAX_BASE_LEN = 200
MAX_BASE_DEPTH = 0.55
EXTENDED_ATR = 1.5           # so weit über Pivot = Einstieg verpasst
MAX_PIVOT_DIST_ATR = 3.0     # weiter weg = Ausbruch nicht in Reichweite
MAX_PIVOT_DIST_PCT = 10.0
MAX_RISK_PCT = 0.15          # Pivot->Stopp; darüber ist das Setup nicht handelbar


class BaseState:
    NO_BASE = "keine Basis"
    FORMING = "Basis in Bildung"
    NEAR_PIVOT = "Pivot in Reichweite"
    BREAKOUT = "Pivot durchbrochen"
    EXTENDED = "über Kaufzone hinausgelaufen"
    FAILED = "Basis gebrochen"


@dataclass(slots=True)
class BaseFormation:
    """Die aktuelle Konsolidierung und die daraus abgeleiteten Level."""
    state: str
    start_idx: int
    length: int
    pivot: float                             # Deckel der Basis = Ausbruchspunkt
    base_low: float
    depth_pct: float

    buy_zone_low: float | None = None        # = pivot
    buy_zone_high: float | None = None       # = pivot + 0,4·ATR
    stop_suggest: float | None = None
    invalidation: float | None = None
    risk_pct: float | None = None

    # Rein beschreibend — ausdrücklich NICHT als Erfolgsprognose gemessen.
    position_in_base: float | None = None    # 0 = am Tief, 1 = am Pivot
    pivot_tests: int = 0
    bars_since_low: int = 0
    contraction: float | None = None
    volume_dryup: float | None = None
    low_rise: float | None = None
    dist_to_pivot_pct: float | None = None
    dist_to_pivot_atr: float | None = None
    rationale: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Hilfsfunktionen
# --------------------------------------------------------------------------- #
def _suffix_extremes(candles: list[Candle]) -> tuple[list[float], list[int], list[float], list[int]]:
    """Laufende Extrema von Index i bis zum Ende — ein Durchlauf statt O(n²).

    Alle Kandidatenfenster enden am rechten Chartrand, ihr Maximum ist also
    genau `smax[s]`. Damit kostet die Bewertung aller Fenster zusammen O(n).
    """
    n = len(candles)
    smax, smin = [0.0] * n, [0.0] * n
    smax_i, smin_i = [0] * n, [0] * n
    smax[n - 1], smin[n - 1] = candles[n - 1].h, candles[n - 1].l
    smax_i[n - 1] = smin_i[n - 1] = n - 1
    for i in range(n - 2, -1, -1):
        c = candles[i]
        if c.h >= smax[i + 1]:
            smax[i], smax_i[i] = c.h, i
        else:
            smax[i], smax_i[i] = smax[i + 1], smax_i[i + 1]
        if c.l <= smin[i + 1]:
            smin[i], smin_i[i] = c.l, i
        else:
            smin[i], smin_i[i] = smin[i + 1], smin_i[i + 1]
    return smax, smax_i, smin, smin_i


def _swing_lows(w: list[Candle], window: int = 3) -> list[tuple[int, float]]:
    """Lokale Tiefs MIT Index — `zones.swing_points` liefert nur Preise, für die
    Stopp-Ableitung brauchen wir aber die zeitliche Reihenfolge."""
    return [(i, w[i].l) for i in range(window, len(w) - window)
            if w[i].l <= min(c.l for c in w[i - window:i + window + 1])]


def _range_pct(w: list[Candle]) -> float | None:
    if not w:
        return None
    hi, lo = max(c.h for c in w), min(c.l for c in w)
    mid = (hi + lo) / 2.0
    return (hi - lo) / mid if mid > 0 else None


def _count_pivot_tests(w: list[Candle], pivot: float, tol: float) -> int:
    """Wie oft wurde der Deckel angelaufen und abgewiesen? Aufeinanderfolgende
    Berührungen zählen als EIN Test (erst nach 3 Bars darunter zählt neu)."""
    tests, in_touch, away = 0, False, 0
    for c in w:
        if c.h >= pivot - tol:
            if not in_touch:
                tests += 1
                in_touch = True
            away = 0
        elif in_touch:
            away += 1
            if away >= 3:
                in_touch = False
    return tests


def _describe(w: list[Candle], *, price: float, pivot: float, low: float,
              low_idx: int, atr: float) -> dict[str, float]:
    """Beschreibende Kennzahlen der Basis. Keine Bewertung, kein Score."""
    L = len(w)
    height = pivot - low
    third = max(L // 3, 2)
    f: dict[str, float] = {}

    half = L // 2
    lo_first = min(c.l for c in w[:half]) if half else low
    lo_second = min(c.l for c in w[half:]) if half else low
    f["low_rise"] = (lo_second - lo_first) / height if height > 0 else 0.0
    f["position_in_base"] = (price - low) / height if height > 0 else 0.0

    r_first, r_last = _range_pct(w[:third]), _range_pct(w[-third:])
    if r_first and r_last and r_first > 0:
        f["contraction"] = r_last / r_first

    v_first = sum(c.v for c in w[:third]) / third
    if v_first > 0:
        f["volume_dryup"] = (sum(c.v for c in w[-third:]) / third) / v_first

    tol = max(0.02 * pivot, 0.5 * atr) if pivot > 0 else atr
    f["pivot_tests"] = float(_count_pivot_tests(w, pivot, tol))
    f["bars_since_low"] = float(L - 1 - low_idx)
    return f


# --------------------------------------------------------------------------- #
#  Hauptfunktion
# --------------------------------------------------------------------------- #
def detect_base(candles: list[Candle], *, price: float, atr: float | None,
                ema_200: float | None = None,
                ema_200_slope: float | None = None) -> BaseFormation | None:
    """Findet die aktuelle Konsolidierung und leitet Pivot/Kaufzone/Stopp ab.

    `None`, wenn zu wenig Historie vorliegt oder kein Bereich die Struktur-
    kriterien erfüllt (zu tief, oder das Tief liegt noch am rechten Rand).

    `ema_200`/`ema_200_slope` werden nur für die Begründungstexte verwendet —
    sie fließen NICHT in eine Bewertung ein (siehe Modul-Docstring).
    """
    # Die Struktur wird aus der Historie OHNE die letzte Kerze bestimmt und
    # `price` dann dagegen geprüft. Sonst enthielte der Pivot das heutige Hoch
    # — und da ein Schlusskurs nie über dem eigenen Tageshoch liegt, wäre ein
    # Ausbruch über den eigenen Pivot rechnerisch unmöglich.
    hist = candles[:-1]
    n = len(hist)
    if n < MIN_BASE_LEN + 5 or price <= 0:
        return None
    atr = atr if (atr and atr > 0) else max(price * 0.02, 1e-9)

    smax, _smax_i, smin, smin_i = _suffix_extremes(hist)

    # ── Fensterauswahl (Strukturregel, keine Prognose) ──────────────────────
    # Gesucht ist der Bereich, der die aktuelle Konsolidierung am besten
    # abbildet: sauber begrenzte Spanne, Tief nicht am rechten Rand, Kurs
    # eher im oberen Teil. Kein Längen-Bonus — ein linear mit L wachsender
    # Term zieht die Auswahl sonst immer ans Maximum und erklärt dann
    # schlicht „das letzte Jahr" zur Basis.
    best_pre, best_s = None, None
    for L in range(MIN_BASE_LEN, min(MAX_BASE_LEN, n) + 1):
        s = n - L
        hi, lo = smax[s], smin[s]
        if hi <= 0 or lo <= 0 or hi <= lo:
            continue
        depth = (hi - lo) / hi
        if depth > MAX_BASE_DEPTH:
            continue
        low_idx = smin_i[s] - s
        if low_idx > 0.85 * L:
            continue
        pre = ((band(float(L), [(15, 0.4), (45, 1.0), (90, 1.0), (200, 0.5)]) or 0) * 0.35
               + (band(depth, [(0.05, 0.3), (0.15, 1.0), (0.30, 1.0), (0.55, 0.2)]) or 0) * 0.30
               + ((price - lo) / (hi - lo)) * 0.20
               + (low_idx / L) * 0.15)
        if best_pre is None or pre > best_pre:
            best_pre, best_s = pre, s

    if best_s is None:
        return None

    s = best_s
    w = hist[s:]
    L = len(w)
    pivot, low = smax[s], smin[s]
    depth = (pivot - low) / pivot
    facts = _describe(w, price=price, pivot=pivot, low=low,
                      low_idx=smin_i[s] - s, atr=atr)

    # ── Handelbare Level ────────────────────────────────────────────────────
    buy_low, buy_high = pivot, pivot + 0.4 * atr
    # Stopp unter das JÜNGSTE höhere Tief — nicht unter das Basistief: Bei
    # einer tiefen Basis liegt das weit unten, während der Einstieg oben am
    # Pivot erfolgt (in der Messung ergab das bis zu 29 % Strukturrisiko).
    sw = _swing_lows(w)
    last_third = [(i, p) for i, p in sw if i >= (2 * L) // 3]
    anchor = (last_third[-1][1] if last_third
              else min((p for i, p in sw if i >= L // 2), default=low))
    stop = anchor - 0.5 * atr
    if stop >= buy_low or stop <= 0:
        stop = low - 0.5 * atr
    risk_pct = (buy_low - stop) / buy_low if buy_low > 0 else 1.0

    dist_pct = (pivot - price) / pivot * 100.0 if pivot > 0 else None
    dist_atr = (pivot - price) / atr

    # ── Zustand (rein mechanisch: wo steht der Kurs zur Struktur?) ──────────
    near = (dist_atr <= MAX_PIVOT_DIST_ATR
            and (dist_pct is None or dist_pct <= MAX_PIVOT_DIST_PCT)
            and risk_pct <= MAX_RISK_PCT)
    if price < low:
        state = BaseState.FAILED
    elif price > pivot + EXTENDED_ATR * atr:
        state = BaseState.EXTENDED
    elif price > pivot:
        state = BaseState.BREAKOUT
    elif near:
        state = BaseState.NEAR_PIVOT
    else:
        state = BaseState.FORMING

    lr = facts.get("low_rise", 0.0)
    rat = [f"Konsolidierung über {L} Bars, Spanne {depth:.0%}, Pivot {pivot:.2f}",
           f"Tiefs {'steigend' if lr > 0.05 else 'seitwärts' if lr > -0.05 else 'fallend'}"
           f" ({lr:+.0%} der Spanne)"]
    if "contraction" in facts:
        rat.append(f"Spannweite letztes/erstes Drittel: {facts['contraction']:.2f}×")
    if "volume_dryup" in facts:
        rat.append(f"Volumen {facts['volume_dryup']:.2f}× ggü. Beginn")
    rat.append(f"Pivot {int(facts['pivot_tests'])}× getestet, Tief liegt "
               f"{int(facts['bars_since_low'])} Bars zurück")
    rat.append(f"Kurs bei {facts['position_in_base']:.0%} der Spanne, "
               f"Risiko Pivot bis Stopp {risk_pct:.1%}")
    if risk_pct > MAX_RISK_PCT:
        rat.append(f"Strukturrisiko über {MAX_RISK_PCT:.0%} — Level nur informativ")
    if ema_200 and price < ema_200 and (ema_200_slope or 0.0) < 0:
        rat.append("unter fallender EMA200")

    return BaseFormation(
        state=state, start_idx=s, length=L,
        pivot=round(pivot, 4), base_low=round(low, 4), depth_pct=round(depth, 4),
        buy_zone_low=round(buy_low, 4), buy_zone_high=round(buy_high, 4),
        stop_suggest=round(stop, 4), invalidation=round(low, 4),
        risk_pct=round(risk_pct, 4),
        position_in_base=round(facts["position_in_base"], 3),
        pivot_tests=int(facts["pivot_tests"]),
        bars_since_low=int(facts["bars_since_low"]),
        contraction=(round(facts["contraction"], 3) if "contraction" in facts else None),
        volume_dryup=(round(facts["volume_dryup"], 3) if "volume_dryup" in facts else None),
        low_rise=round(facts["low_rise"], 4),
        dist_to_pivot_pct=(round(dist_pct, 2) if dist_pct is not None else None),
        dist_to_pivot_atr=round(dist_atr, 2),
        rationale=rat,
    )
