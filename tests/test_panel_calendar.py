"""Tests fuer die gemeinsame Stichtagsachse der Querschnitts-Backtests.

Kern des Problems: Ein Querschnitts-Rang-IC vergleicht viele Titel zu EINEM
Zeitpunkt. Wird ueber den Listenindex ausgerichtet, bedeutet derselbe Index
bei unterschiedlich langen Historien fuer jeden Titel einen anderen
Kalendertag — der Querschnitt vermischt Marktphasen.
"""
from __future__ import annotations

from scoring.validation.panel import build_panel_calendar
from screener.zones import Candle


def _series(days: list[str]) -> list[Candle]:
    return [Candle(1.0, 1.0, 1.0, float(i + 1), 100.0, d)
            for i, d in enumerate(days)]


def _undated(n: int) -> list[Candle]:
    return [Candle(1.0, 1.0, 1.0, float(i + 1), 100.0) for i in range(n)]


# --------------------------------------------------------------------------- #
#  Datumsbasierte Ausrichtung
# --------------------------------------------------------------------------- #
def test_gleicher_stichtag_trifft_gleichen_kalendertag():
    """Der eigentliche Fix: unterschiedlich lange Historien, gleicher Tag."""
    lang = _series(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    kurz = _series(["2026-01-07", "2026-01-08"])          # spaeterer Boersengang
    cal = build_panel_calendar({"LANG": lang, "KURZ": kurz})

    assert cal.dated
    j = cal._dates.index("2026-01-07")
    assert lang[cal.index_at("LANG", j)].ts == "2026-01-07"
    assert kurz[cal.index_at("KURZ", j)].ts == "2026-01-07"


def test_titel_ohne_historie_am_stichtag_faellt_raus():
    lang = _series(["2026-01-05", "2026-01-06", "2026-01-07"])
    kurz = _series(["2026-01-07"])
    cal = build_panel_calendar({"LANG": lang, "KURZ": kurz})
    j = cal._dates.index("2026-01-05")
    assert cal.index_at("LANG", j) == 0
    assert cal.index_at("KURZ", j) is None, "vor dem Boersengang gibt es nichts"


def test_handelsfreier_tag_nutzt_die_letzte_vorherige_kerze():
    """Ein Titel, der an einem Tag nicht handelte, darf nicht in die Zukunft
    greifen — es gilt die juengste Kerze DAVOR."""
    a = _series(["2026-01-05", "2026-01-06", "2026-01-07"])
    b = _series(["2026-01-05", "2026-01-07"])             # 06. ausgesetzt
    cal = build_panel_calendar({"A": a, "B": b})
    j = cal._dates.index("2026-01-06")
    assert b[cal.index_at("B", j)].ts == "2026-01-05"


def test_niemals_zukunftskerze():
    a = _series(["2026-01-05", "2026-01-09"])
    cal = build_panel_calendar({"A": a})
    for j in range(cal.n):
        idx = cal.index_at("A", j)
        if idx is not None:
            assert a[idx].ts <= cal.label(j)


# --------------------------------------------------------------------------- #
#  Rueckfall ohne Datumsangaben (alte Caches)
# --------------------------------------------------------------------------- #
def test_ohne_datum_wird_vom_ENDE_ausgerichtet():
    """Alte Caches haben kein Datum. Dann ist die Ausrichtung am Reihenende
    korrekt, solange alle Reihen am selben Tag enden — im Gegensatz zur
    frueheren Ausrichtung am Reihenanfang."""
    lang, kurz = _undated(100), _undated(40)
    cal = build_panel_calendar({"LANG": lang, "KURZ": kurz})

    assert not cal.dated and cal.n == 100
    letzter = cal.n - 1
    assert cal.index_at("LANG", letzter) == 99
    assert cal.index_at("KURZ", letzter) == 39, "beide zeigen auf die letzte Kerze"
    # einen Tag davor ebenso
    assert cal.index_at("LANG", letzter - 1) == 98
    assert cal.index_at("KURZ", letzter - 1) == 38


def test_ohne_datum_vor_dem_reihenbeginn_gibt_es_nichts():
    cal = build_panel_calendar({"LANG": _undated(100), "KURZ": _undated(40)})
    assert cal.index_at("KURZ", 0) is None
    assert cal.index_at("LANG", 0) == 0


def test_teilweise_datumsangaben_fallen_ganz_zurueck():
    """Gemischter Betrieb waere schlimmer als beide Einzelvarianten."""
    cal = build_panel_calendar({"MIT": _series(["2026-01-05", "2026-01-06"]),
                                "OHNE": _undated(2)})
    assert not cal.dated


# --------------------------------------------------------------------------- #
#  Stichtagsauswahl
# --------------------------------------------------------------------------- #
def test_positions_laesst_vorlauf_und_nachlauf():
    cal = build_panel_calendar({"A": _undated(100)})
    pos = cal.positions(min_history=20, horizon=10, step=5)
    assert pos[0] == 20
    assert max(pos) <= cal.n - 10, "Vorwaertsrendite muss noch messbar sein"
    assert pos[1] - pos[0] == 5


def test_positions_leer_wenn_historie_nicht_reicht():
    cal = build_panel_calendar({"A": _undated(30)})
    assert cal.positions(min_history=25, horizon=20, step=5) == []


def test_leeres_panel_stuerzt_nicht_ab():
    cal = build_panel_calendar({})
    assert cal.n == 0 and cal.positions(min_history=0, horizon=0, step=1) == []
