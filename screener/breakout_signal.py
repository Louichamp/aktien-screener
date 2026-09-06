"""Ausbruchs-Kaufsignal — auf gemessener Grundlage, nicht auf Lehrbuchannahme.

Dieses Modul implementiert GENAU das Signal, für das eine Vorhersagekraft
tatsächlich nachgewiesen wurde, und nichts darüber hinaus. Die Messung
(`scripts/backtest_base.py` und Segment-Kalibrierung, 2026-09-05, 782 Ticker,
12 Jahre, point-in-time, winsorisiert und liquiditätsgefiltert):

  Signal:   Schlusskurs durchbricht das Hoch der letzten 60 Bars
  Horizont: ~250 Bars (12 Monate) — auf 20 und 60 Bars ist der Effekt NEGATIV
  Segment:  nur bei niedrigem Tagesumsatz; oberhalb ~20 Mio USD verschwindet er

    Median-Tagesumsatz    Δ Median ggü. Durchschnittstag    Trefferquote
    < 1 Mio USD                     +8,01 pp                   55,4 %
    1–5 Mio USD                     +2,23 pp                   49,6 %
    5–20 Mio USD                    +3,92 pp                   59,0 %
    20–100 Mio USD                  −1,34 pp                   64,5 %
    100–500 Mio USD                 −0,76 pp                   65,6 %
    > 500 Mio USD                   +0,34 pp                   66,7 %

Bewusste Entscheidungen daraus:

  * KEIN Qualitäts-Score. Eine frühere, aufwendigere Bewertung (Basis-Dauer,
    VCP-Kontraktion, Volumen-Dry-up, Pivot-Tests) wurde gemessen und war
    uninformativ (Korrelation zur Rendite −0,061); sie verlor sogar gegen
    dieses simple 60-Tage-Hoch. Siehe `screener/base_formation.py`.
  * KEINE Volumenbestätigung am Ausbruchstag. In der Messung trennte sie
    nicht (0–1× Volumen: +2,52 % / 1,5–2,5×: +0,02 %).
  * Unterhalb von 1 Mio USD Tagesumsatz wird NICHT gemeldet, obwohl der
    gemessene Effekt dort am größten ist: Bei dem Umsatz bewegt die eigene
    Order den Kurs, und die Datenqualität ist schlecht (58 % der Rohdaten
    in diesem Bereich waren Penny-Werte oder Fehl-Adjustierungen).

Wer dieses Signal ändert, misst es bitte vorher mit dem Backtest neu.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .zones import Candle

LOOKBACK = 60                      # Bars für das Ausbruchshoch (gemessen)
MEASURED_HORIZON_BARS = 250        # Horizont, auf dem der Vorteil auftrat
MIN_PRICE = 5.0                    # darunter: Penny-Bereich, Datenqualität
MIN_DOLLAR_VOLUME = 1_000_000.0    # darunter: nicht handelbar
MAX_DOLLAR_VOLUME = 20_000_000.0   # darüber: kein gemessener Vorteil


@dataclass(slots=True)
class BreakoutSignal:
    applicable: bool                 # liegt der Titel im gemessenen Segment?
    triggered: bool                  # heute über das 60-Bar-Hoch geschlossen?
    breakout_level: float | None     # das durchbrochene Hoch
    dollar_volume: float | None      # Median der letzten 60 Bars
    segment: str
    reason: str
    horizon_hint: str = "gemessener Vorteil auf ~12 Monate Haltedauer"


def _segment(dv: float) -> str:
    if dv < MIN_DOLLAR_VOLUME:
        return "illiquide"
    if dv < 5_000_000:
        return "gering (1–5 Mio $)"
    if dv < MAX_DOLLAR_VOLUME:
        return "mittel (5–20 Mio $)"
    if dv < 100_000_000:
        return "hoch (20–100 Mio $)"
    return "sehr hoch (> 100 Mio $)"


def evaluate_breakout(candles: list[Candle], *, price: float) -> BreakoutSignal | None:
    """Prüft das gemessene Ausbruchssignal. `None` bei zu wenig Historie.

    Der Vergleich nutzt den VORTAGES-Schluss gegen das Hoch der 60 Bars davor,
    damit ein Titel, der schon länger über dem Niveau notiert, nicht jeden Tag
    erneut als frischer Ausbruch gemeldet wird.
    """
    if len(candles) < LOOKBACK + 2 or price <= 0:
        return None

    window = candles[-(LOOKBACK + 1):-1]          # die 60 Bars VOR heute
    level = max(c.h for c in window)
    dv = statistics.median(c.c * c.v for c in window)
    seg = _segment(dv)

    if price < MIN_PRICE:
        return BreakoutSignal(False, False, level, dv, seg,
                              f"Kurs unter {MIN_PRICE:.0f} $ — Penny-Bereich "
                              f"ausgeschlossen (Datenqualität)")
    if dv < MIN_DOLLAR_VOLUME:
        return BreakoutSignal(False, False, level, dv, seg,
                              "Tagesumsatz unter 1 Mio $ — praktisch nicht "
                              "handelbar, Signal wird nicht gemeldet")
    if dv > MAX_DOLLAR_VOLUME:
        return BreakoutSignal(False, False, level, dv, seg,
                              "Tagesumsatz über 20 Mio $ — in diesem Segment "
                              "wurde KEIN Ausbruchsvorteil gemessen")

    prev_close = candles[-2].c
    triggered = prev_close <= level < price
    if triggered:
        reason = (f"Schlusskurs {price:.2f} über dem 60-Bar-Hoch {level:.2f}; "
                  f"Segment {seg} — dort +2,2 bis +3,9 pp über dem "
                  f"Durchschnittstag auf 12 Monate")
    elif price > level:
        reason = (f"bereits über dem 60-Bar-Hoch {level:.2f} — kein frischer "
                  f"Ausbruch mehr")
    else:
        reason = (f"{(level / price - 1.0) * 100:.1f} % unter dem "
                  f"60-Bar-Hoch {level:.2f}")
    return BreakoutSignal(True, triggered, round(level, 4), round(dv, 0), seg, reason)
