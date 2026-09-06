"""Batch-Score-Berechnung für die Live-API-Architektur (Render + Neon).

Läuft EINMAL pro Aufruf (GitHub Actions Cron, nicht dauerhaft) und schreibt alle
Scores direkt in die produktive Postgres-DB (`DATABASE_URL`). Das
FastAPI-Backend (`api/main.py`) liest diese Tabelle danach nur noch — es
berechnet nichts mehr live bei Requests.

Rollierender Cache (wie `rotating_sync.py` für den Netlify-Pfad): ein
Snapshot-Cache (Pickle) wächst über die Läufe, jeder Lauf frischt nur die
ÄLTESTEN N Ticker neu auf, rechnet aber das GESAMTE angesammelte Universum
cross-sectional neu (Peer-Perzentile brauchen die volle Kohorte, nicht nur den
Tages-Batch). Der Cache liegt bewusst NICHT in der DB — nur das fertige,
kompakte Ergebnis (`screener_rows`) landet in Postgres. Das hält den
DB-Storage klein (siehe Punkt 5/7 der Kostenschätzung); Rohdaten
(Kerzen, Technicals, Fundamentals) sind Wegwerf-Zwischenstand, kein Produktdatum.

Kronos/torch bewusst NICHT hier: der GitHub-Actions-Free-Runner hat keine GPU,
torch+transformers ist >2GB und würde den Free-Minuten-Etat sprengen. Es läuft
das torch-freie `StatisticalForecaster` (GBM aus echten Log-Renditen) — exakt
dieselbe Wahl wie im bereits produktiven Netlify-Pfad.

Eigenständiges Skript (keine Abhängigkeit von rotating_sync.py/build_site.py):
die beiden Pfade (Netlify-Static vs. Live-API) haben unterschiedliche
Nach-Schritte (Frontend-Export vs. nichts — Vercel baut selbst) und sollen sich
nicht gegenseitig destabilisieren können. Etwas Logik-Überlappung mit
rotating_sync.py ist der bewusste Preis dafür.

  # täglicher Cron-Lauf (GitHub Actions): die ältesten ~1500 auffrischen
  python scripts/compute_scores.py --cache .cache/snapshots.pkl --refresh 1500 \
      --limit 5250 --source broad

  # lokal: kompletten Rebuild erzwingen
  python scripts/compute_scores.py --cache .cache/snapshots.pkl --refresh all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.database.config import (create_engine, create_session_factory,
                                            init_models)
from infrastructure.database.repository import ScreenerRepository
from infrastructure.forecast import apply_forecasts, build_forecaster
from infrastructure.providers import build_market_data_provider, build_universe
from infrastructure.run_metrics import RunMetrics, attach_db_counter
from screener.pipeline import run_screener_pipeline


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Nur diese Klassen darf der Cache beim Entpickeln instanziieren. `pickle.load()`
# auf einer via `actions/cache` wiederhergestellten Datei ist grundsätzlich ein
# Code-Execution-Risiko (ein manipulierter Pickle-Stream kann beliebige
# Funktionen aufrufen) — der restriktive Unpickler unten lässt NUR die beiden
# hier tatsächlich verwendeten Dataclasses zu und lehnt jede andere
# Klassen-/Funktionsreferenz (das klassische Pickle-RCE-Gadget) hart ab.
_ALLOWED_CACHE_CLASSES = {
    ("screener.zones", "Candle"),
    ("screener.pipeline", "MarketSnapshot"),
}


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) not in _ALLOWED_CACHE_CLASSES:
            raise pickle.UnpicklingError(
                f"Cache enthält nicht erlaubte Klasse: {module}.{name}")
        return super().find_class(module, name)


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "rb") as fh:
                data = _RestrictedUnpickler(fh).load()
            if not isinstance(data, dict):
                print(f"Cache hat falschen Typ ({type(data).__name__}, erwartet dict) "
                      "— starte leer", flush=True)
                return {}
            print(f"Cache geladen: {len(data)} Snapshots", flush=True)
            return data
        except Exception as exc:
            print(f"Cache unlesbar ({exc}) — starte leer", flush=True)
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(cache, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


# --------------------------------------------------------------------------- #
#  Ausfall-Verfolgung (Backoff für dauerhaft tote Symbole)
# --------------------------------------------------------------------------- #
# Ohne das verhungert die Rotation: Ein Ticker, der NIE erfolgreich beschafft
# wird (delistet, ungültiges Symbol, bei Yahoo nicht vorhanden), behält für
# immer as_of=None -> sortiert als "" ganz nach vorne -> wird jeden Tag erneut
# zuerst gewählt, scheitert wieder und belegt dauerhaft einen der 1500 Plätze.
# Real gemessen am Lauf vom 2026-09-05: von 1500 gewählten Titeln scheiterten
# 1055; effektiv frisch wurden 445/Tag statt 1500. Dass die Retry-Pässe nur
# 6 Titel retteten, zeigt, dass es harte Fehler sind und kein Throttling.
def _load_failures(path: Path) -> dict[str, dict]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
        except Exception as exc:
            print(f"Fehlerliste unlesbar ({exc}) — starte leer", flush=True)
    return {}


def _save_failures(path: Path, failures: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(failures, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _backoff_days(fails: int) -> int:
    """Erste zwei Ausfälle ohne Strafe (echtes Throttling darf sich erholen),
    danach exponentiell bis maximal 30 Tage."""
    if fails < 3:
        return 0
    return min(2 ** (fails - 2), 30)


def _in_backoff(rec: dict | None, now: datetime) -> bool:
    if not rec:
        return False
    days = _backoff_days(int(rec.get("fails", 0)))
    if days <= 0:
        return False
    try:
        last = datetime.fromisoformat(str(rec.get("last", "")))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now < last + timedelta(days=days)


def _select_oldest(universe_tickers: list[str], cache: dict, n: int,
                   failures: dict[str, dict] | None = None) -> list[str]:
    """Nie beschaffte zuerst, dann nach data_as_of aufsteigend (älteste zuerst).

    Titel in Backoff werden übersprungen, damit dauerhaft tote Symbole die
    Plätze nicht blockieren.
    """
    failures = failures or {}
    now = datetime.now(timezone.utc)
    eligible = [t for t in universe_tickers if not _in_backoff(failures.get(t), now)]

    def key(t: str):
        snap = cache.get(t)
        return getattr(snap, "as_of", None) or ""        # "" = nie -> ganz vorne
    return sorted(eligible, key=key)[:n]


# Fundamentaldaten wechseln quartalsweise, nicht taeglich. Sie trotzdem bei
# jedem Lauf erneut zu holen war — neben dem Einzelabruf der Historie — der
# Grund fuer ~3000 Anfragen pro Lauf und damit fuer die Drosselung.
FUNDAMENTALS_MAX_AGE_DAYS = int(os.getenv("YF_FUNDAMENTALS_MAX_AGE_DAYS", "14"))


def _reusable_fundamentals(cache: dict, batch: list[str], max_age_days: int) -> dict:
    """Fuer welche Titel sind die Stammdaten noch frisch genug?

    Rueckgabe im Format, das `YahooMarketDataProvider.fetch_many` erwartet.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    out: dict = {}
    for tk in batch:
        snap = cache.get(tk)
        if snap is None or not getattr(snap, "fundamentals", None):
            continue
        raw = getattr(snap, "fundamentals_as_of", None) or getattr(snap, "as_of", None)
        try:
            stamp = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp < cutoff:
            continue
        out[tk] = {
            "fundamentals": dict(snap.fundamentals),
            "meta": {"name": snap.name, "sector": snap.sector,
                     "country": snap.country, "currency": snap.currency,
                     "market_cap": snap.market_cap, "asset_class": snap.asset_class},
            "_stamp": str(raw),
        }
    return out


