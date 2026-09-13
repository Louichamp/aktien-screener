"""Peer-Perzentile und Empirical-Bayes-Shrinkage.

Die Shrinkage-Formel

    shrunk = 0.5 + (percentile - 0.5) * n / (n + k)      mit k = 12

zieht Perzentile aus duennen Peer-Gruppen zur neutralen Mitte. Ohne sie
erzeugt „Platz 1 von 3" denselben Extremwert wie „Platz 1 von 300".

Sensitivitaet von k (analytisch, Dokumentation zu §12): Anteil des Roh-Abstands
zur Mitte, der erhalten bleibt — n/(n+k):

    n      k=6     k=12    k=24
    3     0,33     0,20    0,11
    5     0,45     0,29    0,17
    8     0,57     0,40    0,25
   10     0,63     0,45    0,29
   20     0,77     0,63    0,45
   50     0,89     0,81    0,68
  100     0,94     0,89    0,81

k = 12 ist auf `min_peers = 8` abgestimmt: Genau an der Schwelle, ab der eine
Peer-Gruppe ueberhaupt verwendet wird, bleiben 40 % des Abstands erhalten —
die Gruppe wirkt, dominiert aber nicht. Bei den in Produktion typischen
Branchengroessen (>= 50) sind es ueber 80 %, die Daempfung verschwindet also
dort, wo sie nicht mehr gebraucht wird. Das ist eine nachvollziehbare
Abstimmung, kein zufaellig stehengebliebener Parameter.
"""
from __future__ import annotations

import pytest

from scoring import InstrumentData, ScoringContext


def _inst(tk: str, value: float, *, industry: str = "Software",
          sector: str = "Technology") -> InstrumentData:
    return InstrumentData(instrument_id=tk, ticker=tk, asset_class="Aktie",
                          sector=sector, industry=industry,
                          technicals={"x": value}, fundamentals={})


def _ctx(values: list[float], **kw) -> tuple[ScoringContext, list[InstrumentData]]:
    insts = [_inst(f"T{i}", v, **kw) for i, v in enumerate(values)]
    return ScoringContext(insts, min_peers=8), insts


def _pct(ctx, inst) -> float:
    return ctx.percentile(inst, lambda d: d.metric("x"), scope="industry").percentile


# --------------------------------------------------------------------------- #
#  Grundverhalten
# --------------------------------------------------------------------------- #
def test_hoechster_wert_bekommt_hoechstes_perzentil():
    ctx, insts = _ctx([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
    assert _pct(ctx, insts[-1]) > _pct(ctx, insts[0])


def test_invert_dreht_die_richtung():
    ctx, insts = _ctx(list(range(1, 21)))
    normal = ctx.percentile(insts[-1], lambda d: d.metric("x"), scope="industry")
    gedreht = ctx.percentile(insts[-1], lambda d: d.metric("x"), scope="industry",
                             invert=True)
    assert normal.percentile > 0.5 > gedreht.percentile
    assert normal.percentile + gedreht.percentile == pytest.approx(1.0)


def test_fehlender_eigenwert_liefert_none():
    ctx, insts = _ctx(list(range(1, 21)))
    ohne = InstrumentData(instrument_id="X", ticker="X", asset_class="Aktie",
                          sector="Technology", industry="Software",
                          technicals={}, fundamentals={})
    assert ctx.percentile(ohne, lambda d: d.metric("x"), scope="industry").percentile is None


def test_gleichstaende_bekommen_mittelrang():
    """Sonst haengt das Ergebnis von der Eingabereihenfolge ab."""
    ctx, insts = _ctx([5.0] * 20)
    werte = {round(_pct(ctx, i), 6) for i in insts}
    assert len(werte) == 1, "alle gleichen Werte muessen dasselbe Perzentil bekommen"
    assert werte.pop() == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
#  Shrinkage (§12)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n", [3, 5, 8, 10, 20, 50])
def test_shrinkage_waechst_mit_der_gruppengroesse(n: int):
    """Je groesser die Gruppe, desto naeher liegt das Ergebnis am Rohwert."""
    ctx, insts = _ctx([float(i) for i in range(n)])
    spitze = _pct(ctx, insts[-1])
    roh = 1.0 - 0.5 / n                      # Mid-Rank des groessten Werts
    erhalten = (spitze - 0.5) / (roh - 0.5)
    assert erhalten == pytest.approx(n / (n + 12.0), abs=1e-6)


def test_duenne_gruppe_wird_stark_gedaempft():
    """Platz 1 von 3 darf nicht wie Platz 1 von 300 aussehen."""
    klein_ctx, klein = _ctx([1.0, 2.0, 3.0])
    gross_ctx, gross = _ctx([float(i) for i in range(100)])
    assert _pct(klein_ctx, klein[-1]) < _pct(gross_ctx, gross[-1])


def test_shrinkage_ist_symmetrisch_um_die_mitte():
    ctx, insts = _ctx([float(i) for i in range(21)])
    oben = _pct(ctx, insts[-1]) - 0.5
    unten = 0.5 - _pct(ctx, insts[0])
    assert oben == pytest.approx(unten, abs=1e-9)


def test_shrinkage_verlaesst_nie_den_gueltigen_bereich():
    for n in (2, 3, 8, 50, 200):
        ctx, insts = _ctx([float(i) for i in range(n)])
        for i in insts:
            p = _pct(ctx, i)
            assert 0.0 <= p <= 1.0


# --------------------------------------------------------------------------- #
#  Peer-Gruppen-Rueckfall
# --------------------------------------------------------------------------- #
def test_duenne_branche_faellt_auf_sektor_zurueck():
    """Unter min_peers=8 darf nicht gegen eine Zufallsgruppe verglichen werden."""
    insts = ([_inst(f"A{i}", float(i), industry="Nische") for i in range(3)]
             + [_inst(f"B{i}", float(i), industry="Gross") for i in range(20)])
    ctx = ScoringContext(insts, min_peers=8)
    ps = ctx.percentile(insts[0], lambda d: d.metric("x"), scope="industry")
    assert ps.scope == "sector", "zu duenne Branche muss auf den Sektor ausweichen"


def test_ohne_sektor_faellt_auf_universum_zurueck():
    insts = [InstrumentData(instrument_id=f"T{i}", ticker=f"T{i}",
                            asset_class="Aktie", sector=None, industry=None,
                            technicals={"x": float(i)}, fundamentals={})
             for i in range(20)]
    ctx = ScoringContext(insts, min_peers=8)
    ps = ctx.percentile(insts[0], lambda d: d.metric("x"), scope="industry")
    assert ps.scope == "universe"


def test_der_verwendete_bereich_wird_immer_mitgeliefert():
    """Transparenz: ein Perzentil ohne Angabe der Vergleichsgruppe ist wertlos."""
    ctx, insts = _ctx([float(i) for i in range(20)])
    ps = ctx.percentile(insts[0], lambda d: d.metric("x"), scope="industry")
    assert ps.scope in ("industry", "sector", "universe") and ps.n > 0
