"""Handelbare Level, Konfluenzzonen und Eigenschaftstests (§33).

Geprueft werden die Zusagen, die der Handelsplan implizit macht:
  * Der Stopp liegt bei einem Long-Trade IMMER unter dem Einstieg.
  * Das Risiko ist auf `max_risk_pct` gedeckelt.
  * Das CRV entspricht (Ziel - Einstieg) / (Einstieg - Stopp).
  * Zonenstaerke waechst mit UNABHAENGIGEN Faktoren, nicht mit blosser Haeufung.
  * Mehr Daten duerfen einen Score nicht unlogisch verschlechtern.
"""
from __future__ import annotations

import pytest

from screener.levels import LevelEngine
from screener.zones import (Candle, ConfluenceZone, PriceLevel, ZoneCategory,
                            ZoneContext, ZoneEngine)


def _candles(n: int = 120, start: float = 100.0, drift: float = 0.1) -> list[Candle]:
    out = []
    p = start
    for i in range(n):
        p += drift
        out.append(Candle(o=p - 0.2, h=p + 0.8, l=p - 0.8, c=p, v=1_000_000.0,
                          ts=f"2026-01-{(i % 28) + 1:02d}"))
    return out


def _ctx(price: float = 112.0, atr: float = 1.5, **kw) -> ZoneContext:
    return ZoneContext(price=price, atr=atr, candles=_candles(),
                       trend=kw.pop("trend", "up"),
                       ema_50=kw.pop("ema_50", 108.0),
                       sma_200=kw.pop("sma_200", 104.0), **kw)


# --------------------------------------------------------------------------- #
#  Handelsplan — Eigenschaften, die immer gelten muessen
# --------------------------------------------------------------------------- #
def test_stopp_liegt_immer_unter_dem_einstieg():
    plan = LevelEngine().build_plan(_ctx())
    if plan.signal_aggr and plan.stop_loss:
        assert plan.stop_loss < plan.signal_aggr


@pytest.mark.parametrize("price,atr", [(112.0, 1.5), (95.0, 3.0), (150.0, 0.5),
                                       (101.0, 2.2), (130.0, 4.0)])
def test_stopp_unter_einstieg_ueber_viele_konstellationen(price: float, atr: float):
    plan = LevelEngine().build_plan(_ctx(price=price, atr=atr))
    if plan.signal_aggr and plan.stop_loss:
        assert plan.stop_loss < plan.signal_aggr, f"Preis {price}, ATR {atr}"


def test_risiko_ist_gedeckelt():
    """Ohne Deckel kann eine tiefe Zone ein absurdes Strukturrisiko erzeugen."""
    eng = LevelEngine(max_risk_pct=0.08)
    plan = eng.build_plan(_ctx(atr=12.0))          # sehr weite Zone
    if plan.signal_aggr and plan.stop_loss:
        risiko = (plan.signal_aggr - plan.stop_loss) / plan.signal_aggr
        assert risiko <= 0.08 + 1e-9


def test_crv_entspricht_seiner_definition():
    plan = LevelEngine().build_plan(_ctx())
    if plan.crv is not None and plan.signal_aggr and plan.stop_loss and plan.target_1:
        erwartet = ((plan.target_1 - plan.signal_aggr)
                    / (plan.signal_aggr - plan.stop_loss))
        assert plan.crv == pytest.approx(erwartet, abs=0.01)


def test_ohne_zonen_kein_erfundener_plan():
    leer = ZoneContext(price=100.0, atr=1.0, candles=[], trend="neutral")
    plan = LevelEngine().build_plan(leer)
    assert plan.signal_aggr is None and plan.stop_loss is None and plan.crv is None


def test_plan_traegt_seine_begruendung():
    """Eine Zahl ohne Begruendung ist im Tearsheet wertlos."""
    plan = LevelEngine().build_plan(_ctx())
    if plan.signal_aggr:
        assert plan.rationale and any("Konfluenz" in r for r in plan.rationale)


# --------------------------------------------------------------------------- #
#  Zonen-Clustering und Diversitaet
# --------------------------------------------------------------------------- #
def _lvl(price: float, kategorie: str, gewicht: float = 0.7) -> PriceLevel:
    return PriceLevel(price=price, source=f"q{kategorie}", category=kategorie,
                      weight=gewicht, label=kategorie, kind="support")


