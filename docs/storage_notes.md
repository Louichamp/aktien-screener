# Storage-Strategie für den Postgres Free Tier (~0.5 GB)

**Provider-Update (2026-07-12):** Timescale Cloud bietet keinen dauerhaft
kostenlosen Tarif mehr (nur ein 29-Tage-Trial mit $1.000 Guthaben, danach ab
$30/Monat). Die DB läuft daher auf **Neon** (echter, dauerhaft kostenloser
Postgres-Tarif, 0.5 GB, keine Kreditkarte nötig). Die komplette Argumentation
unten bleibt unverändert gültig — sie greift auf reines Postgres-Verhalten
zurück (Upsert-Tabelle, JSONB-Storage), nicht auf eine Timescale-spezifische
Erweiterung, die wir ohnehin nie gebraucht haben (s. u.).

## Warum TimescaleDB-Compression/Retention hier NICHT greifen

Compression-Policies und Retention-Policies sind Hypertable-Features für
**append-only Zeitreihendaten** (viele Zeilen über Zeit, alte Chunks werden
komprimiert oder gelöscht). `screener_rows` ist das Gegenteil: **eine Zeile pro
Ticker**, die bei jedem Batch-Lauf per Upsert überschrieben wird
(`ON CONFLICT (ticker) DO UPDATE`, siehe `infrastructure/database/repository.py`).
Nichts "altert" in dieser Tabelle — sie hat zu jedem Zeitpunkt exakt `#Ticker`
Zeilen, nicht mehr. Eine Compression-Policy hätte nichts zu komprimieren, eine
Retention-Policy nichts zu löschen (jede Zeile wird ja laufend neu geschrieben).

**Falls du sie trotzdem aktivieren willst** (z. B. weil Timescale Cloud es im
Dashboard anbietet) — schadet es nicht, bringt aber auch nichts:

```sql
-- Nur sinnvoll auf einer echten Zeitreihen-Hypertable (s. u.), NICHT auf
-- screener_rows selbst — SELECT create_hypertable('screener_rows', ...) würde
-- fehlschlagen bzw. wäre semantisch falsch (kein Zeitstempel-Partitionsschlüssel).
```

## Was tatsächlich Storage spart: JSONB-Payload begrenzen (umgesetzt)

Die einzigen unbegrenzt wachsenden Felder waren `price_history`,
`forecast_history` und `drivers.zones`. Alle drei sind jetzt gedeckelt:

| Feld | Vorher | Jetzt | Wo |
|---|---|---|---|
| `price_history` | unbegrenzt (alle Kerzen) | ≤ 120 Werte | `screener/pipeline.py:_price_history` (war bereits gecappt) |
| `forecast_history` | = Forecast-Horizont | ≤ 30 Einträge | `compute_scores.py --horizon 30` |
| `drivers.zones` | unbegrenzt (alle Konfluenzzonen) | ≤ 15 (stärkste zuerst) | `screener/pipeline.py:_build_drivers` (neu gedeckelt) |

## Zweiter, größerer Fund: ungenutzte GIN-Indizes entfernt

`api/queries.py` filtert **nie** über JSONB-Containment (`@>`, `?`) auf
`drivers`, `targets`, `forecast_history` oder `price_history` — es sind reine
Passthrough-Payloads fürs Tearsheet. Die vier GIN-Indizes darauf
(`ix_screener_rows_*_gin`) hatten daher **keinen Query-Nutzen**, aber GIN-Indizes
auf textlastigem JSONB sind oft **größer als die Daten selbst**. Entfernt in
Migration `0006_drop_unused_gin_indexes.py` — reiner Storage-Gewinn, keine
Query dieser Anwendung wird dadurch langsamer.

## Realistische Storage-Rechnung (nach den Caps)

Pro Zeile (`screener_rows`), grobe JSONB-Größe:

| Spalte | Inhalt | ≈ Bytes |
|---|---|---|
| `price_history` | ≤120 Floats | ~900 |
| `forecast_history` | ≤30 × {timestamp, mean, upper, lower} | ~2.100 |
| `drivers` | bull(5)+bear(5)+zones(≤15)+rationale | ~5.000 |
| `targets` | ~10 Floats/Strings | ~300 |
| Skalarspalten | name, sector, scores, etc. | ~300 |
| B-Tree-Indizes (13 Stück) | anteilig | ~500 |
| **Summe/Zeile** | | **~9 KB** |

Bei **5.250 Tickern**: `5.250 × 9 KB ≈ 47 MB` — weit unter dem 0.5 GB-Limit.
Selbst bei einer 5–10× großzügigeren Schätzung (Postgres-Overhead, TOAST,
WAL-Reste) bleibt das Universum bequem unter 250 MB. Storage ist bei diesem
Schema **kein realistisches Risiko** — die eigentlichen Limits liegen bei
Yahoo-Rate-Limits und GitHub-Actions-Minuten (siehe Kostenschätzung).

## Falls du später echte Zeitreihen willst (Trend-Charts über Wochen)

Dafür wäre eine **zusätzliche, echte Hypertable** der richtige Ort — z. B.
`score_history(ticker, ts, total_score, wlatar, wlafar)`, NICHT die vollen
JSONB-Blobs. Das ist Scope-Erweiterung (nicht Teil dieses Umbaus), aber falls
gewünscht, so würde man Compression + Retention dort korrekt aktivieren:

```sql
CREATE TABLE score_history (
    ticker       text NOT NULL,
    ts           timestamptz NOT NULL,
    total_score  int,
    wlatar       int,
    wlafar       int
);
SELECT create_hypertable('score_history', 'ts');

-- Nach 7 Tagen komprimieren (alte Chunks schreibgeschützt, ~10-20x kleiner)
ALTER TABLE score_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker'
);
SELECT add_compression_policy('score_history', INTERVAL '7 days');

-- Nach 180 Tagen löschen (Free-Tier-Storage-Deckel)
SELECT add_retention_policy('score_history', INTERVAL '180 days');
```
