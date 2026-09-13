"""Tests fuer das Datumsfeld der Kerze und die Cache-Vertraeglichkeit.

Ohne Zeitstempel koennen Backtests Querschnitte nur ueber den Listenindex
bilden. Da Titel unterschiedlich lange Historien haben, bedeutet derselbe Index
fuer jeden Titel einen anderen Kalendertag — der „Querschnitt" vermischt
Zeitpunkte, obwohl Rang-IC und Regime-Klassifikation denselben Stichtag
voraussetzen.

Kritisch an der Umsetzung: `Candle` nutzt `slots=True` und wird gepickelt im
GitHub-Actions-Cache abgelegt. Ein zusaetzlicher Slot bliebe beim Entpickeln
alter Daten UNGESETZT und wuerde beim Zugriff eine AttributeError werfen —
der gesamte Snapshot-Cache waere unlesbar und ein vollstaendiger Neuabruf
aller Titel noetig.
"""
from __future__ import annotations

import pickle

from screener.zones import Candle


def test_ts_ist_optional():
    """Bestehender Konstruktionscode (5 positionale Argumente) bleibt gueltig."""
    c = Candle(1.0, 2.0, 0.5, 1.5, 100.0)
    assert c.ts is None


def test_ts_wird_gesetzt_und_gelesen():
    c = Candle(1.0, 2.0, 0.5, 1.5, 100.0, "2026-09-13")
    assert c.ts == "2026-09-13"


def test_roundtrip_pickle_mit_datum():
    c = Candle(1.0, 2.0, 0.5, 1.5, 100.0, "2026-09-13")
    assert pickle.loads(pickle.dumps(c)) == c


def test_altes_pickle_ohne_ts_bleibt_lesbar():
    """Der eigentliche Schutz: ein vor der Aenderung geschriebener Cache.

    Nachgestellt wird exakt der Zustand, den `slots`-Pickles haben:
    (None, {slot: wert}) — hier ohne den neuen Slot `ts`.
    """
    alt = Candle.__new__(Candle)
    alt.__setstate__((None, {"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100.0}))
    assert alt.ts is None, "fehlendes Datum muss auf None fallen, nicht werfen"
    assert (alt.o, alt.h, alt.l, alt.c, alt.v) == (1.0, 2.0, 0.5, 1.5, 100.0)


def test_altes_pickle_ueberlebt_den_vollen_roundtrip():
    alt = Candle.__new__(Candle)
    alt.__setstate__((None, {"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100.0}))
    wieder = pickle.loads(pickle.dumps(alt))
    assert wieder.ts is None and wieder.c == 1.5


def test_setstate_akzeptiert_auch_reines_dict():
    """Defensive Absicherung gegen abweichende Pickle-Protokolle."""
    alt = Candle.__new__(Candle)
    alt.__setstate__({"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100.0})
    assert alt.ts is None and alt.o == 1.0


def test_iso_datum_sortiert_chronologisch():
    """Lexikographische Sortierung muss der Zeitachse entsprechen —
    darauf beruht die datumsbasierte Ausrichtung im Backtest."""
    tage = ["2026-01-09", "2025-12-31", "2026-10-02", "2026-02-01"]
    assert sorted(tage) == ["2025-12-31", "2026-01-09", "2026-02-01", "2026-10-02"]


def test_iso_day_helfer():
    from datetime import datetime

    from infrastructure.providers.yahoo import _iso_day

    assert _iso_day(datetime(2026, 9, 13, 15, 30)) == "2026-09-13"
    assert _iso_day("2026-09-13 00:00:00") == "2026-09-13"
    assert _iso_day(None) is None
