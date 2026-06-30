"""Empirische Validierungs- und Selbstkorrektur-Schicht der Score-Engine.

Diese Schicht beantwortet die einzige Frage, die ein Allokations-System
beantworten muss: *Hat ein Signal in der Vergangenheit zukünftige Renditen
tatsächlich erklärt — stabil über Marktphasen?* Sie besteht aus vier reinen,
deterministischen, abhängigkeitsfreien Bausteinen:

  • ic.py            — Rolling Information Coefficient (Rang-IC), Stabilität,
                       Decay/Halbwertszeit und REGULARISIERTE Gewichtsschätzung
                       (Shrinkage gegen den Prior, NICHT naive Optimierung).
  • regime.py        — Volatilitäts-/Trend-Kohärenz-/Dispersions-Regime aus dem
                       Querschnitt; macht IC regime-bedingt auswertbar.
  • orthogonality.py — Querschnitts-Redundanz: welche Signale dieselbe Information
                       tragen (Korrelations-Pruning, effektive Informationsdichte).
  • decision.py      — Entscheidungs-Qualität je Titel (Coverage, Signal-Agreement,
                       Instabilität, Ranking-Konfidenz) — das finale Output-Layer.

Die Produktions-Scoring-Pfade bleiben unberührt: dieses Paket liefert Diagnostik
und (über die Offline-Kalibrierung) optionale, evidenzbasierte Gewichte. Ohne
vorliegende Evidenz reduziert sich alles auf das bestehende Verhalten — by design.
"""
from __future__ import annotations

from .ic import (ICStats, ic_summary, rank_ic, regularized_weights,
                 signal_half_life)
from .decision import DecisionQuality, decision_quality
from .orthogonality import correlation_matrix, redundancy_report
from .regime import RegimeSnapshot, classify_regime

__all__ = [
    "ICStats", "rank_ic", "ic_summary", "signal_half_life", "regularized_weights",
    "RegimeSnapshot", "classify_regime",
    "correlation_matrix", "redundancy_report",
    "DecisionQuality", "decision_quality",
]
