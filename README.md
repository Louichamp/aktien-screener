# LOUICHAMP SCREENER

Aktien-Research-Screener (kein Trading-Bot): technische + fundamentale Analyse
plus Kronos-Prognose, skaliert auf **5.000+ Instrumente** mit kostenloser
Yahoo-Datenanbindung. Stack: FastAPI · PostgreSQL/TimescaleDB (JSONB+GIN) ·
arq/Redis · Next.js (App Router, Tailwind) · Kronos (PyTorch).

```
scoring/         Plugin-basierte Score-Engine
screener/        Zonen-/Level-Engine, Status, Strategien, Pipeline
infrastructure/  DB (models/config/repository), providers (FMP), forecast (Kronos), worker
api/             FastAPI-Lese-Schicht (Filter/Sort/Pagination + Tearsheet-Detail)
alembic/         Migrationen (GIN-/B-Tree-Indizes)
frontend/        Next.js-Dashboard + Tearsheet
scripts/         seed_dev.py (Demodaten), start_prod.py (Prod-Start)
```

## 🌐 Online stellen (Netlify, kostenlos) — statische Seite

Das Frontend kann als **reine statische Seite** laufen, die ihre Daten aus
exportierten JSON-Dateien liest — **kein Server/keine DB online nötig**, perfekt
für Netlifys Gratis-Tier und vom Handy aus erreichbar.

```powershell
# 1) Daten lokal beschaffen — rollierend, "alles durchballern" (volles Universum):
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
.\.venv\Scripts\python.exe scripts\rotating_sync.py --cache .cache\snapshots.pkl `
    --refresh all --limit 5000 --source broad
#    --refresh all = alles neu; oder z.B. --refresh 1500 = nur die 1500 ältesten

# 2) Exportieren + statisch bauen in EINEM Befehl
.\.venv\Scripts\python.exe scripts\build_site.py
#    --with-news  hängt Live-News je Ticker an (langsamer; nur kleine Universen)

# 3) Hochladen: den erzeugten Ordner  frontend\out  auf
#    https://app.netlify.com/drop  ziehen  → fertig, öffentliche URL.
```

**Rollierendes Modell:** Der `rotating_sync` hält einen Snapshot-Cache, frischt
die **ältesten** Werte zuerst auf und rechnet immer das **gesamte angesammelte
Universum** durch — es wird also stets so viel angezeigt wie verfügbar (nie
nichts), und jeder Wert trägt seinen eigenen **„Stand"** (Alter). Wird Yahoo
gedrosselt, kommen halt weniger neue dazu; der Rest bleibt mit älterem Stand
sichtbar.

**Aktualisieren = Schritte 1–3 wiederholen** (oder nur 2–3, wenn die DB schon
aktuell ist) und neu hochladen. Beim Neuladen der Seite zieht der Browser die
neue JSON (Cache-Bust eingebaut). Alternativ den Ordner per Git an Netlify
anbinden (`netlify.toml` ist dabei) — dann baut Netlify bei jedem Push selbst;
dafür müssen die Daten unter `frontend/public/data/` mit eingecheckt sein.

> Lokal genauso testen: `cd frontend && npm run dev` (liest dieselben
> `public/data`-JSONs). Der FastAPI-Server wird für die statische Seite nicht
> mehr gebraucht (bleibt aber für den „Live-Modus" erhalten).

## 🤖 Vollautomatisch jeden Morgen (GitHub Actions → Netlify)

Damit sich die Seite **ohne PC** täglich selbst aktualisiert: Der Workflow
[.github/workflows/daily-update.yml](.github/workflows/daily-update.yml) holt
werktags früh die Daten, baut die Seite und deployt sie zu Netlify. Danach
zeigt jedes Neuladen (auch am Handy) den frischen Stand.

**Einmalige Einrichtung (~5 Min):**
1. **Netlify-Site anlegen** (falls noch nicht): einmal lokal
   `python scripts/build_site.py` und den Ordner `frontend/out` auf
   <https://app.netlify.com/drop> ziehen → Site existiert.
2. **Netlify-Werte holen:** Site-Einstellungen → *Site ID* (= API ID) notieren;
   unter Netlify *User settings → Applications → Personal access tokens* einen
   **Token** erstellen.
3. **Projekt zu GitHub pushen** (Repo anlegen, `git init`, commit, push).
4. **GitHub-Repo → Settings → Secrets and variables → Actions** zwei Secrets
   anlegen:
   - `NETLIFY_AUTH_TOKEN` = der Token aus Schritt 2
   - `NETLIFY_SITE_ID` = die Site-ID aus Schritt 2
5. Fertig. Der Workflow läuft ab jetzt **werktags 07:00 UTC** (≈ 9 Uhr DE-Sommer,
   8 Uhr Winter) — und jederzeit manuell über *Actions → Daily Screener Update →
   Run workflow* (dort lassen sich `limit`/`source` setzen).

**Uhrzeit ändern:** in der Workflow-Datei die `cron`-Zeile anpassen (UTC!).
Beispiele: `0 6 * * 1-5` = 8/7 Uhr DE, `0 21 * * 1-5` = kurz nach US-Börsenschluss.

> Rollierend: Der CI-Lauf nutzt `rotating_sync` mit einem **persistenten
> Snapshot-Cache** (GitHub-Actions-Cache). Jeder Lauf frischt die ältesten
> `SCREENER_REFRESH` (Default 1500) Werte des `SCREENER_LIMIT`-Universums
> (Default 5000, broad) auf und deployt das gesamte angesammelte Set. So füllt
> sich über wenige Tage das volle Universum und rotiert dann durch — **nie wird
> nichts angezeigt**. Den kompletten Sofort-Refresh machst du lokal mit
> `rotating_sync.py --refresh all` + `build_site.py --deploy`.

## Schnelltest lokal (ohne Postgres/Redis/FMP/GPU)

Alles läuft gegen SQLite; FMP/Kronos werden nicht benötigt.

```powershell
# 1) venv + Abhängigkeiten (Test-/API-Teil reicht; torch etc. NICHT nötig)
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install "sqlalchemy[asyncio]>=2.0" fastapi "uvicorn[standard]" `
    pydantic aiosqlite httpx arq alembic python-dotenv pytest pytest-asyncio

# 2) Tests
.\.venv\Scripts\python.exe -m pytest -q

# 3) Demodaten + API starten (SQLite, Schema wird automatisch angelegt)
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
.\.venv\Scripts\python.exe scripts\seed_universe.py --count 1000   # 1.000 Instrumente
#   (oder scripts\seed_dev.py für ein kleines, kuratiertes Set)
$env:SCREENER_CREATE_SCHEMA = "1"          # legt Tabellen beim Start an (nur Dev)
.\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
#   -> http://localhost:8000/health           {"status":"ok","db":"ok"}
#   -> http://localhost:8000/docs              (Swagger; alle Filter sichtbar)
#   -> http://localhost:8000/api/v1/screener?sector=Technologie&min_total_score=70
#   -> http://localhost:8000/api/v1/screener/facets   (Filter-Werte)

# 4) Frontend
cd frontend
npm install
"NEXT_PUBLIC_API_BASE=http://localhost:8000" | Out-File -Encoding utf8 .env.local
npm run dev                                 # http://localhost:3000
```

