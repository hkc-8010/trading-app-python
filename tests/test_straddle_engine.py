"""Tests for straddle_engine.py — StraddleEngine."""

from __future__ import annotations

import pytest

from scanner.state import CandleRow
from scanner.straddle_engine import StraddleEngine


def make_candle(o: float, h: float, l: float, c: float, v: int, ts: float = 60.0) -> CandleRow:
    return CandleRow(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


class TestStraddleEngine:
    def test_basic_straddle(self) -> None:
        ce = make_candle(100, 110, 90, 105, 50)
        pe = make_candle(80, 85, 75, 82, 30)
        straddle = StraddleEngine.build_straddle(ce, pe)
        assert straddle.open == 180.0
        assert straddle.high == 195.0
        assert straddle.low == 165.0
        assert straddle.close == 187.0
        assert straddle.volume == 80

    def test_timestamp_from_ce(self) -> None:
        ce = make_candle(100, 100, 100, 100, 1, ts=123.0)
        pe = make_candle(100, 100, 100, 100, 1, ts=456.0)
        straddle = StraddleEngine.build_straddle(ce, pe)
        assert straddle.timestamp == 123.0

    def test_zero_volume_legs(self) -> None:
        ce = make_candle(50, 55, 45, 50, 0)
        pe = make_candle(50, 55, 45, 50, 0)
        straddle = StraddleEngine.build_straddle(ce, pe)
        assert straddle.volume == 0
        assert straddle.close == 100.0
