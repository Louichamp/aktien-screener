"""Tests für die Score-Aufschlüsselung und die Signalstärke.

Der Kern: Ein Treffer, der nur auf EINER Bedingung beruht, darf nicht wie ein
Treffer aussehen, den vier unabhängige Faktoren stützen. Genau das war vorher
nicht unterscheidbar — gespeichert wurden nur die verdichteten Kennzahlen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from screener.explain import (CONFIRM_AT, SignalStrength, build_breakdown)


@dataclass
class _Res:
    slug: str
    score: float
    ok: bool = True
    state: str | None = None


@dataclass
class _Scored:
    results: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Comp:
    slug: str
    label: str


_COMPOSITES = {
    "technical_rating": {"trend": 0.4, "momentum": 0.3, "rel_strength": 0.2, "volume": 0.1},
    "fundamental_rating": {"fund_quality": 1.0},
}
_COMPUTORS = [_Comp("trend", "Trend"), _Comp("momentum", "Momentum"),
              _Comp("rel_strength", "Relative Stärke"), _Comp("volume", "Volumen"),
              _Comp("fund_quality", "Qualität")]


def _mk(**scores) -> _Scored:
    return _Scored({k: _Res(k, v) for k, v in scores.items()})


def _bd(**scores):
    return build_breakdown(_mk(**scores), _COMPOSITES, _COMPUTORS)


# --------------------------------------------------------------------------- #
#  Signalstärke
# --------------------------------------------------------------------------- #
def test_alle_vier_faktoren_bestaetigen_ist_stark():
    b = _bd(trend=8.0, momentum=7.5, rel_strength=7.0, volume=7.0)
    assert b.signal_strength == SignalStrength.STRONG
    assert set(b.confirming) == {"trend", "momentum", "rel_strength", "volume"}


def test_einzelne_bedingung_ist_schwach():
    """Der klassische Fehlalarm: RSI überverkauft, sonst spricht nichts dafür."""
    b = _bd(trend=3.0, momentum=3.5, rel_strength=8.0, volume=4.0)
    assert b.signal_strength == SignalStrength.WEAK
    assert b.confirming == ["rel_strength"]
    assert "trend" in b.contradicting


def test_zwei_faktoren_sind_moderat():
    b = _bd(trend=7.0, momentum=7.0, rel_strength=5.0, volume=5.0)
    assert b.signal_strength == SignalStrength.MODERATE


def test_widerspruch_druckt_von_stark_auf_moderat():
    b = _bd(trend=8.0, momentum=8.0, rel_strength=8.0, volume=2.0)
    assert b.signal_strength == SignalStrength.MODERATE


def test_ohne_faktoren_kein_signal():
    assert _bd().signal_strength == SignalStrength.NONE


def test_eine_einzige_bekannte_dimension_ergibt_kein_signal():
    """Aus einem verfügbaren Faktor lässt sich keine Übereinstimmung ableiten —
    lieber 'kein Signal' als eine Stärke, die auf nichts beruht."""
    b = _bd(trend=9.5)
    assert b.signal_strength == SignalStrength.NONE


def test_schwelle_ist_inklusiv():
    b = _bd(trend=CONFIRM_AT, momentum=CONFIRM_AT, rel_strength=5.0, volume=5.0)
    assert "trend" in b.confirming and "momentum" in b.confirming


# --------------------------------------------------------------------------- #
#  Aufschlüsselung
# --------------------------------------------------------------------------- #
def test_beitraege_summieren_sich_zum_gesamtwert():
    b = _bd(trend=8.0, momentum=6.0, rel_strength=4.0, volume=2.0)
    erwartet = (8.0 * .4 + 6.0 * .3 + 4.0 * .2 + 2.0 * .1) * 10
    assert abs(sum(c.contribution for c in b.technical) - erwartet) < 0.2


def test_fehlende_faktoren_werden_ausgewiesen_nicht_verschwiegen():
    """Ein Score auf halber Datenlage muss als solcher erkennbar sein."""
    sc = _Scored({"trend": _Res("trend", 8.0),
                  "momentum": _Res("momentum", 0.0, ok=False)})
    b = build_breakdown(sc, _COMPOSITES, _COMPUTORS)
    fehlend = [c for c in b.technical if not c.available]
    assert {c.slug for c in fehlend} == {"momentum", "rel_strength", "volume"}
    assert all(c.contribution == 0.0 for c in fehlend)
    assert b.coverage == 0.4
    assert b.note is not None and "40" in b.note


def test_labels_kommen_aus_den_computors():
    b = _bd(trend=7.0, momentum=7.0)
    assert next(c.label for c in b.technical if c.slug == "rel_strength") == "Relative Stärke"


def test_dict_ist_serialisierbar():
    import json
    json.dumps(_bd(trend=7.0, momentum=7.0).to_dict())
