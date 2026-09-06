"""Pydantic-V2-Antwortschemata für die Lese-Schicht.

Die Schemata bilden `ScreenerRowModel` exakt ab und validieren die drei
JSONB-Felder (`targets`, `drivers`, `strategy_tags`) strukturiert. Konstruktion
erfolgt direkt aus dem ORM-Objekt (`from_attributes=True`); die JSONB-Dicts
werden dabei in die geschachtelten Modelle hineinvalidiert.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TargetsSchema(BaseModel):
    """Handelbare Level + Chance (JSONB-Spalte `targets`)."""
    model_config = ConfigDict(extra="ignore")

    signal_aggr: float | None = None
    signal_kons: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    crv: float | None = None
    chance: float | None = None
    chance_dots: int | None = None
    forecast_return: float | None = None      # erwartete Rendite bis Prognose-Ende
    forecast_method: str | None = None         # "statistical" | "kronos"


class DriverSchema(BaseModel):
    """Ein einzelner Bull-/Bear-Treiber."""
    model_config = ConfigDict(extra="ignore")

    code: str
    polarity: str
    magnitude: float
    statement: str


class ZoneSchema(BaseModel):
    """Eine Konfluenzzone (für das Tearsheet)."""
    model_config = ConfigDict(extra="ignore")

    center: float
    low: float
    high: float
    strength: float
    kind: str
    categories: list[str] = Field(default_factory=list)
    explain: str | None = None
    is_entry: bool = False


class DriversSchema(BaseModel):
    """Begründungen + Zonen-Konfluenzen (JSONB-Spalte `drivers`)."""
    model_config = ConfigDict(extra="ignore")

    bull: list[DriverSchema] = Field(default_factory=list)
    bear: list[DriverSchema] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    status_note: str | None = None
    zones: list[ZoneSchema] = Field(default_factory=list)


class ForecastPoint(BaseModel):
    """Ein Kronos-Inferenzpunkt der 30-Tage-Prognose."""
    model_config = ConfigDict(extra="ignore")

    timestamp: str
    mean: float
    upper: float
    lower: float


class ScoreComponentSchema(BaseModel):
    """Ein Faktor der Score-Aufschlüsselung."""
    model_config = ConfigDict(extra="ignore")

    slug: str
    label: str
    score: float                 # 0..100
    weight: float                # Anteil am Composite
    contribution: float          # Beitrag in Punkten
    state: str | None = None
    available: bool = True       # False = keine Daten, floss NICHT ein


class DataQualitySchema(BaseModel):
    """Woraus die Datengrundlage besteht — und was ihr fehlt."""
    model_config = ConfigDict(extra="ignore")

    score: int | None = None
    label: str | None = None
    components: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    bars: int | None = None
    age_days: float | None = None


class ScoreBreakdownSchema(BaseModel):
    """Warum dieser Gesamtscore? (JSONB-Spalte `score_breakdown`)"""
    model_config = ConfigDict(extra="ignore")

    data_quality: DataQualitySchema | None = None

    technical: list[ScoreComponentSchema] = Field(default_factory=list)
    fundamental: list[ScoreComponentSchema] = Field(default_factory=list)
    signal_strength: str | None = None
    confirming: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    coverage: float | None = None       # Anteil des Gewichts mit echten Daten
    note: str | None = None


class ScreenerRowSchema(BaseModel):
    """Tabellenzeile für das Dashboard (ein Instrument)."""
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str | None = None
    sector: str | None = None
    country: str | None = None
    asset_class: str | None = None
    price: float | None = None
    currency: str | None = None
    dividend_yield: float | None = None

    strategy_tag: str | None = None
    strategy_tags: list[str] = Field(default_factory=list)

    status: str | None = None
    rating: str | None = None
    wlatar: int | None = None
    wlafar: int | None = None
    total_score: int | None = None      # Gesamtrating 0..100

    trend_long: str | None = None
    trend_medium: str | None = None
    risikoklasse: str | None = None
    chance_rarity: str | None = None
    data_as_of: str | None = None        # Stand der Daten dieses Werts (ISO)
    # Wie viele unabhängige Faktoren sich bestätigen (stark/moderat/schwach).
    # In der Liste, weil danach gefiltert und sortiert wird; die vollständige
    # Aufschlüsselung steckt nur in der Detailsicht (Payload-Gewicht).
    signal_strength: str | None = None
    # Belastbarkeit der Datengrundlage (0..100) samt Kurzlabel. In der Liste,
    # damit ein Score aus Bruchstücken nicht wie ein vollständiger wirkt.
    data_quality: int | None = None
    data_quality_label: str | None = None

    targets: TargetsSchema = Field(default_factory=TargetsSchema)
    updated_at: datetime | None = None


class ScreenerRowDetailSchema(ScreenerRowSchema):
    """Volle Detailsicht inkl. Begründungen, Konfluenzzonen und Kronos-Prognose."""

    drivers: DriversSchema = Field(default_factory=DriversSchema)
    forecast_history: list[ForecastPoint] = Field(default_factory=list)
    price_history: list[float] = Field(default_factory=list)
    score_breakdown: ScoreBreakdownSchema = Field(default_factory=ScoreBreakdownSchema)


class ScreenerListResponse(BaseModel):
    """Pagination-Hülle: `1–10 of 1 234` lässt sich daraus direkt rendern."""

    items: list[ScreenerRowSchema]
    total: int
    limit: int
    offset: int


class FacetsResponse(BaseModel):
    """Distinct-Werte für die Filter-Dropdowns (dynamisch aus dem Universum)."""

    sectors: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    risk_classes: list[str] = Field(default_factory=list)
    ratings: list[str] = Field(default_factory=list)
    total: int = 0


class NewsItem(BaseModel):
    """Eine Nachricht zu einem Instrument."""
    model_config = ConfigDict(extra="ignore")

    title: str
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    snippet: str | None = None
    image: str | None = None


class NewsResponse(BaseModel):
    ticker: str
    items: list[NewsItem] = Field(default_factory=list)
    note: str | None = None          # z.B. Hinweis, wenn kein FMP-Key gesetzt ist


class SummaryResponse(BaseModel):
    """Marktbreite der gefilterten Menge (für das Übersichts-Band)."""
    total: int = 0
    avg_total_score: float | None = None
    by_rating: dict[str, int] = Field(default_factory=dict)
    # Datenabdeckung (rollierender Batch-Sync): ältester/neuester data_as_of
    # über die gefilterte Menge — zeigt die Frische des zuletzt berechneten Stands.
    oldest_data_as_of: str | None = None
    newest_data_as_of: str | None = None