## Produktion

`.env` aus `.env.example` ableiten (DATABASE_URL=postgres, REDIS_URL, FMP_API_KEY,
KRONOS_*, WATCHLIST). Dann:

```bash
pip install -r requirements.txt            # inkl. torch (ggf. CUDA-Index-URL)
python scripts/start_prod.py --migrate     # Alembic + 3 arq-Worker + uvicorn
```

### Echte Daten – KOSTENLOS über Yahoo Finance (empfohlen)

Kein API-Key nötig. Ein Lauf holt das Universum (S&P 500 + NASDAQ/NYSE) und
rechnet die komplette Pipeline durch (cross-sectional), inkl. echter Namen,
Branchen, Preise, Dividenden und Scores:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
.\.venv\Scripts\python.exe scripts\run_yahoo_universe.py --limit 1000 --source broad
#   --source sp500       nur der saubere S&P-500-Kern (mit Branche)
#   --no-fundamentals    nur Technik (sehr schnell für riesige Universen)
#   --no-forecast        Forecast-Band überspringen
#   --forecast-backend kronos   echtes Kronos statt statistisch (braucht torch)
# Danach: API + Frontend starten -> echte Daten + Forecast-Band, Live-News im Tearsheet.
```

Das **Forecast-Band** rechnet standardmäßig der statistische GBM-Forecaster
(`FORECAST_BACKEND=statistical`, gratis, kein torch): Drift μ + Vola σ aus der
echten Kurshistorie → log-normaler Konfidenzkanal pro Titel. Mit
`FORECAST_BACKEND=kronos` (torch + Modell nötig) wird stattdessen das echte
Kronos-KI-Modell genutzt — gleiche Schnittstelle. Der Tearsheet zeigt einen
durchgängigen „Kursverlauf → Prognose"-Chart (echte Historie → Kegel).

`DATA_PROVIDER=yahoo` (Default) gilt auch für Worker und News-Endpunkt — News
kommen ohne Key live von Yahoo. Für sehr große Universen dauert der Lauf länger
(~1 HTTP/Titel für Fundamentaldaten; Yahoo wird gedrosselt abgefragt).

### Alternativ: Financial Modeling Prep (Key nötig, limitiert)

```bash
# Stammdaten via FMP (DATA_PROVIDER=fmp), ~600 Ticker:
FMP_API_KEY=... python scripts/seed_real_universe.py --indices sp500 nasdaq
```

Der Orchestrator (`screener_run`) verarbeitet das Universum in Batches
(`SCREENER_BATCH_SIZE`, Default 50): Ingest/Forecast laufen als parallele
Sub-Jobs, gedrosselt vom geteilten FMP-Rate-Limiter (keine 429). Der
compute-Schritt bleibt bewusst universumsweit (cross-sectional Scoring).
News werden pro Ticker `NEWS_CACHE_TTL` Sekunden (Default 300) gecacht.

Migrationen separat: `alembic upgrade head` (nicht `python -m alembic`).
DDL-Vorschau für Postgres: `alembic upgrade head --sql`.

## Tests

`pytest -q` — deckt API (Filter/Sort/Pagination/Detail), den DB-Push-down,
die Kronos-Worker-Kette (inkl. Retry/Degradation) und die FMP-/Indikator-Logik ab.
