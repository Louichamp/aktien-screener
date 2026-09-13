"""Tests fuer das Liquiditaetsmass (Median-Tagesumsatz).

Vorher existierten zwei unterschiedliche Liquiditaetsbegriffe im System:

  screener/status.py       avg_dollar_volume = Yahoo-Durchschnittsvolumen
                           x HEUTIGER Kurs  -> entscheidet ueber Status
                           „Vermeiden" (< 2 Mio $)
  screener/breakout_signal.py  statistics.median(c.c * c.v) ueber 60 Bars

Der Durchschnitt ist bei rechtsschiefen Umsatzverteilungen genau dort
unbrauchbar, wo der Filter greifen soll: Ein einzelner Nachrichtentag hebt
einen sonst illiquiden Titel ueber die Schwelle.
"""
from __future__ import annotations

from infrastructure.providers.indicators import median_dollar_volume
from screener.zones import Candle


def _c(close: float, vol: float) -> Candle:
    return Candle(o=close, h=close * 1.01, l=close * 0.99, c=close, v=vol)


def test_einzelner_umsatz_spike_hebt_den_median_nicht():
    """Der eigentliche Fix: ein Ausreisser darf einen illiquiden Titel nicht
    ueber die 2-Mio-Schwelle heben."""
    ruhig = [_c(10.0, 50_000) for _ in range(59)]      # 500 Tsd $/Tag
    spike = [_c(10.0, 30_000_000)]                     # 300 Mio $ an einem Tag
    candles = ruhig + spike

    median = median_dollar_volume(candles)
    schnitt = sum(c.c * c.v for c in candles) / len(candles)

    assert median == 500_000.0
    assert schnitt > 5_000_000.0, "der Durchschnitt kippt tatsaechlich"
    assert median < 2_000_000.0 < schnitt, \
        "Median haelt den Titel korrekt unter der Liquiditaetsschwelle"


def test_liquider_titel_bleibt_liquide():
    candles = [_c(100.0, 500_000) for _ in range(60)]   # 50 Mio $/Tag
    assert median_dollar_volume(candles) == 50_000_000.0


def test_nutzt_nur_die_letzten_period_bars():
    alt = [_c(100.0, 1_000_000) for _ in range(100)]    # frueher sehr liquide
    neu = [_c(10.0, 10_000) for _ in range(60)]         # heute illiquide
    assert median_dollar_volume(alt + neu, period=60) == 100_000.0


def test_kurze_reihe_wird_verwendet_statt_verworfen():
    candles = [_c(20.0, 100_000) for _ in range(10)]
    assert median_dollar_volume(candles, period=60) == 2_000_000.0


def test_robust_gegen_leere_und_ungueltige_daten():
    assert median_dollar_volume([]) is None
    assert median_dollar_volume([_c(0.0, 0.0) for _ in range(5)]) is None


def test_gerade_anzahl_mittelt_die_beiden_mittleren():
    candles = [_c(1.0, 100), _c(1.0, 200), _c(1.0, 300), _c(1.0, 400)]
    assert median_dollar_volume(candles) == 250.0


def test_gleiche_definition_wie_breakout_signal():
    """Beide Stellen muessen dieselbe Zahl liefern — sonst hat das System
    wieder zwei Liquiditaetsbegriffe."""
    import statistics

    candles = [_c(10.0 + i * 0.1, 100_000 + i * 1_000) for i in range(62)]
    window = candles[-61:-1]                       # Fenster aus evaluate_breakout
    ref = statistics.median(c.c * c.v for c in window)
    assert median_dollar_volume(window, period=60) == ref
