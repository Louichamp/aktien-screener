"""Tests für die Wochen-Watchlist.

Der Schwerpunkt liegt auf den Fehlern, die im ersten Lauf gegen echte Daten
sichtbar wurden — eine Watchlist mit untauglichen Kandidaten kostet mehr
Zeit, als sie spart.
"""
from __future__ import annotations

from screener.watchlist import (MIN_DATA_QUALITY, P1_MAX_DIST_PCT,
                                build_market_overview, build_watchlist,
                                rank_sectors)


def _row(ticker, **kw):
    """Ein Titel, der die Grundfilter besteht — Abweichungen per kw."""
    base = {
        "ticker": ticker, "name": f"{ticker} Inc.", "sector": "Technology",
        "price": 100.0, "currency": "USD", "status": "Ausbruch vorbereitet",
        "rating": "KAUFEN", "total_score": 75, "trend_long": "AUFWÄRTS",
        "signal_strength": "moderat", "data_quality": 90,
        "drivers": {"base": {"dist_to_pivot_pct": 2.0, "pivot": 102.0,
                             "buy_zone_low": 102.0, "buy_zone_high": 103.0,
                             "stop": 94.0, "risk_pct": 0.08, "state": "Pivot in Reichweite"},
                    "breakout": {"segment": "mittel (5–20 Mio $)"}},
    }
    base.update(kw)
    return base


def _viele(n=12, **kw):
    return [_row(f"T{i:02d}", **kw) for i in range(n)]


# --------------------------------------------------------------------------- #
#  Grundfilter
# --------------------------------------------------------------------------- #
def test_titel_auf_vermeiden_kommen_nicht_auf_die_liste():
    """Ein Titel, den die eigene Zustandsmaschine auf 'Vermeiden' setzt, darf
    nicht über einen anderen Weg wieder auf eine Empfehlungsliste geraten.
    Im ersten Lauf standen so zwei Vorzugsklassen auf Priorität 1."""
    w = build_watchlist(_viele(12) + [_row("BAD", status="Vermeiden", total_score=99)])
    assert "BAD" not in {c.ticker for c in w.candidates}


def test_illiquide_titel_werden_ausgeschlossen():
    """Dort bewegt die eigene Order den Kurs — und die Datenqualität ist
    typischerweise schlecht."""
    w = build_watchlist(_viele(12) + [
        _row("ILL", total_score=99,
             drivers={"base": {"dist_to_pivot_pct": 0.5},
                      "breakout": {"segment": "illiquide"}})])
    assert "ILL" not in {c.ticker for c in w.candidates}


def test_duenne_datenlage_wird_ausgeschlossen():
    w = build_watchlist(_viele(12) + [
        _row("THIN", data_quality=MIN_DATA_QUALITY - 1, total_score=99)])
    assert "THIN" not in {c.ticker for c in w.candidates}


def test_unklares_rating_wird_ausgeschlossen():
    w = build_watchlist(_viele(12) + [_row("UNK", rating="UNKLAR", total_score=99)])
    assert "UNK" not in {c.ticker for c in w.candidates}


def test_schwaches_signal_wird_ausgeschlossen():
    w = build_watchlist(_viele(12) + [
        _row("WEAK", signal_strength="schwach", total_score=99),
        _row("NONE", signal_strength="kein Signal", total_score=99)])
    tickers = {c.ticker for c in w.candidates}
    assert "WEAK" not in tickers and "NONE" not in tickers


# --------------------------------------------------------------------------- #
#  Priorisierung
# --------------------------------------------------------------------------- #
def test_naher_ausloeser_ist_prioritaet_1():
    w = build_watchlist([_row("NAH", drivers={
        "base": {"dist_to_pivot_pct": 1.0, "pivot": 101.0, "risk_pct": 0.07},
        "breakout": {"segment": "mittel (5–20 Mio $)"}})] + _viele(11))
    c = next(c for c in w.candidates if c.ticker == "NAH")
    assert c.priority == 1
    assert "1.0" in c.reason


