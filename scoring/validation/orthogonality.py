"""Querschnitts-Informationsgeometrie: Redundanz vs. Orthogonalität der Signale.

Zwei Signale, die über den Querschnitt hoch korrelieren, tragen dieselbe
Information — ihre getrennte Verbuchung im Composite ist eine versteckte
Doppelzählung (Multikollinearität), die die effektive Diversifikation senkt und
ein latentes Faktor-Exposure aufbläht. Dieses Modul macht die Redundanz MESSBAR:

  • correlation_matrix — paarweise Rang-Korrelation aller Sub-Scores im Querschnitt.
  • redundancy_report  — Cluster hoch korrelierter Signale, je-Signal-Redundanz und
                         eine „effektive Anzahl unabhängiger Signale" (Partizipations-
                         Ratio der Korrelations-Eigenwerte-Näherung über Zeilensummen).

Bewusst nur DIAGNOSTIK + Empfehlung: eine automatische Pruning-/Penalty-Anwendung
pro Lauf würde unter rotierenden Teil-Universen instabil (die Korrelationsstruktur
schwankt mit der Stichprobe). Die Empfehlung fließt stattdessen kontrolliert in die
Offline-Kalibrierung und in bewusste Composite-Entscheidungen ein.
"""
from __future__ import annotations

import math
from .ic import _ranks


def _rank_corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxx = sum((x - mx) ** 2 for x in rx)
    syy = sum((y - my) ** 2 for y in ry)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    return sxy / math.sqrt(sxx * syy)


def correlation_matrix(panel: list[dict[str, float]], slugs: list[str]
                       ) -> dict[tuple[str, str], float]:
    """Paarweise Rang-Korrelation der Signale über den Querschnitt.

    `panel`: eine Liste von {slug: score}-Dicts (ein Eintrag je Titel). Nur Paare,
    bei denen beide Signale für genügend gemeinsame Titel vorliegen, werden besetzt.
    """
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            xs, ys = [], []
            for row in panel:
                va, vb = row.get(a), row.get(b)
                if va is not None and vb is not None:
                    xs.append(va)
                    ys.append(vb)
            c = _rank_corr(xs, ys)
            if c is not None:
                out[(a, b)] = c
    return out


def redundancy_report(panel: list[dict[str, float]], slugs: list[str],
                      *, threshold: float = 0.7) -> dict[str, object]:
    """Redundanz-Diagnose: Cluster, je-Signal-Redundanz, effektive Signalzahl.

    • clusters: Gruppen von Signalen mit paarweiser |Korr| ≥ threshold (transitiv
      über Union-Find verbunden) — Kandidaten für Zusammenlegung/Abwertung.
    • redundancy[slug]: mittlere |Korr| zu allen anderen Signalen (0..1); hoch =
      das Signal dupliziert weitgehend vorhandene Information.
    • effective_signals: Σ|corr|-basierte Partizipations-Ratio
      (Σ_i 1 / Σ_j |corr_ij|) — wie viele wirklich unabhängige Signale die Menge
      faktisch enthält (≤ Anzahl der Signale).
    """
    corr = correlation_matrix(panel, slugs)

    # Union-Find für die Cluster-Bildung über dem Schwellwert.
    parent = {s: s for s in slugs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (a, b), c in corr.items():
        if abs(c) >= threshold:
            union(a, b)

    groups: dict[str, list[str]] = {}
    for s in slugs:
        groups.setdefault(find(s), []).append(s)
    clusters = [sorted(g) for g in groups.values() if len(g) > 1]

    # Je-Signal-Redundanz und effektive Signalzahl.
    redundancy: dict[str, float] = {}
    eff = 0.0
    for s in slugs:
        abs_corrs = [abs(corr.get((min(s, o), max(s, o)), 0.0))
                     for o in slugs if o != s]
        redundancy[s] = (sum(abs_corrs) / len(abs_corrs)) if abs_corrs else 0.0
        row_sum = 1.0 + sum(abs_corrs)        # Selbstkorrelation 1 + Σ|corr|
        eff += 1.0 / row_sum

    return {
        "clusters": clusters,
        "redundancy": redundancy,
        "effective_signals": round(eff, 2),
        "n_signals": len(slugs),
    }
