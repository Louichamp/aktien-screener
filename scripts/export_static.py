"""Exportiert den aktuellen DB-Stand als statische JSON-Dateien fürs Frontend.

Erzeugt unter `--out` (Default frontend/public/data):
  * screener.json          -> { generated_at, total, items[], facets }
  * detail/<TICKER>.json   -> vollständige Detailsicht je Instrument (Tearsheet)

Damit wird das Frontend zu einer reinen statischen Seite (Netlify-tauglich,
kostenlos): kein Live-Backend nötig. Workflow:

  1) Daten beschaffen:  python scripts/run_yahoo_universe.py --limit 1000 --source broad
  2) Exportieren:       python scripts/export_static.py
  3) Bauen + deployen:  cd frontend && npm run build   (-> out/ auf Netlify)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.database.config import create_engine, create_session_factory
from api.queries import ScreenerFilters, query_facets, query_screener_rows
from api.schemas import ScreenerRowDetailSchema, ScreenerRowSchema


def _sanitize(obj):
    """Ersetzt nicht-finite Floats (Infinity, -Infinity, NaN) rekursiv durch None.

    Python's json.dumps schreibt diese Werte standardmäßig als JavaScript-Token
    (Infinity, NaN), die gegen RFC 8259 verstoßen und im Browser einen SyntaxError
    auslösen. Diese Funktion ist die letzte Verteidigungslinie vor dem Schreiben;
    der eigentliche Fix liegt in den Provider-_f()-Funktionen.
    """
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _write_json(path: Path, data) -> None:
    clean = _sanitize(data)
    # allow_nan=False lässt json.dumps mit ValueError scheitern, falls _sanitize
    # doch einen Infinity/NaN-Wert übersehen hat — Fail-Fast statt stille Korruption.
    text = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "frontend" / "public" / "data"))
    ap.add_argument("--limit", type=int, default=100_000)
    ap.add_argument("--with-news", action="store_true",
                    help="Live-News je Ticker mitexportieren (langsam; nur kleine Universen)")
    args = ap.parse_args()

    out = Path(args.out)
    detail_dir = out / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)

    provider = None
    if args.with_news:
        from infrastructure.providers import build_market_data_provider
        provider = build_market_data_provider("yahoo")

    engine = create_engine()
    sm = create_session_factory(engine)
    async with sm() as s:
        rows, total = await query_screener_rows(
            s, ScreenerFilters(), sort_by="total_score", descending=True, limit=args.limit)
        facets = await query_facets(s)

    # Data-Safety: NIE einen leeren Stand schreiben (würde gute Daten überschreiben).
    if not rows:
        await engine.dispose()
        if provider is not None and hasattr(provider, "aclose"):
            await provider.aclose()
        print("FEHLER: 0 Instrumente in der DB — Export abgebrochen, vorhandene "
              "Daten bleiben erhalten.", file=sys.stderr)
        raise SystemExit(1)

    items = [ScreenerRowSchema.model_validate(r).model_dump(mode="json") for r in rows]
    screener_path = out / "screener.json"
    _write_json(screener_path, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": total, "items": items, "facets": facets,
    })
    # Automatische Validierung: bricht den Build ab, bevor korrupte Dateien deployt werden.
    try:
        json.loads(screener_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FEHLER: screener.json enthält ungültiges JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    # Alte Detail-Dateien aufräumen, dann frisch schreiben.
    for old in detail_dir.glob("*.json"):
        old.unlink()
    for r in rows:
        detail = ScreenerRowDetailSchema.model_validate(r).model_dump(mode="json")
        if provider is not None:
            try:
                detail["news"] = await provider.fetch_news(r.ticker, limit=10)
            except Exception:
                detail["news"] = []
        _write_json(detail_dir / f"{r.ticker}.json", detail)

    if provider is not None and hasattr(provider, "aclose"):
        await provider.aclose()
    await engine.dispose()
    print(f"export: {total} Instrumente -> {out}  (screener.json + {len(rows)} Detail-Dateien)")


if __name__ == "__main__":
    asyncio.run(main())
