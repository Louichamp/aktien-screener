"""Die Rating-Leiter und der Wegfall von „STARK KAUFEN".

Der Walk-Forward-Test ueber 12 Jahre (782 Titel, 124 Stichtage, 55.821
Beobachtungen, docs/AUDIT_2026-09.md) zeigte, dass die oberste Klasse des
technischen Ratings auf ALLEN geprueften Horizonten die schlechteste war:

    Klasse 80-90     5 Tage  -0,11 %    20 Tage  +0,21 %
                    60 Tage  -0,87 %   120 Tage  -1,33 %   Trefferquote 48,8 %
    Klasse 40-50    60 Tage  +3,82 %   120 Tage  +6,47 %

Eine Hoechststufe, die historisch am schlechtesten abschnitt, ist als
Handlungsempfehlung nicht zu verantworten. Sie wurde deshalb ersatzlos
entfernt; „KAUFEN" ist seither die staerkste Aussage des Systems.

Diese Tests halten die Entscheidung fest, damit sie nicht unbemerkt
zurueckgedreht wird.
"""
from __future__ import annotations

import pytest

from infrastructure.database.repository import (MIN_QUALITY_FOR_RATING,
                                                RATING_UNCLEAR, rating_label)

ERLAUBTE_LABELS = {"KAUFEN", "HALTEN", "REDUZIEREN", "VERKAUFEN", RATING_UNCLEAR}


# --------------------------------------------------------------------------- #
#  „STARK KAUFEN" wird nicht mehr vergeben
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("score", [80, 85, 90, 95, 100])
def test_kein_stark_kaufen_mehr(score: int):
    assert rating_label(score, 90) == "KAUFEN"


def test_ueber_den_gesamten_wertebereich_kein_stark_kaufen():
    for score in range(0, 101):
        for dq in (None, 60, 90, 100):
            assert rating_label(score, dq) != "STARK KAUFEN"


def test_nur_noch_die_erlaubten_labels():
    for score in range(0, 101):
        for dq in (None, 30, 59, 60, 100):
            for complete in (True, False):
                label = rating_label(score, dq, complete=complete)
                assert label in ERLAUBTE_LABELS, f"unerwartet: {label}"


# --------------------------------------------------------------------------- #
#  Die uebrigen Stufen bleiben unveraendert
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("score,erwartet", [
    (100, "KAUFEN"), (80, "KAUFEN"), (65, "KAUFEN"),
    (64, "HALTEN"), (50, "HALTEN"),
    (49, "REDUZIEREN"), (35, "REDUZIEREN"),
    (34, "VERKAUFEN"), (0, "VERKAUFEN"),
])
def test_schwellen_65_50_35_bleiben(score: int, erwartet: str):
    assert rating_label(score, 90) == erwartet


def test_die_leiter_ist_monoton():
    """Ein hoeherer Score darf nie eine schwaechere Empfehlung ergeben."""
    rang = {"VERKAUFEN": 0, "REDUZIEREN": 1, "HALTEN": 2, "KAUFEN": 3}
    vorher = -1
    for score in range(0, 101):
        jetzt = rang[rating_label(score, 90)]
        assert jetzt >= vorher, f"Ruecksprung bei Score {score}"
        vorher = jetzt


# --------------------------------------------------------------------------- #
#  Die bestehenden Schutzmechanismen greifen weiterhin
# --------------------------------------------------------------------------- #
def test_datenqualitaetssperre_bleibt():
    assert rating_label(90, MIN_QUALITY_FOR_RATING - 1) == RATING_UNCLEAR
    assert rating_label(20, MIN_QUALITY_FOR_RATING - 1) == RATING_UNCLEAR


def test_deckelung_einseitiger_scores_wirkt_weiterhin_nach_unten():
    assert rating_label(20, 90, complete=True) == "VERKAUFEN"
    assert rating_label(20, 90, complete=False) == "REDUZIEREN"


def test_ohne_score_keine_empfehlung():
    assert rating_label(None) is None
    assert rating_label(None, 100) is None