async def _fetch_batch(provider, batch: list[str], by_sym: dict,
                       *, passes: int, chunk_size: int = 200,
                       cache: dict | None = None, metrics=None) -> dict:
    """Beschafft `batch` resilient. Nutzt den gebuendelten Weg, wenn der
    Provider ihn anbietet — sonst wie bisher Titel fuer Titel."""
    if hasattr(provider, "fetch_many"):
        return await _fetch_batch_bundled(provider, batch, by_sym,
                                          passes=passes, cache=cache or {},
                                          metrics=metrics)
    got: dict = {}
    todo = list(batch)
    for p in range(1, passes + 1):
        if not todo:
            break
        failed: list[str] = []
        done_this_pass = 0
        for i in range(0, len(todo), chunk_size):
            chunk = todo[i: i + chunk_size]
            results = await asyncio.gather(*(provider.fetch(t) for t in chunk),
                                           return_exceptions=True)
            for sym, snap in zip(chunk, results):
                if snap is None or isinstance(snap, Exception):
                    failed.append(sym)
                    continue
                e = by_sym.get(sym, {})
                if not snap.name:
                    snap.name = e.get("name")
                if not snap.sector:
                    snap.sector = e.get("sector")
                snap.as_of = _now_iso()
                got[sym] = snap
                done_this_pass += 1
            pct = (i + len(chunk)) / len(todo) * 100
            print(f"  Pass {p}/{passes}: {i + len(chunk)}/{len(todo)} verarbeitet "
                  f"({pct:.0f}%) — {done_this_pass} ok, {len(failed)} offen", flush=True)
        todo = failed
        if todo and p < passes:
            print(f"  Pause 20s vor Retry-Pass {p + 1} ({len(todo)} offen) …", flush=True)
            await asyncio.sleep(20)
    return got


