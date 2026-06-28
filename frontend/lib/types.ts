// Spiegelt die Pydantic-Schemata der FastAPI-Lese-Schicht (api/schemas.py).

export interface Targets {
  signal_aggr: number | null;
  signal_kons: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  crv: number | null;
  chance: number | null;
  chance_dots: number | null;
  forecast_return: number | null;
  forecast_method: string | null;
}

export interface Driver {
  code: string;
  polarity: "positive" | "negative" | string;
  magnitude: number;
  statement: string;
}

export interface Zone {
  center: number;
  low: number;
  high: number;
  strength: number;
  kind: "support" | "resistance" | "neutral" | string;
  categories: string[];
  explain: string | null;
  is_entry: boolean;
}

export interface Drivers {
  bull: Driver[];
  bear: Driver[];
  rationale: string[];
  status_note: string | null;
  zones: Zone[];
}

export interface ScreenerRow {
  ticker: string;
  name: string | null;
  sector: string | null;
  country: string | null;
  asset_class: string | null;
  price: number | null;
  currency: string | null;
  dividend_yield: number | null;
  strategy_tag: string | null;
  strategy_tags: string[];
  status: string | null;
  rating: string | null;
  wlatar: number | null;
  wlafar: number | null;
  total_score: number | null;
  trend_long: string | null;
  trend_medium: string | null;
  risikoklasse: string | null;
  chance_rarity: string | null;
  data_as_of: string | null;
  targets: Targets;
  updated_at: string | null;
}

export interface Facets {
  sectors: string[];
  countries: string[];
  asset_classes: string[];
  statuses: string[];
  strategies: string[];
  risk_classes: string[];
  ratings: string[];
  total: number;
}

export interface NewsItem {
  title: string;
  url: string | null;
  source: string | null;
  published_at: string | null;
  snippet: string | null;
  image: string | null;
}

export interface NewsResponse {
  ticker: string;
  items: NewsItem[];
  note: string | null;
}

export interface Summary {
  total: number;
  avg_total_score: number | null;
  by_rating: Record<string, number>;
}

export interface ForecastPoint {
  timestamp: string;
  mean: number;
  upper: number;
  lower: number;
}

export interface ScreenerRowDetail extends ScreenerRow {
  drivers: Drivers;
  forecast_history: ForecastPoint[];
  price_history: number[];
  news?: NewsItem[];          // optional vom Export mitgeliefert (--with-news)
}

export interface ScreenerListResponse {
  items: ScreenerRow[];
  total: number;
  limit: number;
  offset: number;
}

export type SortBy =
  | "ticker" | "name" | "sector" | "country" | "price" | "dividend_yield"
  | "wlatar" | "wlafar" | "total_score" | "rating" | "status" | "strategy"
  | "risk_class" | "data_as_of" | "updated_at" | "chance_dots";
export type SortDir = "asc" | "desc";

export interface ScreenerQuery {
  search?: string;
  strategy?: string;
  risk_class?: string;
  sector?: string;
  country?: string;
  asset_class?: string;
  status?: string;
  rating?: string;
  trend_long?: string;
  trend_medium?: string;
  min_total_score?: number;
  min_wlatar?: number;
  min_wlafar?: number;
  min_dividend_yield?: number;
  max_risk_level?: number;
  tickers?: string;
  rare_only?: boolean;
  sort_by?: SortBy;
  sort_dir?: SortDir;
  limit?: number;
  offset?: number;
}

export const RISK_CLASSES = [
  "sehr niedrig", "niedrig", "mittel", "hoch", "sehr hoch",
] as const;
export const TRENDS = ["AUFWÄRTS", "NEUTRAL", "ABWÄRTS"] as const;
