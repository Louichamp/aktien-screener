"""Messwerte eines Screening-Laufs — Grundlage für Nachvollziehbarkeit und Monitoring.

Bis hierher gab es über einen Lauf nur zwei Zahlen: „X in DB geschrieben" und
die Gesamtdauer. Ob die Daten vollständig waren, wie viele Titel auf halber
Datenlage bewertet wurden, wie oft die Datenquelle ausfiel oder wie viele
Datenbank-Roundtrips nötig waren — nichts davon war sichtbar. Damit ist die
Frage „ist der Screener heute sauber gelaufen?" nicht beantwortbar gewesen.

Bewusst schlicht: ein Zähler-Objekt und eine JSON-Datei. Kein Metrik-Dienst,
keine Zeitreihen-Datenbank — dafür ist ein täglicher Lauf zu wenig Signal.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunMetrics:
    """Sammelt Kennzahlen während eines Laufs. Alle Felder sind Rohzählungen —
    Ableitungen (Quoten) entstehen erst in `to_dict`, damit nichts doppelt
    gepflegt werden muss."""

    started_at: str = field(default_factory=_now)
    _t0: float = field(default_factory=time.monotonic)
    phases: dict[str, float] = field(default_factory=dict)

    # Universum und Beschaffung
    universe_size: int = 0
    selected: int = 0                  # zur Auffrischung ausgewählt
    skipped_backoff: int = 0           # wegen wiederholter Ausfälle zurückgestellt
    fetch_ok: int = 0
    fetch_failed: int = 0
    fundamentals_reused: int = 0       # Stammdaten aus dem Cache übernommen
    provider_batch_calls: int = 0      # Block-Downloads (je ~50 Titel)
    provider_info_calls: int = 0       # Einzelabrufe der Stammdaten

    # Verarbeitung
    universe_scored: int = 0           # Titel, die die Score-Engine durchliefen
    indicators_computed: int = 0       # Summe berechneter Indikator-Felder
    scores_computed: int = 0           # Summe berechneter Sub-Scores
    score_full: int = 0                # volle technische Datenabdeckung
    score_partial: int = 0             # unter dem Schwellwert -> unsicher
    score_none: int = 0                # gar kein technisches Rating
    db_statements: int = 0             # ausgeführte SQL-Anweisungen (= Roundtrips)
    rows_written: int = 0

    # Fehler, nach Ursache gruppiert (nicht nur gezählt)
    errors: Counter = field(default_factory=Counter)
    error_samples: dict[str, str] = field(default_factory=dict)

    def phase(self, name: str) -> "_Phase":
        return _Phase(self, name)

    def note_error(self, ticker: str, message: str) -> None:
        """Gruppiert nach Ursache — 1000-mal dieselbe Ursache ist EIN Problem,
        nicht tausend."""
        kind = message.split(":", 1)[0].strip()[:40] or "unbekannt"
        self.errors[kind] += 1
        self.error_samples.setdefault(kind, f"{ticker}: {message}"[:200])

    def to_dict(self) -> dict[str, Any]:
        runtime = time.monotonic() - self._t0
        sel = max(self.selected, 1)
        scored = max(self.universe_scored, 1)
        return {
            "started_at": self.started_at,
            "finished_at": _now(),
            "runtime_seconds": round(runtime, 1),
            "phases_seconds": {k: round(v, 1) for k, v in self.phases.items()},
            "universe": {
                "size": self.universe_size,
                "selected_for_refresh": self.selected,
                "skipped_backoff": self.skipped_backoff,
            },
            "fetch": {
                "ok": self.fetch_ok,
                "failed": self.fetch_failed,
                "success_rate": round(self.fetch_ok / sel, 4),
                "fundamentals_reused": self.fundamentals_reused,
                "fundamentals_cache_hit_rate": round(self.fundamentals_reused / sel, 4),
                "provider_batch_calls": self.provider_batch_calls,
                "provider_info_calls": self.provider_info_calls,
                "provider_calls_total": self.provider_batch_calls + self.provider_info_calls,
                "calls_per_ticker": round(
                    (self.provider_batch_calls + self.provider_info_calls) / sel, 3),
            },
            "compute": {
                "scored": self.universe_scored,
                "indicators_computed": self.indicators_computed,
                "indicators_per_ticker": round(self.indicators_computed / scored, 1),
                "scores_computed": self.scores_computed,
                "score_full": self.score_full,
                "score_partial": self.score_partial,
                "score_none": self.score_none,
                "full_rate": round(self.score_full / scored, 4),
            },
            "database": {
                "statements": self.db_statements,
                "statements_per_ticker": round(self.db_statements / scored, 3),
                "rows_written": self.rows_written,
            },
            "errors": {
                "total": sum(self.errors.values()),
                "by_kind": dict(self.errors.most_common()),
                "samples": self.error_samples,
            },
        }

    def write(self, path: Path) -> dict[str, Any]:
        data = self.to_dict()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return data

    def summary(self) -> str:
        d = self.to_dict()
        return (
            f"Lauf {d['runtime_seconds']}s | "
            f"beschafft {d['fetch']['ok']}/{d['universe']['selected_for_refresh']} "
            f"({d['fetch']['success_rate']:.0%}) | "
            f"Provider-Aufrufe {d['fetch']['provider_calls_total']} "
            f"({d['fetch']['calls_per_ticker']}/Titel) | "
            f"Stammdaten-Cache {d['fetch']['fundamentals_cache_hit_rate']:.0%} | "
            f"DB-Anweisungen {d['database']['statements']} "
            f"({d['database']['statements_per_ticker']}/Titel) | "
            f"volle Datenlage {d['compute']['full_rate']:.0%} | "
            f"Fehler {d['errors']['total']}")


class _Phase:
    """Kontextmanager: misst die Dauer eines Abschnitts."""

    def __init__(self, m: RunMetrics, name: str) -> None:
        self.m, self.name = m, name

    def __enter__(self) -> "_Phase":
        self._t = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.m.phases[self.name] = self.m.phases.get(self.name, 0.0) + (
            time.monotonic() - self._t)


def attach_db_counter(engine: Any, metrics: RunMetrics) -> None:
    """Zählt tatsächlich ausgeführte SQL-Anweisungen.

    Jede Anweisung ist ein Netzwerk-Roundtrip zur Datenbank; bei einer
    verwalteten Postgres-Instanz ist das die dominierende Kostengröße.
    """
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        metrics.db_statements += 1
