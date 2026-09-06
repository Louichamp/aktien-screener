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
    "technical_rating": {"trend": 0.25, "momentum": 0.2, "rel_strength": 0.15,
                         "market_leadership": 0.1, "volume": 0.1,
                         "institutional_demand": 0.05, "breakout": 0.08,
                         "setup": 0.07},
    "fundamental_rating": {"fund_quality": 1.0},
}
_COMPUTORS = [_Comp("trend", "Trend"), _Comp("momentum", "Momentum"),
              _Comp("rel_strength", "Relative Stärke"),
              _Comp("market_leadership", "Market Leadership"),
              _Comp("volume", "Volumen"),
              _Comp("institutional_demand", "Institutionelle Nachfrage"),
              _Comp("breakout", "Breakout"), _Comp("setup", "Setup"),
              _Comp("fund_quality", "Qualität")]


def _mk(**scores) -> _Scored:
    return _Scored({k: _Res(k, v) for k, v in scores.items()})


def _bd(**scores):
    return build_breakdown(_mk(**scores), _COMPOSITES, _COMPUTORS)


# --------------------------------------------------------------------------- #
#  Signalstärke — zählt UNABHÄNGIGE Gruppen, nicht einzelne Faktoren
# --------------------------------------------------------------------------- #
def test_korrelierte_faktoren_zaehlen_nur_einmal():
    """DER Kernpunkt. trend, momentum, rel_strength und market_leadership sind
    im Querschnitt zu 0,72–0,92 korreliert — sie messen dieselbe Aussage. Eine
    Aktie im Aufwärtstrend darf sich dadurch nicht dreifach selbst bestätigen.
    Die erste Fassung stufte genau diesen Fall als 'stark' ein."""
    b = _bd(trend=9.0, momentum=9.0, rel_strength=9.0, market_leadership=9.0)
    assert b.confirming == ["Trendstärke"]          # EINE Gruppe, nicht vier
    assert b.signal_strength == SignalStrength.NONE  # nur eine belegte Gruppe


def test_bestaetigung_aus_verschiedenen_gruppen_zaehlt():
    b = _bd(trend=8.0, momentum=8.0, volume=8.0, institutional_demand=7.0)
    assert set(b.confirming) == {"Trendstärke", "Volumen"}
    assert b.signal_strength == SignalStrength.MODERATE


def test_drei_gruppen_ohne_widerspruch_sind_stark():
    b = _bd(trend=8.0, momentum=8.0, volume=8.0, institutional_demand=7.5,
            breakout=7.5, setup=5.0)
    assert set(b.confirming) == {"Trendstärke", "Volumen", "Ausbruchslage"}
    assert b.signal_strength == SignalStrength.STRONG


def test_ein_widerspruch_verhindert_stark():
    b = _bd(trend=8.0, momentum=8.0, volume=8.0, institutional_demand=7.5,
            breakout=7.5, setup=2.0)
    assert "Einstiegslage" in b.contradicting
    assert b.signal_strength == SignalStrength.MODERATE


def test_einzelne_bedingung_ist_schwach():
    """Der klassische Fehlalarm: eine Gruppe spricht dafür, eine dagegen."""
    b = _bd(trend=3.0, momentum=3.0, breakout=8.0, setup=5.0)
    assert b.confirming == ["Ausbruchslage"]
    assert "Trendstärke" in b.contradicting
    assert b.signal_strength == SignalStrength.WEAK


def test_gruppenwert_ist_der_mittelwert_der_mitglieder():
    """Innerhalb einer Gruppe sind die Faktoren hoch korreliert; ihr Mittel ist
    die stabilere Schätzung derselben Aussage — zählt aber nur einmal."""
    b = _bd(trend=9.0, momentum=3.0, volume=8.0, institutional_demand=8.0)
    assert "Trendstärke" not in b.confirming      # Mittel 6,0 < Schwelle 6,5
    assert "Volumen" in b.confirming


def test_ohne_faktoren_kein_signal():
    assert _bd().signal_strength == SignalStrength.NONE


def test_eine_einzige_bekannte_gruppe_ergibt_kein_signal():
    """Aus einer Informationsquelle lässt sich keine Übereinstimmung ableiten —
    lieber 'kein Signal' als eine Stärke, die auf nichts beruht."""
    assert _bd(trend=9.5).signal_strength == SignalStrength.NONE


def test_schwelle_ist_inklusiv():
    b = _bd(trend=CONFIRM_AT, momentum=CONFIRM_AT, volume=CONFIRM_AT,
            institutional_demand=CONFIRM_AT)
    assert set(b.confirming) == {"Trendstärke", "Volumen"}


# --------------------------------------------------------------------------- #
#  Aufschlüsselung
# --------------------------------------------------------------------------- #
def test_beitraege_summieren_sich_zum_gesamtwert():
    """Die Anzeige 'Warum 87?' waere eine huebsche Luege, wenn die Beitraege
    nicht den ausgewiesenen Wert ergaeben."""
    scores = {"trend": 8.0, "momentum": 6.0, "rel_strength": 4.0,
              "market_leadership": 5.0, "volume": 2.0,
              "institutional_demand": 7.0, "breakout": 6.0, "setup": 3.0}
    b = _bd(**scores)
    w = _COMPOSITES["technical_rating"]
    erwartet = sum(scores[k] * w[k] for k in scores) / sum(w.values()) * 10
    assert abs(sum(c.contribution for c in b.technical) - erwartet) < 0.2


def test_fehlende_faktoren_werden_ausgewiesen_nicht_verschwiegen():
    """Ein Score auf halber Datenlage muss als solcher erkennbar sein."""
    sc = _Scored({"trend": _Res("trend", 8.0),
                  "momentum": _Res("momentum", 0.0, ok=False)})
    b = build_breakdown(sc, _COMPOSITES, _COMPUTORS)
    fehlend = [c for c in b.technical if not c.available]
    # Alles ausser `trend` fehlt — jeder dieser Faktoren muss ausgewiesen
    # werden, statt stillschweigend zu verschwinden.
    assert "momentum" in {c.slug for c in fehlend}
    assert "trend" not in {c.slug for c in fehlend}
    assert all(c.contribution == 0.0 for c in fehlend)
    assert b.coverage == _COMPOSITES["technical_rating"]["trend"] / sum(
        _COMPOSITES["technical_rating"].values())
    assert b.note is not None and "25" in b.note


def test_labels_kommen_aus_den_computors():
    b = _bd(trend=7.0, momentum=7.0)
    assert next(c.label for c in b.technical if c.slug == "rel_strength") == "Relative Stärke"


def test_dict_ist_serialisierbar():
    import json
    json.dumps(_bd(trend=7.0, momentum=7.0).to_dict())
