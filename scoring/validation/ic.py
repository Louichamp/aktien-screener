"""Information Coefficient (IC) — empirische Vorhersagegüte je Signal.

Der IC ist das institutionelle Standardmaß für Signalqualität: die
Querschnitts-Rangkorrelation zwischen dem Signalwert zum Zeitpunkt t und der
realisierten Vorwärtsrendite (t → t+h). Über viele Rebalancing-Termine gemittelt
liefert er:

  • IC_mean      — durchschnittliche Vorhersagekraft (Vorzeichen + Stärke)
  • IC_std       — Streuung der Vorhersagekraft (Instabilität)
  • IC_t_stat    — IC_mean / IC_std · √n  (statistische Signifikanz der Kante)
  • hit_rate     — Anteil der Termine mit korrektem Vorzeichen

Rang-IC (Spearman) statt Pearson, weil Scores nichtlinear skaliert sind und wir
nur die ORDNUNG bewerten — robust gegen Ausreißer und monotone Transformationen.

Alles reine stdlib, O(n log n) je Termin, deterministisch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _ranks(values: list[float]) -> list[float]:
    """Durchschnittsränge (Ties bekommen den Mittelrang) — für Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(values)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0          # 1-basierter Mittelrang
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:                # konstante Reihe → keine Korrelation
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return sxy / math.sqrt(sxx * syy)


def rank_ic(signal: list[float], forward_return: list[float]) -> float | None:
    """Spearman-Rang-IC zwischen Signal und Vorwärtsrendite eines Termins.

    Erwartet zwei gleich lange, ausgerichtete Listen (gleiche Reihenfolge der
    Titel). Gibt None bei <3 Beobachtungen oder entarteter (konstanter) Reihe.
    """
    if len(signal) != len(forward_return) or len(signal) < 3:
        return None
    return _pearson(_ranks(signal), _ranks(forward_return))


@dataclass(slots=True)
class ICStats:
    """Aggregierte IC-Statistik eines Signals über viele Termine."""
    slug: str
    ic_mean: float
    ic_std: float
    ic_t_stat: float            # Signifikanz der Kante (|t|≳2 ≈ tragfähig)
    hit_rate: float             # Anteil Termine mit Vorzeichen von ic_mean
    n_periods: int
    by_regime: dict[str, float] # IC_mean je Regime-Label (regime-bedingte Gültigkeit)

    @property
    def reliable(self) -> bool:
        """Tragfähige, stabile Kante: signifikant UND vorzeichenkonsistent."""
        return abs(self.ic_t_stat) >= 2.0 and self.hit_rate >= 0.55 and self.n_periods >= 12


def ic_summary(slug: str, ic_series: list[float],
               regimes: list[str] | None = None) -> ICStats | None:
    """Verdichtet eine Reihe von Termin-ICs zu robuster Statistik.

    `ic_series` ist je ein Rang-IC pro Rebalancing-Termin; `regimes` (optional)
    das Regime-Label je Termin für die regime-bedingte Auswertung.
    """
    vals = [c for c in ic_series if c is not None]
    n = len(vals)
    if n < 3:
        return None
    mean = sum(vals) / n
    var = sum((c - mean) ** 2 for c in vals) / (n - 1)
    std = math.sqrt(max(var, 1e-12))
    t_stat = mean / std * math.sqrt(n) if std > 0 else 0.0
    sign = 1.0 if mean >= 0 else -1.0
    hit = sum(1 for c in vals if c * sign > 0) / n

    by_regime: dict[str, float] = {}
    if regimes is not None and len(regimes) == len(ic_series):
        buckets: dict[str, list[float]] = {}
        for c, rg in zip(ic_series, regimes):
            if c is not None:
                buckets.setdefault(rg, []).append(c)
        by_regime = {rg: sum(b) / len(b) for rg, b in buckets.items() if b}

    return ICStats(slug, mean, std, t_stat, hit, n, by_regime)