def test_nahe_level_werden_zu_einer_zone():
    eng = ZoneEngine()
    ctx = _ctx()
    zonen = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI),
                              _lvl(100.2, ZoneCategory.PRICE_LEVEL)])
    assert len(zonen) == 1


def test_weit_entfernte_level_bleiben_getrennt():
    eng = ZoneEngine()
    ctx = _ctx()
    zonen = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI),
                              _lvl(140.0, ZoneCategory.PRICE_LEVEL)])
    assert len(zonen) == 2


def test_unabhaengige_kategorien_schlagen_blosse_haeufung():
    """Der Kern der Konfluenz-Idee: drei verschiedene Methoden an derselben
    Stelle sind mehr wert als dreimal dieselbe Methode."""
    eng = ZoneEngine()
    ctx = _ctx()
    gleich = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI),
                               _lvl(100.1, ZoneCategory.FIBONACCI),
                               _lvl(100.2, ZoneCategory.FIBONACCI)])
    verschieden = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI),
                                    _lvl(100.1, ZoneCategory.VOLUME),
                                    _lvl(100.2, ZoneCategory.MOVING_AVERAGE)])
    assert verschieden[0].strength > gleich[0].strength


def test_zusaetzliche_gleichartige_faktoren_zaehlen_nur_teilweise():
    eng = ZoneEngine()
    ctx = _ctx()
    eins = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI)])[0].strength
    zwei = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI),
                             _lvl(100.1, ZoneCategory.FIBONACCI)])[0].strength
    assert zwei > eins
    assert zwei < 2 * eins, "abnehmender Grenznutzen fehlt"


def test_zonenstaerke_bleibt_im_wertebereich():
    eng = ZoneEngine()
    ctx = _ctx()
    viele = [_lvl(100.0 + i * 0.01, kat, 1.0)
             for i, kat in enumerate([ZoneCategory.FIBONACCI, ZoneCategory.VOLUME,
                                      ZoneCategory.TREND, ZoneCategory.STRUCTURE,
                                      ZoneCategory.PRICE_LEVEL,
                                      ZoneCategory.MOVING_AVERAGE,
                                      ZoneCategory.DERIVATIVE] * 3)]
    z = eng.cluster(ctx, viele)[0]
    assert 0.0 <= z.strength <= 10.0


def test_zone_kennt_ihre_art():
    eng = ZoneEngine()
    ctx = _ctx(price=112.0)
    unten = eng.cluster(ctx, [_lvl(100.0, ZoneCategory.FIBONACCI)])[0]
    oben = eng.cluster(ctx, [_lvl(130.0, ZoneCategory.FIBONACCI)])[0]
    assert unten.kind == "support" and oben.kind == "resistance"


def test_zone_erklaert_sich_selbst():
    eng = ZoneEngine()
    z = eng.cluster(_ctx(), [_lvl(100.0, ZoneCategory.FIBONACCI),
                             _lvl(100.1, ZoneCategory.VOLUME)])[0]
    assert z.explain() and "+" in z.explain()


# --------------------------------------------------------------------------- #
#  Eigenschaftstest: mehr Daten duerfen nicht unlogisch schaden
# --------------------------------------------------------------------------- #
def test_mehr_historie_kippt_den_plan_nicht():
    """Eine laengere, gleichfoermige Historie darf den Plan nicht umwerfen."""
    kurz = ZoneContext(price=112.0, atr=1.5, candles=_candles(60), trend="up",
                       ema_50=108.0, sma_200=104.0)
    lang = ZoneContext(price=112.0, atr=1.5, candles=_candles(240), trend="up",
                       ema_50=108.0, sma_200=104.0)
    a = LevelEngine().build_plan(kurz)
    b = LevelEngine().build_plan(lang)
    if a.stop_loss and b.stop_loss and a.signal_aggr and b.signal_aggr:
        assert b.stop_loss < b.signal_aggr
        assert abs(b.signal_aggr - a.signal_aggr) / a.signal_aggr < 0.5