def test_ausbruch_vorbereitet_ohne_naehe_ist_nicht_prioritaet_1():
    """Blackstone stand mit 9,4 % Abstand in der Stufe 'kurz vor dem
    Einstieg' — der Status allein reicht dafür nicht."""
    w = build_watchlist([_row("FERN", status="Ausbruch vorbereitet", drivers={
        "base": {"dist_to_pivot_pct": 9.4, "pivot": 110.0, "risk_pct": 0.07},
        "breakout": {"segment": "mittel (5–20 Mio $)"}})] + _viele(11))
    c = next(c for c in w.candidates if c.ticker == "FERN")
    assert c.priority == 2


def test_hohes_strukturrisiko_verhindert_prioritaet_1():
    w = build_watchlist([_row("RISK", drivers={
        "base": {"dist_to_pivot_pct": 1.0, "pivot": 101.0, "risk_pct": 0.30},
        "breakout": {"segment": "mittel (5–20 Mio $)"}})] + _viele(11))
    c = next((c for c in w.candidates if c.ticker == "RISK"), None)
    assert c is None or c.priority > 1


def test_prioritaetsgrenze_ist_inklusiv():
    w = build_watchlist([_row("GRENZ", drivers={
        "base": {"dist_to_pivot_pct": P1_MAX_DIST_PCT, "pivot": 103.0, "risk_pct": 0.05},
        "breakout": {"segment": "mittel (5–20 Mio $)"}})] + _viele(11))
    assert next(c for c in w.candidates if c.ticker == "GRENZ").priority == 1


# --------------------------------------------------------------------------- #
#  Dubletten
# --------------------------------------------------------------------------- #
def test_anteilsklassen_belegen_nur_einen_platz():
    """ADAMN und ADAMM sind beide 'Adamas Trust, Inc.' und belegten im ersten
    Lauf zwei Plätze mit derselben Aussage."""
    rows = _viele(10) + [
        _row("ADAMN", name="Adamas Trust, Inc.", total_score=80),
        _row("ADAMM", name="Adamas Trust, Inc.", total_score=78)]
    w = build_watchlist(rows)
    adamas = [c for c in w.candidates if c.name == "Adamas Trust, Inc."]
    assert len(adamas) == 1
    assert adamas[0].ticker == "ADAMN", "der bestbewertete Vertreter bleibt"


# --------------------------------------------------------------------------- #
#  Markt und Sektoren
# --------------------------------------------------------------------------- #
def test_marktueberblick_erkennt_breite():
    freundlich = build_market_overview(_viele(10))
    assert freundlich.breadth_verdict == "freundlich"
    defensiv = build_market_overview(_viele(10, trend_long="ABWÄRTS"))
    assert defensiv.breadth_verdict == "defensiv"


def test_leerer_markt_stuerzt_nicht_ab():
    m = build_market_overview([])
    assert m.n_total == 0 and m.breadth_verdict == "unbekannt"


def test_kleine_sektoren_werden_nicht_bewertet():
    """Aus drei Titeln lässt sich kein Sektorurteil ableiten."""
    rows = _viele(10) + [_row("X1", sector="Energy"), _row("X2", sector="Energy")]
    sektoren = {s.sector for s in rank_sectors(rows)}
    assert "Energie" not in sektoren
    assert "Informationstechnologie" in sektoren


def test_gics_namen_werden_zusammengefasst():
    """'Financials' und 'Financial Services' sind derselbe Sektor — beide
    Schreibweisen kommen in den Rohdaten vor."""
    rows = ([_row(f"F{i}", sector="Financial Services") for i in range(4)]
            + [_row(f"G{i}", sector="Financials") for i in range(4)])
    sektoren = rank_sectors(rows)
    assert [s.sector for s in sektoren] == ["Finanzwesen"]
    assert sektoren[0].n == 8


def test_watchlist_ist_serialisierbar():
    import json
    json.dumps(build_watchlist(_viele(12)).to_dict())


def test_leeres_universum_ergibt_leere_liste():
    w = build_watchlist([])
    assert w.candidates == [] and w.universe_size == 0
