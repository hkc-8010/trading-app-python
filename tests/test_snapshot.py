"""Tests for snapshot.py — SnapshotWriter."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scanner.snapshot import SnapshotWriter
from scanner.state import CandleRow, StateStore


@pytest.fixture
def tmp_path_snapshot(tmp_path: Path) -> Path:
    return tmp_path / "data" / "snapshot.json"


class TestSnapshotWriter:
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "snap.json"
        store = StateStore()
        writer = SnapshotWriter(store, path)
        writer.write()
        assert path.exists()

    def test_snapshot_contains_candles(self, tmp_path_snapshot: Path) -> None:
        store = StateStore()
        asyncio.run(
            store.append_candle(
                "straddle:NIFTY",
                CandleRow(timestamp=60.0, open=100.0, high=110.0, low=90.0, close=105.0, volume=50, vwap=102.0),
            )
        )
        writer = SnapshotWriter(store, tmp_path_snapshot)
        writer.write()

        with tmp_path_snapshot.open() as fh:
            data = json.load(fh)

        assert "straddle:NIFTY" in data["candles"]
        candles = data["candles"]["straddle:NIFTY"]
        assert len(candles) == 1
        assert candles[0]["close"] == 105.0
        assert candles[0]["vwap"] == 102.0

    def test_atomic_write_no_partial_read(self, tmp_path_snapshot: Path) -> None:
        """Verify no .tmp file is left after a successful write."""
        store = StateStore()
        writer = SnapshotWriter(store, tmp_path_snapshot)
        writer.write()
        tmp_file = tmp_path_snapshot.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_snapshot_contains_signals(self, tmp_path_snapshot: Path) -> None:
        store = StateStore()
        asyncio.run(
            store.record_signals([{"signal_type": "VWAP_CROSSOVER_UP", "underlying": "NIFTY"}])
        )
        writer = SnapshotWriter(store, tmp_path_snapshot)
        writer.write()

        with tmp_path_snapshot.open() as fh:
            data = json.load(fh)
        assert len(data["signals"]) == 1
