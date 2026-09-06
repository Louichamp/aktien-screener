"""Tests für die Datenqualitäts-Kennzahl.

Kernanliegen: Ein Score von 87/100 darf nicht identisch aussehen, ob er auf
zwölf Jahren lückenloser Historie beruht oder auf acht Wochen Kursen ohne jede
Fundamentalkennzahl. Gemessen an 250 echten Titeln reicht die Spanne von 46
(53 % Nulltage, 30 Tagessprünge über 35 %) bis 94.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infrastructure.providers.indicators import technicals_from_candles
from screener.data_quality import (FULL_HISTORY_BARS, QualityLabel, assess)
from screener.zones import Candle


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _series(n: int, *, volume: float = 500_000.0, start: float = 50.0,
            step: float = 0.004) -> list[Candle]:
    out, px = [], start
    for i in range(n):
        px *= (1.0 + step * (1 if i % 3 else -1))
        out.append(Candle(px * 0.999, px * 1.01, px * 0.99, px, volume))
    return out


def _assess(candles, *, fundamentals=None, age=1.0):
    return assess(candles, technicals_from_candles(candles, price=candles[-1].c),
                  fundamentals if fundamentals is not None else
                  {"net_margin": 0.1, "roic": 0.12, "pe": 18.0, "revenue_growth": 0.05,
                   "ev_ebitda": 11.0, "p_b": 3.0, "debt_to_equity": 0.4,
                   "fcf_margin": 0.15},
                  as_of=_iso(age))


# --------------------------------------------------------------------------- #
#  Historientiefe
# --------------------------------------------------------------------------- #
def test_volle_historie_ist_vollstaendig():
    q = _assess(_series(FULL_HISTORY_BARS + 60))
    assert q.label == QualityLabel.FULL
    assert q.score >= 85


def test_kurze_historie_wird_abgewertet_und_benannt():
    """Ein RSI aus 40 Bars ist rechnerisch gültig und trotzdem wenig wert."""
    lang = _assess(_series(FULL_HISTORY_BARS + 60))
    kurz = _assess(_series(40))
    assert kurz.score < lang.score
    assert kurz.label != QualityLabel.FULL
    assert any("Handelstage" in i for i in kurz.issues)


def test_fehlende_fundamentaldaten_werden_benannt():
    q = _assess(_series(FULL_HISTORY_BARS + 60), fundamentals={})
    assert any("Fundamentaldaten" in i for i in q.issues)
    assert q.components["fundamental"] == 0.0


# --------------------------------------------------------------------------- #
#  Aktualität
# --------------------------------------------------------------------------- #
def test_alte_daten_senken_die_qualitaet():
    frisch = _assess(_series(300), age=1)
    alt = _assess(_series(300), age=25)
    assert alt.score < frisch.score
    assert any("Tage alt" in i for i in alt.issues)


def test_ohne_zeitstempel_wird_nicht_volle_punktzahl_vergeben():
    q = assess(_series(300), technicals_from_candles(_series(300), price=50.0),
               {}, as_of=None)
    assert q.components["aktualitaet"] < 1.0
    assert any("Zeitstempel" in i for i in q.issues)


# --------------------------------------------------------------------------- #
#  Reihenqualität — die eigentlichen Datenfehler
# --------------------------------------------------------------------------- #
def test_nulltage_werden_erkannt():
    c = _series(300)
    for i in range(0, 300, 3):
        c[i] = Candle(c[i].o, c[i].h, c[i].l, c[i].c, 0.0)
    q = _assess(c)
    assert any("ohne Umsatz" in i for i in q.issues)


# --------------------------------------------------------------------------- #
#  Klassifikation grosser Kursbewegungen
#
#  Die Live-Analyse ueber 2170 Spruenge >35 % ergab: 65,3 % sind echte
#  Bewegungen, nur rund 20 % echte Datenprobleme. Eine Pauschalstrafe wertete
#  Titel ab, die schlicht stark gestiegen sind.
# --------------------------------------------------------------------------- #
def _scale(k: Candle, f: float, volume=None) -> Candle:
    return Candle(k.o * f, k.h * f, k.l * f, k.c * f,
                  k.v if volume is None else volume)


def _jump(c, i, factor, *, volume=None, revert=False, persist=True):
    """Setzt an Position i einen Kurssprung.

    `persist` skaliert ALLE Folgekerzen mit — so bleibt die Reihe in sich
    gültig (Schluss innerhalb Hoch/Tief) und das neue Niveau hat Bestand.
    Ein Sprung, der nur eine Kerze verschiebt, erzeugt sonst automatisch
    einen zweiten Sprung zurück und verfälscht den Test.
    """
    base = c[i - 1].c
    v = c[i].v if volume is None else volume
    if revert:                              # nur diese eine Kerze verschieben
        c[i] = _scale(c[i], factor, v)
        return c
    end = len(c) if persist else min(i + 3, len(c))
    for j in range(i, end):
        c[j] = _scale(c[j], factor, v if j == i else None)
    if not persist:                          # danach zurueck aufs alte Niveau
        for j in range(end, len(c)):
            c[j] = c[j]
    return c


def test_glattes_split_verhaeltnis_gilt_als_datenproblem():
    """Ein echter Split waere von der Datenquelle bereinigt worden — bleibt das
    glatte Verhaeltnis stehen, ist die Bereinigung fehlgeschlagen."""
    q = _assess(_jump(_series(300), 150, 2.0))
    assert any("Split-Verhältnis" in i for i in q.issues)


def test_rueckabgewickelter_sprung_ist_ein_ausreisser():
    """Eine einzelne verschobene Kerze, die am Folgetag wieder auf dem alten
    Niveau liegt — ein Ausreißer-Tick, kein Marktgeschehen."""
    q = _assess(_jump(_series(300), 150, 1.6, revert=True))
    assert any("zurückgenommen" in i for i in q.issues)


def test_sprung_ohne_umsatz_wird_erkannt():
    """LVO: 900 -> 300 USD bei Volumen 0 — es hat schlicht kein Handel
    stattgefunden, also gibt es auch keinen Kurs."""
    q = _assess(_jump(_series(300), 150, 0.333, volume=0.0))
    assert any("ohne Umsatz" in i for i in q.issues)


def test_echte_kursbewegung_wird_nicht_bestraft():
    """DER Kernpunkt: AACG stieg 1,36 -> 14,30 USD bei sehr hohem Volumen. So
    etwas ist eine Markttatsache, kein Datenfehler."""
    sauber = _assess(_series(300))
    # 1,62x ist bewusst KEIN glattes Split-Verhaeltnis, mit Volumenanstieg
    # und Bestand ueber die Folgetage.
    bewegt = _assess(_jump(_series(300), 150, 1.62, volume=5_000_000.0))
    assert bewegt.components["reihe"] == sauber.components["reihe"], (
        f"echte Bewegung kostete Reihenqualitaet: "
        f"{bewegt.components['reihe']} statt {sauber.components['reihe']}")
    assert bewegt.score >= sauber.score - 1


def test_grosse_bewegung_ohne_volumenbestaetigung_wiegt_leichter():
    """Unbestaetigt ist nicht dasselbe wie kaputt — die Strafe muss deutlich
    geringer ausfallen als bei einem echten Datenfehler."""
    unbestaetigt = _assess(_jump(_series(300), 150, 1.62, volume=1.0))
    kaputt = _assess(_jump(_series(300), 150, 2.0, volume=1.0))
    assert unbestaetigt.components["reihe"] > kaputt.components["reihe"]


def test_widerspruechliche_kerze_wird_erkannt():
    c = _series(300)
    c[100] = Candle(50.0, 40.0, 60.0, 55.0, 100_000.0)      # Hoch < Tief
    q = _assess(c)
    assert any("widersprüchlich" in i for i in q.issues)


def test_kaputte_reihe_wird_nicht_weggemittelt():
    """Der entscheidende Deckel: Bei halb unbrauchbarer Reihe ergab die reine
    Gewichtung noch 76/100, weil Historie, Aktualität und Indikatoren voll
    punkteten — obwohl genau diese Indikatoren darauf berechnet wurden."""
    c = _series(400)
    for i in range(0, 400, 2):                       # 50 % ohne Umsatz
        c[i] = Candle(c[i].o, c[i].h, c[i].l, c[i - 1].c if i else c[i].c, 0.0)
    for i in range(20, 400, 40):                     # viele Extremsprünge
        c[i] = Candle(c[i].o, c[i].h * 2, c[i].l, c[i].c * 2.0, c[i].v)
    q = _assess(c)
    assert q.components["reihe"] < 0.4
    assert q.score <= 65, f"kaputte Reihe erreicht noch {q.score}"
    assert q.label == QualityLabel.POOR


def test_zu_kurze_reihe_gibt_null():
    q = assess([Candle(1, 1, 1, 1, 1)], {}, {}, as_of=_iso(1))
    assert q.components["reihe"] == 0.0


# --------------------------------------------------------------------------- #
#  Serialisierung
# --------------------------------------------------------------------------- #
def test_dict_ist_vollstaendig_und_serialisierbar():
    import json
    d = _assess(_series(300)).to_dict()
    json.dumps(d)
    assert {"score", "label", "components", "issues", "bars", "age_days"} <= set(d)


# --------------------------------------------------------------------------- #
#  Kopplung an die Handlungsempfehlung
# --------------------------------------------------------------------------- #
def test_keine_kaufempfehlung_auf_duenner_datenlage():
    """Der schwerwiegendste Befund des Volllaufs: PLCI stand mit
    Datenqualität 31 und ohne eine einzige Fundamentalkennzahl auf
    STARK KAUFEN. Fehlt eine Komponente, rechnet compute_total_score mit der
    verbleibenden weiter — ein rein technischer Wert wurde so zu einem
    scheinbar vollwertigen Gesamtrating."""
    from infrastructure.database.repository import (MIN_QUALITY_FOR_RATING,
                                                    RATING_UNCLEAR, rating_label)
    assert rating_label(86, 31) == RATING_UNCLEAR
    assert rating_label(86, MIN_QUALITY_FOR_RATING - 1) == RATING_UNCLEAR
    # Auch eine Verkaufsempfehlung ist auf dieser Grundlage nicht zu vertreten.
    assert rating_label(20, 31) == RATING_UNCLEAR


def test_bei_belastbarer_datenlage_bleibt_alles_wie_bisher():
    from infrastructure.database.repository import (MIN_QUALITY_FOR_RATING,
                                                    rating_label)
    assert rating_label(86, MIN_QUALITY_FOR_RATING) == "STARK KAUFEN"
    assert rating_label(86, 95) == "STARK KAUFEN"
    assert rating_label(70, 90) == "KAUFEN"
    assert rating_label(20, 90) == "VERKAUFEN"


def test_ohne_angabe_zur_datenqualitaet_unveraendertes_verhalten():
    """Rückwärtskompatibel: Wer die Datenqualität nicht kennt, bekommt das
    bisherige Verhalten — sonst würden Altbestände schlagartig UNKLAR."""
    from infrastructure.database.repository import rating_label
    assert rating_label(86) == "STARK KAUFEN"
    assert rating_label(None) is None
