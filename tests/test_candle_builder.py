"""Tests for candle_builder.py — CandleBuilder."""

from __future__ import annotations

import pytest

from scanner.candle_builder import CandleBuilder
from scanner.state import Tick


def make_tick(token: int, ltp: float, volume: int = 10, ts: float = 1.0) -> Tick:
    return Tick(token=token, ltp=ltp, volume=volume, timestamp=ts)


class TestCandleBuilder:
    def test_single_tick_forms_doji(self) -> None:
        cb = CandleBuilder()
        cb.on_tick(make_tick(1, 100.0, volume=50))
        candle = cb.close_candle(1, close_timestamp=60.0)
        assert candle is not None
        assert candle.open == candle.high == candle.low == candle.close == 100.0
        assert candle.volume == 50
        assert candle.timestamp == 60.0

    def test_multiple_ticks_ohlcv(self) -> None:
        cb = CandleBuilder()
        cb.on_tick(make_tick(1, 100.0, volume=10, ts=1.0))
        cb.on_tick(make_tick(1, 105.0, volume=20, ts=2.0))
        cb.on_tick(make_tick(1, 98.0, volume=5, ts=3.0))
        cb.on_tick(make_tick(1, 103.0, volume=15, ts=4.0))
        candle = cb.close_candle(1, close_timestamp=60.0)
        assert candle is not None
        assert candle.open == 100.0
        assert candle.high == 105.0
        assert candle.low == 98.0
        assert candle.close == 103.0
        assert candle.volume == 50

    def test_no_ticks_returns_none(self) -> None:
        cb = CandleBuilder()
        assert cb.close_candle(999, close_timestamp=60.0) is None

    def test_reset_after_close(self) -> None:
        cb = CandleBuilder()
        cb.on_tick(make_tick(1, 100.0))
        cb.close_candle(1, close_timestamp=60.0)
        # After close, next close should return None
        assert cb.close_candle(1, close_timestamp=120.0) is None

    def test_independent_tokens(self) -> None:
        cb = CandleBuilder()
        cb.on_tick(make_tick(1, 100.0, volume=10))
        cb.on_tick(make_tick(2, 200.0, volume=20))
        c1 = cb.close_candle(1, 60.0)
        c2 = cb.close_candle(2, 60.0)
        assert c1 is not None and c1.close == 100.0
        assert c2 is not None and c2.close == 200.0

    def test_active_tokens(self) -> None:
        cb = CandleBuilder()
        cb.on_tick(make_tick(5, 100.0))
        cb.on_tick(make_tick(6, 200.0))
        assert set(cb.active_tokens()) == {5, 6}
        cb.close_candle(5, 60.0)
        assert 5 not in cb.active_tokens()
