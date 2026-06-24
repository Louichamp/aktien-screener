"""Echte Kronos-Inferenz (PyTorch/Transformers) auf OHLCV-Kerzen.

Kronos (AAAI 2026, MIT) ist ein Foundation-Modell für Candlestick-Reihen:
Tokenizer + autoregressiver Transformer. Diese Klasse lädt Tokenizer + Modell
EINMAL (warm im forecast-Worker) und erzeugt eine 30-Tage-Prognose. Da das
Modell autoregressiv samplet, wird das Konfidenzintervall aus mehreren Sampling-
Durchläufen geschätzt (Mittelwert ± z·Std bzw. Perzentile der Close-Pfade).

Schwere Importe (torch, pandas, numpy, Kronos-Klassen) erfolgen LAZY, damit das
Paket auch ohne installiertes Torch importierbar bleibt (Tests/CI/Lese-API).

Konfiguration (Umgebung):
  KRONOS_MODEL_ID        HF-Repo/Pfad des Modells (Default NeoQuasar/Kronos-small)
  KRONOS_TOKENIZER_ID    HF-Repo/Pfad des Tokenizers (Default NeoQuasar/Kronos-Tokenizer-base)
  KRONOS_DEVICE          z.B. "cuda:0" oder "cpu" (Default: cuda falls verfügbar)
  KRONOS_MAX_CONTEXT     Kontextlänge (Default 512)
  KRONOS_LOOKBACK        Anzahl historischer Kerzen als Input (Default 400)
  KRONOS_SAMPLES         Sampling-Durchläufe für das Band (Default 30)
  KRONOS_TOP_P / KRONOS_TEMP   Sampling-Parameter (Default 0.9 / 1.0)
  KRONOS_CONFIDENCE_Z    Bandbreite in Std (Default 1.28 ≈ 80 %)
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from screener.pipeline import MarketSnapshot

log = logging.getLogger("screener.forecast.kronos")


def _load_kronos_classes():
    """Importiert die Kronos-Klassen; tolerant gegenüber Paket-Layout."""
    try:                                  # offizielles Repo: `model`-Modul
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
        return Kronos, KronosTokenizer, KronosPredictor
    except ImportError:
        from kronos import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
        return Kronos, KronosTokenizer, KronosPredictor


class KronosForecaster:
    """Warm gehaltenes Kronos-Modell mit `forecast(snapshot, horizon)`-Schnittstelle."""

    def __init__(self, *, model_id: str | None = None, tokenizer_id: str | None = None,
                 device: str | None = None, max_context: int | None = None,
                 lookback: int | None = None, samples: int | None = None,
                 top_p: float | None = None, temperature: float | None = None,
                 confidence_z: float | None = None) -> None:
        import torch  # lazy

        Kronos, KronosTokenizer, KronosPredictor = _load_kronos_classes()

        self.lookback = lookback or int(os.getenv("KRONOS_LOOKBACK", "400"))
        self.samples = samples or int(os.getenv("KRONOS_SAMPLES", "30"))
        self.top_p = top_p if top_p is not None else float(os.getenv("KRONOS_TOP_P", "0.9"))
        self.temperature = (temperature if temperature is not None
                            else float(os.getenv("KRONOS_TEMP", "1.0")))
        self.confidence_z = (confidence_z if confidence_z is not None
                            else float(os.getenv("KRONOS_CONFIDENCE_Z", "1.28")))
        device = device or os.getenv(
            "KRONOS_DEVICE", "cuda:0" if torch.cuda.is_available() else "cpu")
        max_context = max_context or int(os.getenv("KRONOS_MAX_CONTEXT", "512"))

        tok_id = tokenizer_id or os.getenv("KRONOS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
        mdl_id = model_id or os.getenv("KRONOS_MODEL_ID", "NeoQuasar/Kronos-small")
        log.info("Lade Kronos: model=%s tokenizer=%s device=%s", mdl_id, tok_id, device)

        tokenizer = KronosTokenizer.from_pretrained(tok_id)
        model = Kronos.from_pretrained(mdl_id)
        self.predictor = KronosPredictor(model, tokenizer, device=device, max_context=max_context)
        self.device = device

    # ------------------------------------------------------------------ #
    def _frame(self, snap: MarketSnapshot):
        """Kerzen -> (DataFrame[OHLCV], x_timestamps) für die letzten `lookback` Bars."""
        import pandas as pd  # lazy

        candles = snap.candles[-self.lookback:]
        if len(candles) < 2:
            raise ValueError("zu wenige Kerzen für Kronos-Inferenz")
        df = pd.DataFrame({
            "open": [c.o for c in candles], "high": [c.h for c in candles],
            "low": [c.l for c in candles], "close": [c.c for c in candles],
            "volume": [c.v for c in candles],
        })
        # Synthetische Tagesstempel (echte Daten sind in den Candles nicht enthalten).
        # tz-naiv + normalisiert; pd.Timestamp.utcnow() ist in pandas 2.x deprecated.
        end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        x_ts = pd.date_range(end=end, periods=len(candles), freq="B")
        return df, pd.Series(x_ts)

    async def forecast(self, snap: MarketSnapshot, *, horizon: int = 30) -> dict[str, Any]:
        """Erzeugt mean_path/upper_band/lower_band/timestamps für `horizon` Tage.

        Die eigentliche (blockierende, GPU-lastige) Inferenz läuft in einem
        Thread-Executor, damit der arq-Event-Loop nicht blockiert.
        """
        import asyncio

        return await asyncio.to_thread(self._forecast_sync, snap, horizon)

    def _forecast_sync(self, snap: MarketSnapshot, horizon: int) -> dict[str, Any]:
        import numpy as np  # lazy
        import pandas as pd  # lazy

        df, x_ts = self._frame(snap)
        y_ts = pd.Series(pd.date_range(start=x_ts.iloc[-1] + timedelta(days=1),
                                       periods=horizon, freq="B"))

        # Mehrere Sampling-Durchläufe -> Verteilung der Close-Pfade -> Band.
        close_paths: list[list[float]] = []
        for _ in range(max(1, self.samples)):
            pred = self.predictor.predict(
                df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=horizon,
                T=self.temperature, top_p=self.top_p, sample_count=1, verbose=False)
            close_paths.append([float(v) for v in pred["close"].tolist()])

        arr = np.asarray(close_paths, dtype=float)        # (samples, horizon)
        mean = arr.mean(axis=0)
        std = arr.std(axis=0)
        upper = mean + self.confidence_z * std
        lower = mean - self.confidence_z * std
        direction = "up" if mean[-1] >= float(snap.price) else "down"

        return {
            "timestamps": [d.date().isoformat() for d in y_ts],
            "mean_path": [round(float(v), 4) for v in mean],
            "upper_band": [round(float(v), 4) for v in upper],
            "lower_band": [round(float(v), 4) for v in lower],
            "direction": direction,
        }