def signal_half_life(ic_by_horizon: dict[int, float]) -> float | None:
    """Schätzt die Signal-Halbwertszeit (in Bars) aus IC über Horizonte.

    Nimmt den Horizont mit maximalem |IC| als Peak und sucht den Horizont, an dem
    |IC| auf die Hälfte des Peaks fällt (lineare Interpolation). Misst, wie schnell
    die Information „veraltet" — kurze Halbwertszeit = schnelles, langes = träges
    Signal. Gibt None, wenn der IC im Beobachtungsfenster nicht halbiert.
    """
    pts = sorted((h, abs(ic)) for h, ic in ic_by_horizon.items() if ic is not None)
    if len(pts) < 2:
        return None
    peak_h, peak_ic = max(pts, key=lambda p: p[1])
    if peak_ic <= 0:
        return None
    target = peak_ic / 2.0
    prev = None
    for h, ic in pts:
        if h <= peak_h:
            prev = (h, ic)
            continue
        if ic <= target and prev is not None:
            (h0, i0), (h1, i1) = prev, (h, ic)
            if i0 == i1:
                return float(h1)
            frac = (i0 - target) / (i0 - i1)
            return h0 + frac * (h1 - h0)
        prev = (h, ic)
    return None


def regularized_weights(prior: dict[str, float],
                        ic_stats: dict[str, ICStats],
                        *, max_tilt: float = 0.5,
                        ic_scale: float = 0.05,
                        t0: float = 2.0,
                        n_k: float = 12.0) -> dict[str, float]:
    """Evidenz-korrigierte Gewichte via SHRINKAGE gegen den Prior — kein Fitting.

    Für jedes Signal:

        reliability = n / (n + n_k)                 # Stichproben-Vertrauen 0..1
        significance = t² / (t² + t0²)              # Signifikanz-Shrinkage 0..1
        direction   = tanh(IC_mean / ic_scale)      # Vorzeichen+Stärke, gesättigt
        tilt = max_tilt · direction · reliability · significance     # ∈ [−max_tilt, +max_tilt]
        w' = prior · (1 + tilt)

    Anschließend werden die w' so renormiert, dass die Summe der Prior-Gewichte
    erhalten bleibt (Gesamt-Skala unverändert).

    Eigenschaften (bewusst konservativ, anti-overfit):
      • Ohne Evidenz (n→0 oder t→0): tilt→0 ⇒ Gewichte = Prior (No-Op). Das System
        startet exakt im heutigen Zustand und weicht nur mit echter, signifikanter
        Out-of-Sample-Evidenz ab.
      • Negativer IC (Signal war anti-prädiktiv): tilt<0 ⇒ Abwertung bis (1−max_tilt).
        Das Vorzeichen wird NICHT gedreht (das wäre regime-fragiles Overfitting) —
        einem schädlichen Signal wird lediglich vertraut-entzogen.
      • max_tilt deckelt den Einfluss hart: selbst „perfekte" Evidenz kann ein
        Gewicht höchstens um ±max_tilt verschieben.
    """
    if not prior:
        return {}
    raw: dict[str, float] = {}
    for slug, w in prior.items():
        st = ic_stats.get(slug)
        if st is None or st.n_periods < 3:
            raw[slug] = w                         # keine Evidenz → Prior unverändert
            continue
        reliability = st.n_periods / (st.n_periods + n_k)
        t2 = st.ic_t_stat * st.ic_t_stat
        significance = t2 / (t2 + t0 * t0)
        direction = math.tanh(st.ic_mean / ic_scale)
        tilt = max_tilt * direction * reliability * significance
        tilt = max(-max_tilt, min(max_tilt, tilt))
        raw[slug] = w * (1.0 + tilt)

    prior_sum = sum(prior.values())
    raw_sum = sum(raw.values())
    if raw_sum <= 0:
        return dict(prior)
    scale = prior_sum / raw_sum
    return {slug: v * scale for slug, v in raw.items()}