async def _fetch_batch_bundled(provider, batch: list[str], by_sym: dict,
                               *, passes: int, cache: dict, metrics=None) -> dict:
    """Gebuendelter Weg: Historie blockweise, Stammdaten nur wo noetig.

    Gemessen an 30 Titeln: identische Preise und Indikatoren wie beim
    Einzelabruf (0 Abweichungen), aber ~1 statt ~60 Anfragen. Hochgerechnet
    auf 1500 Titel: ~30 statt ~3000.
    """
    reuse = _reusable_fundamentals(cache, batch, FUNDAMENTALS_MAX_AGE_DAYS)
    print(f"  Stammdaten: {len(reuse)}/{len(batch)} aus dem Cache uebernommen "
          f"(juenger als {FUNDAMENTALS_MAX_AGE_DAYS} Tage)", flush=True)

    got: dict = {}
    todo = list(batch)
    for p in range(1, passes + 1):
        if not todo:
            break
        try:
            fresh = await provider.fetch_many(todo, reuse_fundamentals=reuse,
                                              metrics=metrics)
        except Exception as exc:
            print(f"  Pass {p}/{passes} fehlgeschlagen: {exc}", flush=True)
            fresh = {}
        now = _now_iso()
        for sym, snap in fresh.items():
            e = by_sym.get(sym, {})
            if not snap.name:
                snap.name = e.get("name")
            if not snap.sector:
                snap.sector = e.get("sector")
            snap.as_of = now
            # Uebernommene Stammdaten behalten ihren alten Zeitstempel, damit
            # sie irgendwann tatsaechlich erneuert werden statt ewig zu altern.
            snap.fundamentals_as_of = (reuse[sym]["_stamp"] if sym in reuse else now)
            got[sym] = snap
        todo = [t for t in todo if t not in got]
        print(f"  Pass {p}/{passes}: {len(got)}/{len(batch)} ok, {len(todo)} offen",
              flush=True)
        if todo and p < passes:
            print(f"  Pause 20s vor Retry-Pass {p + 1} …", flush=True)
            await asyncio.sleep(20)
    return got


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "snapshots.pkl"))
    ap.add_argument("--refresh", default="1500", help="Anzahl ältester Werte oder 'all'")
    ap.add_argument("--limit", type=int, default=5250)
    ap.add_argument("--source", choices=["sp500", "broad"], default="broad")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--chunk", type=int, default=200, help="Fetch-Chunk-Größe für Progress-Logging")
    # Bewusst fix "statistical" (torch-frei) — s. Modul-Docstring. Kein --forecast-backend
    # Flag, damit niemand aus Versehen echtes Kronos/torch im Free-Runner aktiviert.
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--prune-orphans", action="store_true",
                    help="Zeilen löschen, die nicht mehr im Universum und veraltet sind "
                         "(ohne das Flag wird nur berichtet)")
    ap.add_argument("--orphan-age", type=int, default=60,
                    help="Ab welchem Alter in Tagen eine universumsfremde Zeile als Waise gilt")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")               # override=False -> Shell-Env gewinnt
    except Exception:
        pass

    t0 = time.monotonic()
    metrics = RunMetrics()
    cache_path = Path(args.cache)
    cache = _load_cache(cache_path)

    print(f"Universe laden (limit={args.limit}, source={args.source}) …", flush=True)
    with metrics.phase("universe"):
        universe = await build_universe(args.limit, source=args.source)
    by_sym = {e["symbol"]: e for e in universe}
    universe_tickers = list(by_sym)
    universe_set = set(universe_tickers)

    failures_path = cache_path.with_name("fetch_failures.json")
    failures = _load_failures(failures_path)

    refresh_all = str(args.refresh).lower() == "all"
    n = len(universe_tickers) if refresh_all else max(0, int(args.refresh))
    # Bei --refresh=all bewusst OHNE Backoff: ein manueller Volllauf soll auch
    # die zurückgestellten Titel noch einmal versuchen.
    batch = (_select_oldest(universe_tickers, cache, n)
             if refresh_all else _select_oldest(universe_tickers, cache, n, failures))
    metrics.universe_size = len(universe_tickers)
    metrics.selected = len(batch)
    now = datetime.now(timezone.utc)
    skipped = sum(1 for t in universe_tickers if _in_backoff(failures.get(t), now))
    metrics.skipped_backoff = skipped
    if skipped:
        dead = sum(1 for t in universe_tickers
                   if int(failures.get(t, {}).get("fails", 0)) >= 7)
        print(f"Backoff: {skipped} Titel zurückgestellt ({dead} davon dauerhaft "
              f"auffällig, >= 7 Ausfälle)", flush=True)

    cached_total = len(cache)
    missing = len([t for t in universe_tickers if t not in cache])
    print(f"Cache: {cached_total} vorhanden, {missing} noch nie beschafft, "
          f"{len(universe_tickers)} im Universum", flush=True)
    if missing > 0 and not refresh_all:
        print(f"  Bootstrap-Hinweis: {missing} Stocks noch nie gesehen. "
              f"Noch {missing // max(n, 1) + 1} Läufe bis vollständige Abdeckung.", flush=True)
    print(f"Auffrischen: {len(batch)} Werte ({'alle' if refresh_all else 'älteste zuerst'})",
          flush=True)

    provider = build_market_data_provider("yahoo")
    with metrics.phase("fetch"):
        fresh = await _fetch_batch(provider, batch, by_sym, passes=args.passes,
                                   chunk_size=args.chunk, cache=cache, metrics=metrics)
    if hasattr(provider, "aclose"):
        await provider.aclose()
    metrics.fetch_ok = len(fresh)
    metrics.fetch_failed = len(batch) - len(fresh)

    # Ausfall-Bilanz fortschreiben: Erfolg löscht den Eintrag, Misserfolg
    # erhöht den Zähler und setzt damit den Backoff für die nächsten Läufe.
    now_iso = _now_iso()
    for tk in batch:
        if tk in fresh:
            failures.pop(tk, None)
        else:
            rec = failures.get(tk) or {"fails": 0}
            rec["fails"] = int(rec.get("fails", 0)) + 1
            rec["last"] = now_iso
            failures[tk] = rec
    failures = {t: r for t, r in failures.items() if t in universe_set}
    _save_failures(failures_path, failures)
    if batch:
        print(f"Beschafft: {len(fresh)}/{len(batch)} "
              f"({len(batch) - len(fresh)} Ausfälle, jetzt {len(failures)} Titel "
              f"in der Fehlerliste)", flush=True)

    cache.update(fresh)
    if len(universe_set) >= max(100, len(cache) // 2):
        cache = {t: s for t, s in cache.items() if t in universe_set}
    elif cache:
        print(f"Universe verdächtig klein ({len(universe_set)}) — Cache NICHT "
              f"beschnitten, {len(cache)} Werte behalten.", flush=True)

    if not cache:
        print("Cache leer (alles gedrosselt?) — DB bleibt unverändert.",
              file=sys.stderr, flush=True)
        raise SystemExit(1)

    # CHECKPOINT: Der Snapshot-Cache wird HIER gesichert, nicht erst am Ende.
    # Die Beschaffung ist der mit Abstand teuerste Schritt (Netz, Drosselung,
    # Minuten bis Stunden); Forecast, Pipeline und DB-Schreiben sind billig und
    # rein lokal. Lag der Save am Ende, warf jeder Fehler danach die gesamte
    # Beschaffung weg — real passiert am 2026-09-06: ein Fehler in der
    # Pipeline-Phase vernichtete 4906 frisch geholte Snapshots, der nächste
    # Lauf hätte alles erneut holen müssen. Jetzt ist der Lauf ab hier
    # wiederaufsetzbar: Ein Neustart findet die Daten vor und überspringt die
    # Beschaffung (sie gelten als frisch).
    _save_cache(cache_path, cache)
    print(f"Checkpoint: {len(cache)} Snapshots gesichert — ein Abbruch ab hier "
          f"kostet keine erneute Beschaffung.", flush=True)

    print(f"Forecast-Band für {len(cache)} Werte rechnen (statistical, torch-frei) …",
          flush=True)
    with metrics.phase("forecast"):
        forecaster = build_forecaster("statistical")
        await apply_forecasts(forecaster, cache, horizon=args.horizon)
        if hasattr(forecaster, "aclose"):
            await forecaster.aclose()

    # Indikator-Felder zaehlen: sagt aus, wie dicht die Datenlage wirklich ist.
    metrics.universe_scored = len(cache)
    metrics.indicators_computed = sum(
        len(getattr(s_, "technicals", {}) or {}) for s_ in cache.values())

    print(f"Pipeline über {len(cache)} Werte rechnen (cross-sectional) …", flush=True)
    engine = create_engine()                       # DATABASE_URL -> Neon Postgres (oder anderer Anbieter)
    attach_db_counter(engine, metrics)              # zaehlt Roundtrips zur DB
    await init_models(engine)                       # idempotent; Produktions-Schema via Alembic
    sm = create_session_factory(engine)
    repo = ScreenerRepository(engine)
    with metrics.phase("pipeline"):
        async with sm() as session:
            res = await run_screener_pipeline(list(cache), session, repository=repo,
                                              snapshots=cache, commit=True,
                                              metrics=metrics)
    metrics.rows_written = res.processed
    for tk, msg in res.errors.items():
        metrics.note_error(tk, msg)

        # Waisen: Zeilen, die nicht mehr im Universum sind und deren Daten alt
        # sind. Sie werden nie wieder beschrieben und verfälschen den
        # ausgewiesenen „ältesten Stand". Standardmäßig wird nur BERICHTET —
        # Löschen ist irreversibel und braucht --prune-orphans.
        try:
            orphans = await repo.find_orphans(session, universe_set,
                                              older_than_days=args.orphan_age)
        except Exception as exc:
            orphans = []
            print(f"Waisen-Prüfung fehlgeschlagen: {exc}", flush=True)
        if orphans:
            share = len(orphans) / max(len(cache), 1)
            print(f"Waisen: {len(orphans)} Zeilen nicht mehr im Universum und "
                  f"älter als {args.orphan_age} Tage (z. B. {', '.join(orphans[:8])})",
                  flush=True)
            if not args.prune_orphans:
                print("  -> nur gemeldet. Löschen mit --prune-orphans.", flush=True)
            elif share > 0.2:
                # Ein kaputtes/verkürztes Universum darf niemals die halbe
                # Tabelle mitreißen — dieselbe Vorsicht wie beim Cache-Beschnitt.
                print(f"  -> ABGELEHNT: {share:.0%} der Zeilen betroffen, das "
                      f"sieht nach kaputtem Universum aus. Nichts gelöscht.",
                      flush=True)
            else:
                n_del = await repo.delete_rows(session, orphans)
                await session.commit()
                print(f"  -> {n_del} Waisen gelöscht.", flush=True)
    await engine.dispose()

    _save_cache(cache_path, cache)

    stamps = [getattr(s, "as_of", None) for s in cache.values() if getattr(s, "as_of", None)]
    oldest = min(stamps) if stamps else "—"
    newest = max(stamps) if stamps else "—"
    print(f"FERTIG: {res.processed} in DB geschrieben ({len(fresh)} neu beschafft), "
          f"Stand ältester {oldest} … neuester {newest}, {time.monotonic() - t0:.0f}s",
          flush=True)

    # Lauf-Kennzahlen festhalten. Ohne sie ist "ist der Screener heute sauber
    # gelaufen?" nicht beantwortbar — bisher gab es nur die Zeilenzahl.
    report = metrics.write(cache_path.with_name("last_run.json"))
    print(metrics.summary(), flush=True)
    if report["errors"]["total"]:
        print("Fehler nach Ursache:", flush=True)
        for kind, n in report["errors"]["by_kind"].items():
            print(f"  {n:>5}x  {kind}  —  z.B. {report['errors']['samples'][kind]}",
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())
