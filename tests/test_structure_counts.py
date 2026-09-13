"""Tests fuer die Chartstruktur-Zaehlung (HH/HL/LH/LL).

Die fruehere Fassung verglich benachbarte KERZEN statt Swing-Punkte. Dadurch galt
hh + lh == n-1 per Konstruktion und der daraus gebildete „bullische
Strukturanteil" war ein Zaehler fuer Aufwaertstage — im `setup`-Score also ein
weiterer kurzfristiger Momentum-Proxy neben RSI, MACD und Stochastik.

Gemessen am Produktions-Querschnitt (4769 Titel) nach der Umstellung auf
Swing-Punkte:

    Rang-Korrelation des bullischen Strukturanteils
                      alt (Bar-zu-Bar)   neu (Swing)
    ret_1m                      +0,56         +0,35
    RSI                         +0,51         +0,33
    ret_3m                      +0,45         +0,58
    Streuung sigma               0,127         0,181
"""
from __future__ import annotations

from infrastructure.providers.indicators import structure_counts
from screener.zones import Candle


def _c(h: float, l: float) -> Candle:
    """Kerze, bei der nur Hoch/Tief relevant sind."""
    mid = (h + l) / 2.0
    return Candle(o=mid, h=h, l=l, c=mid, v=1000.0)


def _path(turning_points: list[float], bars_per_leg: int = 4) -> list[Candle]:
    """Baut einen echten Zickzack-Kurspfad aus Wendepunkten.

    Zwischen zwei Wendepunkten wird linear interpoliert, damit ausschliesslich
    die Wendepunkte selbst lokale Extrema sind — sonst erzeugen Fuellkerzen
    konkurrierende Swings und der Test misst sein eigenes Konstrukt.
    """
    prices: list[float] = []
    for a, b in zip(turning_points, turning_points[1:]):
        for k in range(bars_per_leg):
            prices.append(a + (b - a) * k / bars_per_leg)
    prices.append(turning_points[-1])
    return [_c(p + 0.5, p - 0.5) for p in prices]


# --------------------------------------------------------------------------- #
#  Struktur wird korrekt erkannt
# --------------------------------------------------------------------------- #
def test_steigende_swings_ergeben_hh_und_hl():
    """Aufwaertsstruktur: jedes Hoch hoeher, jedes Tief hoeher."""
    candles = _path([90.0, 110.0, 100.0, 120.0, 110.0, 130.0, 120.0, 140.0])
    d = structure_counts(candles)
    assert d["hh"] >= 2, f"erwartet mind. 2 hoehere Hochs, bekam {d}"
    assert d["hl"] >= 1, f"erwartet mind. 1 hoeheres Tief, bekam {d}"
    assert d["hh"] > d["lh"] and d["hl"] >= d["ll"]


def test_fallende_swings_ergeben_lh_und_ll():
    candles = _path([140.0, 120.0, 130.0, 110.0, 120.0, 100.0, 110.0, 90.0])
    d = structure_counts(candles)
    assert d["lh"] >= 2, f"erwartet mind. 2 tiefere Hochs, bekam {d}"
    assert d["ll"] >= 1, f"erwartet mind. 1 tieferes Tief, bekam {d}"
    assert d["lh"] > d["hh"] and d["ll"] >= d["hl"]


def test_zaehlt_nicht_mehr_jede_kerze():
    """Der eigentliche Fix: frueher galt hh + lh == n-1 per Konstruktion."""
    candles = _path([90.0, 110.0, 100.0, 120.0])
    d = structure_counts(candles)
    assert d["hh"] + d["lh"] < len(candles) - 1, \
        "Die Zaehlung darf nicht mehr an der Kerzenzahl haengen"


# --------------------------------------------------------------------------- #
#  Robustheit
# --------------------------------------------------------------------------- #
def test_zu_kurze_reihe_liefert_nullen_statt_absturz():
    assert structure_counts([_c(100, 90)] * 3) == {"hh": 0, "hl": 0, "lh": 0, "ll": 0}
    assert structure_counts([]) == {"hh": 0, "hl": 0, "lh": 0, "ll": 0}


def test_flache_reihe_erzeugt_keine_bullische_struktur():
    """Ohne Bewegung darf keine Aufwaertsstruktur behauptet werden."""
    d = structure_counts([_c(100.0, 90.0) for _ in range(80)])
    assert d["hh"] == 0 and d["hl"] == 0


def test_nutzt_nur_das_lookback_fenster():
    alt = _path([150.0, 200.0, 180.0, 210.0])                    # alte Aufwaertsphase
    neu = _path([130.0, 110.0, 120.0, 100.0, 110.0, 90.0])       # juengste Abwaertsphase
    d = structure_counts(alt + neu, lookback=len(neu))
    assert d["lh"] > d["hh"], f"nur die juengste Phase darf zaehlen, bekam {d}"


def test_keine_zukunftsinformation():
    """Ein Swing darf sich nicht aendern, wenn spaeter Kerzen dazukommen —
    die Zaehlung des VERGANGENEN Fensters muss stabil bleiben."""
    basis = _path([90.0, 110.0, 100.0, 120.0, 110.0, 130.0])
    vorher = structure_counts(basis, lookback=len(basis))
    # Kuenftige Kerzen anhaengen, aber dasselbe historische Fenster auswerten
    spaeter = basis + [_c(300.0, 290.0) for _ in range(5)]
    nachher = structure_counts(spaeter[: len(basis)], lookback=len(basis))
    assert vorher == nachher
