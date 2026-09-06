"""FastAPI-App-Factory für die Screener-Lese-Schicht."""
from __future__ import annotations

import os

import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .dependencies import make_lifespan
from .routes import router


# Pfade, die auch ohne Schlüssel erreichbar bleiben: Monitoring und die
# OpenAPI-Oberfläche (letztere gibt keine Marktdaten preis).
_OPEN_PATHS = frozenset({"/health", "/", "/docs", "/redoc", "/openapi.json"})


def _install_access_key(app: FastAPI) -> None:
    """Schützt die Lese-Endpunkte mit einem geteilten Schlüssel.

    Warum überhaupt: Das Frontend ist per Passwort-Cookie geschützt, das
    Backend läuft aber als EIGENES, öffentlich erreichbares Vercel-Projekt.
    Ein direkter Aufruf der Backend-URL umging den Passwortschutz damit
    vollständig — ein `curl` auf /api/v1/screener lieferte ohne jede
    Anmeldung das gesamte Universum. Der Schutz vorne war rein kosmetisch.

    Der Schlüssel wird NUR geprüft, wenn API_ACCESS_KEY gesetzt ist. Das ist
    Absicht: So lassen sich Frontend und Backend nacheinander umstellen, ohne
    dass die Live-Seite zwischendurch aussperrt. Ohne die Variable verhält
    sich die API exakt wie bisher.
    """
    expected = os.getenv("API_ACCESS_KEY", "").strip()
    if not expected:
        return

    @app.middleware("http")
    async def require_key(request: Request, call_next):
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)
        # compare_digest statt == : verhindert, dass die Antwortzeit
        # zeichenweise verrät, wie weit ein geratener Schlüssel stimmt.
        got = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(got, expected):
            return JSONResponse({"detail": "Nicht autorisiert"}, status_code=401)
        return await call_next(request)


def _cors_origins() -> list[str]:
    """Erlaubte Origins aus CORS_ORIGINS (Komma-separiert; Default localhost:3000)."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app(database_url: str | None = None, *, create_schema: bool | None = None) -> FastAPI:
    # Schema-Anlage beim Start optional über Env (bequemes lokales SQLite-Testen
    # ohne Alembic). In Produktion: SCREENER_CREATE_SCHEMA ungesetzt -> Migrationen.
    if create_schema is None:
        create_schema = os.getenv("SCREENER_CREATE_SCHEMA", "").lower() in ("1", "true", "yes")

    app = FastAPI(
        title="Louichamp Screener API",
        version="1.0.0",
        summary="Lese-Schicht: Screener-Tabelle, Filter, Sortierung, Tearsheet.",
        lifespan=make_lifespan(database_url, create_schema=create_schema),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    _install_access_key(app)
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness + DB-Readiness: pingt die Datenbank (SELECT 1)."""
        sessionmaker = getattr(app.state, "sessionmaker", None)
        if sessionmaker is None:
            return {"status": "starting", "db": "unknown"}
        try:
            async with sessionmaker() as session:
                await session.execute(text("SELECT 1"))
            return {"status": "ok", "db": "ok"}
        except Exception as exc:                   # DB nicht erreichbar -> degraded
            return {"status": "degraded", "db": f"error: {exc.__class__.__name__}"}

    return app


# Produktions-Einstieg: `uvicorn api.main:app` (DATABASE_URL aus der Umgebung).
app = create_app()
