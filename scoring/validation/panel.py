"""Gemeinsame Stichtagsachse für Querschnitts-Backtests.

Das Problem, das dieses Modul löst: Ein Querschnitts-Rang-IC vergleicht Signale
und Vorwärtsrenditen VIELER Titel zu EINEM Zeitpunkt. Die bisherige
Implementierung bildete den Querschnitt über den Listenindex:

    for t in range(min_history, max_len - max_h, step):
        hist = candles[: t + 1]          # je Ticker eigener Index!

Da Titel unterschiedlich lange Historien haben (spätere Börsengänge, Lücken),
bedeutet derselbe Index für jeden Titel einen ANDEREN Kalendertag. Der
„Querschnitt" mischte damit Marktphasen — und genau das setzt weder der IC
noch die Regime-Klassifikation voraus. Systematisch betroffen sind die jüngeren
Titel, weil sie die kürzesten Historien haben.

`PanelCalendar` richtet stattdessen an echten Handelstagen aus. Liegen (bei
alten Caches) keine Datumsangaben vor, wird vom REIHENENDE her ausgerichtet —
das ist korrekt, solange alle Reihen am selben Tag enden, und in jedem Fall
deutlich besser als die Ausrichtung am Reihenanfang. Der Rückfall wird
ausgewiesen und nicht stillschweigend vollzogen.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(slots=True)
class PanelCalendar:
    """Achse von Stichtagen plus Auflösung „welcher Index gilt für Titel X?".

    Die Achse läuft von alt (`j = 0`) nach neu (`j = n - 1`).
    """
    dated: bool
    n: int
    _dates: list[str] = field(default_factory=list)
    _ticker_dates: dict[str, list[str]] = field(default_factory=dict)
    _lengths: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def label(self, j: int) -> str:
        """Anzeigename des Stichtags — echtes Datum oder Abstand zum Ende."""
        if self.dated:
            return self._dates[j]
        return f"T-{self.n - 1 - j}"

    def index_at(self, ticker: str, j: int) -> int | None:
        """Index der jüngsten Kerze dieses Titels am Stichtag `j`.

        `None`, wenn der Titel zu diesem Zeitpunkt noch keine Historie hatte.
        Es wird NIE ein Index zurückgegeben, dessen Kerze nach dem Stichtag
        liegt — das wäre Zukunftswissen.
        """
        if self.dated:
            days = self._ticker_dates.get(ticker)
            if not days:
                return None
            pos = bisect_right(days, self._dates[j]) - 1
            return pos if pos >= 0 else None
        n = self._lengths.get(ticker, 0)
        idx = n - 1 - (self.n - 1 - j)          # Abstand vom Reihenende
        return idx if idx >= 0 else None

    def positions(self, *, min_history: int, horizon: int, step: int) -> list[int]:
        """Stichtags-Positionen, die genug Vorlauf UND Nachlauf haben."""
        start = max(min_history, 0)
        stop = self.n - horizon
        return list(range(start, max(start, stop), step))


def _dates_of(candles: Sequence[Any]) -> list[str] | None:
    """Sortierte Datumsliste einer Kerzenreihe, oder None wenn unvollständig."""
    out: list[str] = []
    for c in candles:
        ts = getattr(c, "ts", None)
        if not ts:
            return None
        out.append(ts)
    return out


def build_panel_calendar(series: dict[str, Sequence[Any]]) -> PanelCalendar:
    """Baut die gemeinsame Achse aus allen Kerzenreihen.

    Datumsbasiert, sobald JEDE Reihe durchgehend Datumsangaben hat. Fehlt auch
    nur eine, wird für das gesamte Panel vom Reihenende her ausgerichtet —
    ein gemischter Betrieb wäre schlimmer als beide Einzelvarianten, weil dann
    ein Teil der Titel anders ausgerichtet wäre als der Rest.
    """
    if not series:
        return PanelCalendar(dated=False, n=0)

    ticker_dates: dict[str, list[str]] = {}
    complete = True
    for tk, candles in series.items():
        d = _dates_of(candles)
        if d is None:
            complete = False
            break
        ticker_dates[tk] = d

    if complete:
        all_days = sorted({day for days in ticker_dates.values() for day in days})
        return PanelCalendar(dated=True, n=len(all_days), _dates=all_days,
                             _ticker_dates=ticker_dates)

    lengths = {tk: len(c) for tk, c in series.items()}
    return PanelCalendar(dated=False, n=max(lengths.values(), default=0),
                         _lengths=lengths)
