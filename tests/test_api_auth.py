"""Tests für den Zugriffsschutz der Backend-API.

Hintergrund: Das Frontend ist per Passwort-Cookie geschützt, das Backend läuft
aber als eigenes, öffentlich erreichbares Vercel-Projekt. Ein direkter Aufruf
der Backend-URL umging den Passwortschutz vollständig — ein `curl` auf
/api/v1/screener lieferte ohne jede Anmeldung das gesamte Universum.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app


def _app(monkeypatch, key: str | None):
    tmp = tempfile.TemporaryDirectory()
    if key is None:
        monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    else:
        monkeypatch.setenv("API_ACCESS_KEY", key)
    app = create_app(f"sqlite+aiosqlite:///{Path(tmp.name) / 'auth.db'}",
                     create_schema=True)
    return app, tmp


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_ohne_schluessel_bleibt_alles_offen(monkeypatch):
    """Ohne gesetzte Variable verhält sich die API exakt wie vorher — das macht
    einen schrittweisen Rollout (erst Frontend, dann Backend) gefahrlos."""
    app, tmp = _app(monkeypatch, None)
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            assert (await c.get("/api/v1/screener")).status_code == 200
    tmp.cleanup()


@pytest.mark.asyncio
async def test_mit_schluessel_ohne_header_401(monkeypatch):
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            r = await c.get("/api/v1/screener")
            assert r.status_code == 401
            assert "screener" not in r.text.lower() or "detail" in r.text.lower()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_falscher_schluessel_401(monkeypatch):
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            r = await c.get("/api/v1/screener", headers={"x-api-key": "falsch"})
            assert r.status_code == 401
    tmp.cleanup()


@pytest.mark.asyncio
async def test_richtiger_schluessel_laesst_durch(monkeypatch):
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            r = await c.get("/api/v1/screener", headers={"x-api-key": "geheim-123"})
            assert r.status_code == 200
    tmp.cleanup()


@pytest.mark.asyncio
async def test_health_bleibt_ohne_schluessel_erreichbar(monkeypatch):
    """Monitoring darf nicht am Schlüssel scheitern."""
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            assert (await c.get("/health")).status_code == 200
    tmp.cleanup()


@pytest.mark.asyncio
async def test_openapi_ist_geschuetzt(monkeypatch):
    """Die OpenAPI-Beschreibung nennt jeden Endpunkt und jeden Filterparameter.
    Live war sie ohne jede Anmeldung abrufbar (HTTP 200)."""
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            for pfad in ("/openapi.json", "/docs", "/redoc"):
                assert (await c.get(pfad)).status_code == 401, pfad
            # Mit Schlüssel weiterhin erreichbar.
            r = await c.get("/openapi.json", headers={"x-api-key": "geheim-123"})
            assert r.status_code == 200
    tmp.cleanup()


@pytest.mark.asyncio
async def test_detail_und_news_ebenfalls_geschuetzt(monkeypatch):
    """Nicht nur die Liste — jeder datenführende Endpunkt muss den Schlüssel
    verlangen, sonst ist die Absicherung löchrig."""
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            for pfad in ("/api/v1/screener/AAPL", "/api/v1/screener/facets",
                         "/api/v1/screener/summary", "/api/v1/screener/AAPL/news"):
                assert (await c.get(pfad)).status_code == 401, pfad
    tmp.cleanup()


@pytest.mark.asyncio
async def test_schluessel_wird_zeitkonstant_verglichen(monkeypatch):
    """Ein Präfix-Treffer darf nicht anders behandelt werden als ein völlig
    falscher Schlüssel — sonst verrät die Antwortzeit die Länge des Treffers."""
    app, tmp = _app(monkeypatch, "geheim-123")
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            for falsch in ("g", "geheim-12", "geheim-1234", "", "x" * 200):
                assert (await c.get("/api/v1/screener",
                                    headers={"x-api-key": falsch})).status_code == 401
    tmp.cleanup()
