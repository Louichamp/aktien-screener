"""Tests fuer die Bewertungs-Normalisierung.

Hintergrund: Die Invertierung „kleiner Multiplikator = guenstiger" drehte
nicht-positive Multiplikatoren an die SPITZE der Rangliste. Gemessen im
Produktions-Querschnitt vom 2026-09-06: 14,5 % der EV/EBITDA- und 9,3 % der
P/B-Werte waren negativ und erhielten im Mittel Perzentil 0,70 bzw. 0,77
(positive Werte: 0,46). Ein Titel mit EV/EBITDA -447 galt als „billigster der
Branche".
"""
from __future__ import annotations

from scoring import InstrumentData, ScoreEngine, ScoringContext
from scoring.computors.valuation import ValuationComputor, _positive_multiple


def _inst(tk: str, **fundamentals) -> InstrumentData:
    return InstrumentData(instrument_id=tk, ticker=tk, asset_class="Aktie",
                          sector="Technology", industry="Software",
                          market_cap=1e9, technicals={"close": 100.0},
                          fundamentals=fundamentals)


def _score(target: InstrumentData, peers: list[InstrumentData]):
    ctx = ScoringContext([target] + peers, min_peers=8)
    return ValuationComputor().compute(target, ctx)


def _peer_group(n: int = 12, start: float = 10.0) -> list[InstrumentData]:
    """Gesunde Peers mit aufsteigendem (also zunehmend teurerem) KGV."""
    return [_inst(f"P{i}", pe=start + i, ev_ebitda=start + i, p_b=1.0 + i * 0.1)
            for i in range(n)]


# --------------------------------------------------------------------------- #
#  Der eigentliche Fix
# --------------------------------------------------------------------------- #
def test_negatives_kgv_gilt_nicht_als_guenstig():
    """Ein Verlustunternehmen darf nicht als billigster Titel gelten."""
    verlust = _inst("VERLUST", pe=-50.0)
    res = _score(verlust, _peer_group())
    # pe ist der einzige Multiplikator -> keine verwertbare Bewertung
    assert res.raw.get("missing") or not res.ok, \
        "negatives KGV darf keinen Bewertungsscore erzeugen"


def test_negatives_ev_ebitda_wird_ignoriert_andere_zaehlen_weiter():
    """Ein unbrauchbarer Multiplikator kippt nicht die ganze Bewertung."""
    titel = _inst("MIX", pe=12.0, ev_ebitda=-30.0)
    res = _score(titel, _peer_group())
    assert res.ok and not res.raw.get("missing")
    assert res.raw["multiples_used"] == 1, "nur das gueltige KGV darf zaehlen"


def test_negativer_buchwert_erzeugt_keinen_bonus():
    """Negatives Eigenkapital (z. B. nach Rueckkaeufen) ist kein Schnaeppchen."""
    guenstig = _inst("GUENSTIG", p_b=0.5)
    negativ = _inst("NEGATIV", p_b=-24.8)
    peers = _peer_group()
    s_guenstig = _score(guenstig, peers)
    s_negativ = _score(negativ, peers)
    assert s_guenstig.ok and not s_guenstig.raw.get("missing")
    assert s_negativ.raw.get("missing") or not s_negativ.ok


def test_hinweis_driver_bei_unbrauchbarem_multiplikator():
    """Der Ausschluss wird sichtbar gemacht, nicht stillschweigend vollzogen."""
    titel = _inst("MIX", pe=12.0, ev_ebitda=-30.0)
    res = _score(titel, _peer_group())
    codes = [d.code for d in res.drivers]
    assert "multiple_undefined" in codes


def test_negative_peers_verschieben_die_raenge_nicht():
    """Nicht-positive Werte muessen auch aus der PEER-Verteilung fallen —
    sonst verschieben sie die Raenge der gueltigen Titel."""
    peers_sauber = _peer_group()
    peers_mit_muell = peers_sauber + [
        _inst(f"N{i}", pe=-100.0 - i) for i in range(6)]
    titel = _inst("T", pe=15.0)
    a = _score(titel, peers_sauber)
    b = _score(titel, peers_mit_muell)
    assert abs(a.score - b.score) < 1e-9, \
        "negative Peers duerfen das Perzentil eines gueltigen Titels nicht aendern"


# --------------------------------------------------------------------------- #
#  Unveraendertes Verhalten bei gesunden Daten
# --------------------------------------------------------------------------- #
def test_guenstiger_titel_schlaegt_teuren():
    peers = _peer_group()
    billig = _score(_inst("BILLIG", pe=5.0), peers)
    teuer = _score(_inst("TEUER", pe=40.0), peers)
    assert billig.score > teuer.score


def test_extremer_ausreisser_kippt_nichts():
    """Rangbasiert: ein KGV von 4000 belegt denselben letzten Platz wie 400 —
    Winsorizing ist hier nicht noetig."""
    peers = _peer_group()
    a = _score(_inst("A", pe=400.0), peers)
    b = _score(_inst("B", pe=4000.0), peers)
    assert abs(a.score - b.score) < 1e-9


def test_hilfsfunktion_positive_multiple():
    d = _inst("X", pe=10.0, ev_ebitda=0.0, p_b=-1.0)
    assert _positive_multiple(d, "pe") == 10.0
    assert _positive_multiple(d, "ev_ebitda") is None      # 0 ist ebenfalls undefiniert
    assert _positive_multiple(d, "p_b") is None
    assert _positive_multiple(d, "p_fcf") is None          # gar nicht vorhanden


def test_engine_bleibt_lauffaehig_ohne_bewertungsdaten():
    """Fehlt die Bewertung komplett, renormiert das Composite — kein Absturz."""
    inst = _inst("OHNE", roic=0.2, net_margin=0.1)
    ctx = ScoringContext([inst], min_peers=8)
    scored = ScoreEngine().score_instrument(inst, ctx)
    assert scored.results["valuation"].raw.get("missing")
