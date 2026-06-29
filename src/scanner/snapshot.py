"""Atomic JSON snapshot writer for the Streamlit dashboard."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from scanner.state import CandleRow, StateStore

logger = logging.getLogger(__name__)


def _candle_to_dict(c: CandleRow) -> dict:
    return {
        "timestamp": c.timestamp,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
        "vwap": c.vwap,
    }


class SnapshotWriter:
    """Serialises the StateStore to a JSON file read by the Streamlit dashboard.

    Writes to a temporary file first then renames it so the dashboard never
    reads a partially-written file.
    """

    def __init__(self, store: StateStore, output_path: Path) -> None:
        self._store = store
        self._output_path = output_path
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self) -> None:
        """Write a complete snapshot of all candle series and latest signals."""
        candles = self._store.snapshot_candles()
        signals = self._store.get_signals()

        payload = {
            "written_at": time.time(),
            "candles": {
                key: [_candle_to_dict(c) for c in series]
                for key, series in candles.items()
            },
            "signals": signals,
        }

        tmp_path = self._output_path.with_suffix(".tmp")
        try:
            with tmp_path.open("w") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp_path, self._output_path)
        except OSError as exc:
            logger.warning("Snapshot write failed: %s", exc)
