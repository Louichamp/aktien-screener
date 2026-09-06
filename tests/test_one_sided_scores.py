"""Regressionstests: einseitige Scores dürfen nicht wie vollständige wirken.

`compute_total_score` renormiert auf die vorhandene Säule, wenn eine fehlt.
Ein rein technischer Wert von 8,6/10 wurde dadurch zu „86/100" — optisch nicht
von einem Titel zu unterscheiden, der 86 mit BEIDEN Säulen erreicht.

Live gemessen am 2026-09-06 auf der Produktionsinstanz:
  * 203 von 932 Kaufempfehlungen (21,8 %) standen auf nur einer Säule.
  * AISPW: 98/100 STARK KAUFEN — ein 0,50-$-Warrant mit EINEM Kurspunkt,
    ohne technisches Rating; die 98 kamen allein aus wlafar=10.
  * ANNAW: 90/100 STARK KAUFEN bei 0,165 $, ebenfalls ohne technisches Rating.

Die Datenqualität allein fängt das nicht ab: Ein Titel mit voller Kurshistorie,
aber ohne Fundamentaldaten erreicht 87/100 Datenqualität, weil die fundamentale
Komponente dort nur 12 % Gewicht hat. Im lokalen Volllauf standen so 1247
Kaufempfehlungen auf halber Beweislage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infrastructure.database.repository import (MIN_QUALITY_FOR_RATING,
                                                RATING_UNCLEAR,
                                                compute_total_score, rating_label)
from screener.data_quality import assess
from screener.zones import Candle


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------- #
#  Der konkrete Live-Fehlerfall
# --------------------------------------------------------------------------- #
def test_aispw_fall_wird_nicht_mehr_zu_stark_kaufen():
    """AISPW live: 1 Kurspunkt, kein technisches Rating, wlafar=10 -> 98/100
    STARK KAUFEN und damit Platz 1 des Screeners."""
    candles = [Candle(0.5, 0.5, 0.5, 0.5, 1000.0)]
    q = assess(candles, {}, {"net_margin": 0.3, "roic": 0.2,
                             "revenue_growth": 0.92, "pe": 5.0},
               as_of=_iso(8))
    total = compute_total_score(None, 10.0)          # nur fundamental

    assert total == 100, "Der Score selbst bleibt unverändert — er ist ehrlich"
    assert q.score < MIN_QUALITY_FOR_RATING, f"Datenqualität {q.score} zu hoch"
    assert rating_label(total, q.score, complete=False) == RATING_UNCLEAR
    # Vorher:
    assert rating_label(total) == "STARK KAUFEN"


def test_nur_technisch_mit_guter_datenlage_wird_gedeckelt():
    """Der Fall, den die Datenqualität NICHT abfängt: volle Kurshistorie, aber
    keine Fundamentaldaten. Datenqualität ~87, also über der Sperre — trotzdem
    beruht das Rating nur auf der halben Beweislage."""
    assert rating_label(86, 87, complete=True) == "STARK KAUFEN"
    assert rating_label(86, 87, complete=False) == "KAUFEN"


def test_deckelung_wirkt_in_beide_richtungen():
    """Auch eine Verkaufsempfehlung ist die stärkste Aussage ihrer Richtung
    und setzt beide Säulen voraus."""
    assert rating_label(20, 90, complete=True) == "VERKAUFEN"
    assert rating_label(20, 90, complete=False) == "REDUZIEREN"


# --------------------------------------------------------------------------- #
#  Die vier Fälle müssen unterscheidbar bleiben
# --------------------------------------------------------------------------- #
def test_die_vier_faelle_sind_unterscheidbar():
    hoch = 86
    beide = rating_label(hoch, 90, complete=True)
    einseitig = rating_label(hoch, 90, complete=False)
    duenn = rating_label(hoch, 30, complete=False)
    ohne = rating_label(None, 90)

    assert beide == "STARK KAUFEN"
    assert einseitig == "KAUFEN"
    assert duenn == RATING_UNCLEAR
    assert ohne is None
    assert len({beide, einseitig, duenn, str(ohne)}) == 4


def test_mittlere_stufen_bleiben_unveraendert():
    """Nur die stärkste Aussage je Richtung wird gedeckelt — HALTEN, KAUFEN und
    REDUZIEREN sind keine Extremaussagen und bleiben, wie sie waren."""
    for score in (70, 55, 40):
        assert rating_label(score, 90, complete=True) == \
               rating_label(score, 90, complete=False)


# --------------------------------------------------------------------------- #
#  compute_total_score bleibt bewusst unverändert
# --------------------------------------------------------------------------- #
def test_score_wird_nicht_manipuliert():
    """Der Score selbst wird NICHT künstlich gesenkt. Er ist eine ehrliche
    Rechnung über das Vorhandene; nur die Handlungsempfehlung berücksichtigt,
    worauf er beruht. Ein zweites, paralleles Scoring wäre schwerer zu prüfen
    als eines mit klar benannten Grenzen."""
    assert compute_total_score(8.6, None) == 86
    assert compute_total_score(None, 8.6) == 86
    assert compute_total_score(8.6, 8.6) == 86
    assert compute_total_score(None, None) is None


def test_vollstaendigkeit_ist_standard():
    """Ohne Angabe verhält sich rating_label wie bisher — sonst würden
    Altbestände ohne die neuen Felder schlagartig abgewertet."""
    assert rating_label(86) == "STARK KAUFEN"
    assert rating_label(20) == "VERKAUFEN"
