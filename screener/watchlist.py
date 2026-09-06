"""Wochen-Watchlist nach der Vier-Schritte-Methodik (Chartsekte, „Seven Figure Watchlist").

Das E-Book beschreibt einen Trichter, kein Kaufsignal:

  1. Assetklasse festlegen   Aktien, betrachtet über die elf GICS-Sektoren
  2. Screening durchführen   Universum nach Strategie-Kriterien eingrenzen
  3. Kandidaten bewerten     Trendstruktur, relevante Kursbereiche, Volumen
  4. Watchlist erstellen     Kandidaten nach Priorität ordnen und beobachten

Ergänzt um den vom Nutzer beschriebenen Ablauf: zuerst der Marktüberblick,
dann die Sektoren, dann erst die einzelnen Titel.

DER WICHTIGSTE SATZ AUS DEM E-BOOK, der auch hier gilt:

    „Priorität ≠ Trade — Es wird erst gehandelt, wenn das Setup erfüllt ist."

Diese Liste sagt NICHT, welche Aktien steigen. Sie sagt, wo es sich lohnt
hinzuschauen — und zwar begründet aus Daten, die bereits berechnet sind. Wo
die Datengrundlage dünn ist, taucht ein Titel gar nicht erst auf.

Ehrliche Einordnung der Trennschärfe: Der Walk-Forward-Test über 127 Stichtage
ergab für die Signalstufen zwar die erwartete Rangfolge (stark ≥ moderat ≥
schwach), aber mit kleinem Abstand — +0,97 Prozentpunkte auf 60 Handelstage.
Das ist schwache Evidenz. Die Watchlist ist deshalb als Vorauswahl gebaut,
nicht als Empfehlung.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Schritt 1: Die elf GICS-Sektoren ────────────────────────────────────────
# Yahoo liefert eigene Bezeichnungen; hier auf die GICS-Systematik des E-Books
# abgebildet. „Financials" und „Financial Services" sind derselbe Sektor —
# in den Rohdaten kommen beide Schreibweisen vor.
GICS_MAP: dict[str, str] = {
    "Technology": "Informationstechnologie",
    "Information Technology": "Informationstechnologie",
    "Financial Services": "Finanzwesen",
    "Financials": "Finanzwesen",
    "Healthcare": "Gesundheitswesen",
    "Health Care": "Gesundheitswesen",
    "Consumer Cyclical": "Nicht-Basiskonsumgüter",
    "Consumer Discretionary": "Nicht-Basiskonsumgüter",
    "Consumer Defensive": "Basiskonsumgüter",
    "Consumer Staples": "Basiskonsumgüter",
    "Industrials": "Industrie",
    "Communication Services": "Kommunikation",
    "Basic Materials": "Grundstoffe",
    "Materials": "Grundstoffe",
    "Energy": "Energie",
    "Utilities": "Versorger",
    "Real Estate": "Immobilien",
}

# Mindestanforderungen, damit ein Titel überhaupt betrachtet wird. Bewusst
# streng: Eine Watchlist mit unbrauchbaren Kandidaten kostet mehr Zeit,
# als sie spart.
MIN_DATA_QUALITY = 60          # entspricht der Grenze zu „unzureichend"
MIN_TOTAL_SCORE = 50
EXCLUDED_RATINGS = frozenset({"UNKLAR", "VERKAUFEN", "REDUZIEREN"})
MIN_SECTOR_SIZE = 5            # kleinere Sektoren sind statistisch wertlos

# Zustände, die der Screener selbst als untauglich einstuft. Ein Titel, den die
# eigene Zustandsmaschine auf „Vermeiden" setzt, darf nicht über einen anderen
# Weg wieder auf eine Empfehlungsliste geraten — im ersten Testlauf standen so
# zwei illiquide Vorzugsklassen auf Priorität 1.
EXCLUDED_STATUS = frozenset({"Vermeiden", "Trendbruch"})

# Zu dünn gehandelte Titel gehören nicht auf eine Watchlist: Dort bewegt die
# eigene Order den Kurs, und die Datenqualität ist typischerweise schlecht.
EXCLUDED_LIQUIDITY = frozenset({"illiquide"})

# Priorität 1 verlangt Nähe zum Auslöser; die Werte stammen aus der
# Basis-Struktur (screener/base_formation.py), nicht aus einer Faustregel.
P1_MAX_DIST_PCT = 3.0
P2_MAX_DIST_PCT = 8.0
MAX_RISK_PCT = 0.15


@dataclass(slots=True)
class MarketOverview:
    """Schritt 0: Wie steht der Gesamtmarkt? (Intermarket-Blick)"""
    n_total: int
    share_uptrend: float           # Anteil im langfristigen Aufwärtstrend
    share_downtrend: float
    median_score: float
    breadth_verdict: str           # freundlich | gemischt | defensiv
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"n_total": self.n_total,
                "share_uptrend": round(self.share_uptrend, 4),
                "share_downtrend": round(self.share_downtrend, 4),
                "median_score": round(self.median_score, 1),
                "breadth_verdict": self.breadth_verdict, "note": self.note}


@dataclass(slots=True)
class SectorRank:
    """Schritt 1: Sektor-Bewertung über die GICS-Systematik."""
    sector: str
    n: int
    median_score: float
    share_uptrend: float
    n_candidates: int              # Titel, die die Grundfilter bestehen
    rank: int = 0
    verdict: str = ""              # stark | neutral | schwach

    def to_dict(self) -> dict[str, Any]:
        return {"sector": self.sector, "n": self.n,
                "median_score": round(self.median_score, 1),
                "share_uptrend": round(self.share_uptrend, 4),
                "n_candidates": self.n_candidates,
                "rank": self.rank, "verdict": self.verdict}


@dataclass(slots=True)
class Candidate:
    """Schritt 3/4: Ein Kandidat mit Begründung und Prioritätsstufe."""
    ticker: str
    name: str | None
    sector: str
    priority: int                  # 1 | 2 | 3
    price: float | None
    currency: str | None
    total_score: int | None
    rating: str | None
    signal_strength: str | None
    data_quality: int | None
    status: str | None
    trend_long: str | None
    reason: str                    # warum diese Stufe — aus den Daten abgeleitet
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    stop: float | None = None
    dist_to_pivot_pct: float | None = None
    risk_pct: float | None = None
    liquidity_segment: str | None = None
    base_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class Watchlist:
    generated_at: str
    market: MarketOverview
    sectors: list[SectorRank] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    universe_size: int = 0
    passed_filter: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "market": self.market.to_dict(),
            "sectors": [s.to_dict() for s in self.sectors],
            "candidates": [c.to_dict() for c in self.candidates],
            "universe_size": self.universe_size,
            "passed_filter": self.passed_filter,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
#  Hilfen
# --------------------------------------------------------------------------- #
def _gics(sector: str | None) -> str | None:
    if not sector:
        return None
    return GICS_MAP.get(sector.strip(), sector.strip())


def _base(row: dict[str, Any]) -> dict[str, Any]:
    d = row.get("drivers") or {}
    return (d.get("base") or {}) if isinstance(d, dict) else {}


def _breakout(row: dict[str, Any]) -> dict[str, Any]:
    d = row.get("drivers") or {}
    return (d.get("breakout") or {}) if isinstance(d, dict) else {}


def _passes_basics(row: dict[str, Any]) -> bool:
    """Schritt 2: die Grundfilter des Screenings.

    Bewusst hart: Ein Titel ohne belastbare Datengrundlage gehört nicht auf
    eine Liste, die Aufmerksamkeit lenken soll.
    """
    if (row.get("data_quality") or 0) < MIN_DATA_QUALITY:
        return False
    if row.get("rating") in EXCLUDED_RATINGS or not row.get("rating"):
        return False
    if (row.get("total_score") or 0) < MIN_TOTAL_SCORE:
        return False
    if row.get("signal_strength") in (None, "kein Signal", "schwach"):
        return False
    if (row.get("status") or "") in EXCLUDED_STATUS:
        return False
    if (_breakout(row).get("segment") or "") in EXCLUDED_LIQUIDITY:
        return False
    return _gics(row.get("sector")) is not None


# --------------------------------------------------------------------------- #
#  Schritt 0: Marktüberblick
# --------------------------------------------------------------------------- #
def build_market_overview(rows: list[dict[str, Any]]) -> MarketOverview:
    n = len(rows)
    if not n:
        return MarketOverview(0, 0.0, 0.0, 0.0, "unbekannt",
                              "Keine Daten für einen Marktüberblick.")
    up = sum(1 for r in rows if r.get("trend_long") == "AUFWÄRTS")
    down = sum(1 for r in rows if r.get("trend_long") == "ABWÄRTS")
    scores = [r["total_score"] for r in rows if r.get("total_score") is not None]
    med = statistics.median(scores) if scores else 0.0
    share_up, share_down = up / n, down / n

    # Marktbreite: Wie viele Titel tragen den Markt tatsächlich?
    if share_up >= 0.45:
        verdict = "freundlich"
        note = (f"{share_up:.0%} der Titel stehen im langfristigen Aufwärtstrend — "
                f"eine breit getragene Marktphase.")
    elif share_up >= 0.25:
        verdict = "gemischt"
        note = (f"Nur {share_up:.0%} im Aufwärtstrend, {share_down:.0%} abwärts. "
                f"Die Marktbreite ist dünn; Sektorauswahl zählt mehr als sonst.")
    else:
        verdict = "defensiv"
        note = (f"Lediglich {share_up:.0%} im Aufwärtstrend bei {share_down:.0%} "
                f"abwärts. In so einer Phase scheitern auch gute Setups häufiger.")
    return MarketOverview(n, share_up, share_down, med, verdict, note)


# --------------------------------------------------------------------------- #
#  Schritt 1: Sektor-Ranking
# --------------------------------------------------------------------------- #
def rank_sectors(rows: list[dict[str, Any]]) -> list[SectorRank]:
    """Bewertet die GICS-Sektoren, damit der Fokus früh auf die relevanten fällt."""
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        g = _gics(r.get("sector"))
        if g:
            by.setdefault(g, []).append(r)

    out: list[SectorRank] = []
    for sec, items in by.items():
        if len(items) < MIN_SECTOR_SIZE:
            continue
        scores = [i["total_score"] for i in items if i.get("total_score") is not None]
        up = sum(1 for i in items if i.get("trend_long") == "AUFWÄRTS")
        out.append(SectorRank(
            sector=sec, n=len(items),
            median_score=statistics.median(scores) if scores else 0.0,
            share_uptrend=up / len(items),
            n_candidates=sum(1 for i in items if _passes_basics(i))))

    # Rangfolge: Mittelwert aus Score-Niveau und Trendanteil — ein Sektor mit
    # hohem Score, in dem aber kaum ein Titel im Aufwärtstrend steht, ist
    # weniger interessant als einer, in dem beides zusammenkommt.
    out.sort(key=lambda s: -(s.median_score / 100.0 + s.share_uptrend))
    for i, s in enumerate(out, 1):
        s.rank = i
        s.verdict = "stark" if i <= 3 else "schwach" if i > len(out) - 3 else "neutral"
    return out


# --------------------------------------------------------------------------- #
#  Schritt 2/3: Kandidaten und Priorisierung
# --------------------------------------------------------------------------- #
def _classify_priority(row: dict[str, Any]) -> tuple[int, str] | None:
    """Ordnet einen Titel einer Prioritätsstufe zu — mit Begründung.

    Die Stufen stammen aus dem E-Book; die Zuordnung nutzt die bereits
    berechnete Basis-Struktur und die Zustandsmaschine des Screeners.
    """
    base = _base(row)
    status = row.get("status") or ""
    dist = base.get("dist_to_pivot_pct")
    risk = base.get("risk_pct")
    state = base.get("state") or ""

    riskig = risk is not None and risk > MAX_RISK_PCT

    # Priorität 1 — kurz vor dem Einstieg: Der Auslöser ist in Reichweite.
    if not riskig and dist is not None and 0 <= dist <= P1_MAX_DIST_PCT:
        return 1, (f"Kurs steht {dist:.1f} % unter dem Ausbruchspunkt "
                   f"({base.get('pivot'):.2f}) — der Auslöser ist in Reichweite.")
    # „Ausbruch vorbereitet" allein reicht für Priorität 1 nicht — der Auslöser
    # muss auch in Reichweite sein. Sonst landete Blackstone mit 9,4 % Abstand
    # in der Stufe „kurz vor dem Einstieg".
    if (status == "Ausbruch vorbereitet" and not riskig
            and (dist is None or dist <= P1_MAX_DIST_PCT)):
        return 1, "Struktur ist zusammengezogen, der Ausbruch ist vorbereitet."

    # Priorität 2 — nahe am relevanten Bereich.
    if not riskig and dist is not None and dist <= P2_MAX_DIST_PCT:
        return 2, (f"Noch {dist:.1f} % bis zum Ausbruchspunkt — der relevante "
                   f"Bereich rückt näher.")
    if status == "Pullback-Einstieg":
        return 2, "Rücksetzer in einem intakten Aufwärtstrend an eine Unterstützung."
    if status == "Ausbruch vorbereitet":
        # Struktur ist zusammengezogen, der Auslöser aber noch weiter weg.
        # Das ist mehr als ein beliebiger Aufwärtstrend und gehört deshalb
        # nicht auf dieselbe Stufe wie dieser.
        weit = f" — noch {dist:.1f} % bis dorthin" if dist is not None else ""
        return 2, f"Struktur ist zusammengezogen, der Ausbruch ist vorbereitet{weit}."
    if status == "Bodenbildung" and state and "gebrochen" not in state:
        return 2, f"Bodenbildung läuft ({state}) — der Bereich ist noch nicht erreicht."

    # Priorität 3 — beobachten, aber noch weit entfernt.
    if row.get("trend_long") == "AUFWÄRTS":
        return 3, "Intakter Aufwärtstrend, aber derzeit kein naher Auslöser."
    if status in ("Position verwalten", "Regression abwarten"):
        return 3, f"Läuft bereits ({status}) — für einen Neueinstieg zu weit."
    return None


def build_watchlist(rows: list[dict[str, Any]], *,
                    per_priority: int = 8,
                    favour_top_sectors: int = 5) -> Watchlist:
    """Baut die vollständige Wochen-Watchlist aus den Screener-Zeilen.

    `favour_top_sectors`: Aus wie vielen der bestbewerteten Sektoren
    bevorzugt ausgewählt wird — die Umsetzung von „erst Sektor, dann Aktie".
    """
    market = build_market_overview(rows)
    sectors = rank_sectors(rows)
    top = {s.sector for s in sectors[:favour_top_sectors]}

    kandidaten: list[tuple[int, float, Candidate]] = []
    passed = 0
    for r in rows:
        if not _passes_basics(r):
            continue
        passed += 1
        cls = _classify_priority(r)
        if cls is None:
            continue
        prio, grund = cls
        g = _gics(r.get("sector")) or "—"
        base, bo = _base(r), _breakout(r)

        # Sortierschlüssel: innerhalb einer Stufe zuerst die Titel aus starken
        # Sektoren, dann nach Gesamtscore.
        rang = (0 if g in top else 1, -(r.get("total_score") or 0))
        kandidaten.append((prio, rang, Candidate(
            ticker=r["ticker"], name=r.get("name"), sector=g, priority=prio,
            price=r.get("price"), currency=r.get("currency"),
            total_score=r.get("total_score"), rating=r.get("rating"),
            signal_strength=r.get("signal_strength"),
            data_quality=r.get("data_quality"), status=r.get("status"),
            trend_long=r.get("trend_long"), reason=grund,
            buy_zone_low=base.get("buy_zone_low"),
            buy_zone_high=base.get("buy_zone_high"),
            stop=base.get("stop"), dist_to_pivot_pct=base.get("dist_to_pivot_pct"),
            risk_pct=base.get("risk_pct"),
            liquidity_segment=bo.get("segment"), base_state=base.get("state"))))

    kandidaten.sort(key=lambda x: (x[0], x[1]))

    # Anteilsklassen desselben Unternehmens zusammenfassen: ADAMN und ADAMM
    # sind beide „Adamas Trust, Inc." und belegten im ersten Lauf zwei Plätze
    # mit derselben Aussage. Es bleibt der bestbewertete Vertreter.
    gesehen: set[str] = set()
    eindeutig: list[tuple[int, Any, Candidate]] = []
    for prio, rang, c in kandidaten:
        schluessel = (c.name or c.ticker).strip().lower()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        eindeutig.append((prio, rang, c))

    gewaehlt: list[Candidate] = []
    for p in (1, 2, 3):
        gewaehlt += [c for prio, _, c in eindeutig if prio == p][:per_priority]

    note = ("Priorität ≠ Trade. Diese Liste zeigt, wo sich ein Setup entwickeln "
            "könnte — gehandelt wird erst, wenn die Bedingungen deiner Strategie "
            "tatsächlich erfüllt sind.")
    return Watchlist(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market=market, sectors=sectors, candidates=gewaehlt,
        universe_size=len(rows), passed_filter=passed, note=note)
