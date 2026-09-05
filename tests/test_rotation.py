"""Tests für die Auffrisch-Rotation und den Ausfall-Backoff.

Hintergrund: Ohne Backoff verhungert die Rotation. Ein Ticker, der nie
erfolgreich beschafft wird, behält as_of=None, sortiert als "" ganz nach vorne
und wird jeden Tag erneut zuerst gewählt. Im Lauf vom 2026-09-05 scheiterten so
1055 von 1500 gewählten Titeln; effektiv frisch wurden 445/Tag statt 1500,
und der älteste Datenstand blieb 53 Tage alt, obwohl der Cron täglich lief.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from scripts.compute_scores import _backoff_days, _in_backoff, _select_oldest


@dataclass
class _Snap:
    as_of: str | None


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------- #
#  Backoff-Staffel
# --------------------------------------------------------------------------- #
def test_erste_zwei_ausfaelle_ohne_strafe():
    """Echtes Throttling muss sich erholen dürfen, ohne dass ein Titel
    tagelang zurückgestellt wird."""
    assert _backoff_days(1) == 0
    assert _backoff_days(2) == 0


def test_backoff_waechst_exponentiell_und_ist_gedeckelt():
    assert _backoff_days(3) == 2
    assert _backoff_days(5) == 8
    assert _backoff_days(7) == 30
    assert _backoff_days(20) == 30           # Deckel greift


def test_in_backoff_beachtet_zeitpunkt():
    now = datetime.now(timezone.utc)
    frisch = {"fails": 5, "last": _iso(1)}    # 8 Tage Sperre, 1 Tag her
    abgelaufen = {"fails": 5, "last": _iso(9)}
    assert _in_backoff(frisch, now)
    assert not _in_backoff(abgelaufen, now)


def test_leerer_oder_kaputter_eintrag_sperrt_nicht():
    now = datetime.now(timezone.utc)
    assert not _in_backoff(None, now)
    assert not _in_backoff({}, now)
    assert not _in_backoff({"fails": 9, "last": "kein-datum"}, now)


# --------------------------------------------------------------------------- #
#  Auswahl
# --------------------------------------------------------------------------- #
def test_nie_beschaffte_kommen_zuerst():
    cache = {"ALT": _Snap(_iso(30)), "NEU": _Snap(_iso(1))}
    batch = _select_oldest(["ALT", "NEU", "NIE"], cache, 3)
    assert batch[0] == "NIE"
    assert batch[1:] == ["ALT", "NEU"]


def test_tote_symbole_blockieren_die_plaetze_nicht_mehr():
    """Der eigentliche Fix: Ein dauerhaft scheiterndes Symbol darf den
    knappen Platz nicht jeden Tag erneut belegen."""
    cache = {"GUT": _Snap(_iso(20))}
    failures = {"TOT": {"fails": 9, "last": _iso(0)}}
    batch = _select_oldest(["TOT", "GUT"], cache, 1, failures)
    assert batch == ["GUT"]                  # ohne Backoff wäre es ["TOT"]


def test_abgelaufener_backoff_wird_wieder_versucht():
    cache = {"GUT": _Snap(_iso(1))}
    failures = {"TOT": {"fails": 3, "last": _iso(5)}}   # 2 Tage Sperre, 5 Tage her
    batch = _select_oldest(["TOT", "GUT"], cache, 1, failures)
    assert batch == ["TOT"]


def test_ohne_fehlerliste_unveraendertes_verhalten():
    cache = {"A": _Snap(_iso(5)), "B": _Snap(_iso(2))}
    assert _select_oldest(["A", "B"], cache, 2) == ["A", "B"]
