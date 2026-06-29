"""Tests for vwap_engine.py — VWAPEngine."""

from __future__ import annotations

import pytest

from scanner.state import CandleRow, StateStore
from scanner.vwap_engine import VWAPEngine


def make_candle(h: float, l: float, c: float, v: int, ts: float = 60.0) -> CandleRow:
    return CandleRow(timestamp=ts, open=c, high=h, low=l, close=c, volume=v)


class TestVWAPEngine:
    def test_single_candle_vwap_equals_typical_price(self) -> None:
        store = StateStore()
        engine = VWAPEngine(store)
        candle = make_candle(110.0, 90.0, 100.0, 100)
        vwap = engine.apply_vwap("NIFTY", candle)
        tp = (110 + 90 + 100) / 3
        assert vwap == pytest.approx(tp)
        assert candle.vwap == pytest.approx(tp)

    def test_vwap_annotated_on_candle(self) -> None:
        store = StateStore()
        engine = VWAPEngine(store)
        candle = make_candle(200.0, 180.0, 190.0, 50)
        engine.apply_vwap("BANKNIFTY", candle)
        assert candle.vwap > 0

    def test_continuous_accumulation_across_candles(self) -> None:
        store = StateStore()
        engine = VWAPEngine(store)
        c1 = make_candle(110.0, 90.0, 100.0, 100, ts=60.0)
        c2 = make_candle(120.0, 100.0, 110.0, 200, ts=120.0)
        engine.apply_vwap("NIFTY", c1)
        engine.apply_vwap("NIFTY", c2)
        tp1 = (110 + 90 + 100) / 3
        tp2 = (120 + 100 + 110) / 3
        expected = (tp1 * 100 + tp2 * 200) / 300
        assert c2.vwap == pytest.approx(expected)

    def test_reset_session_clears_accumulators(self) -> None:
        store = StateStore()
        engine = VWAPEngine(store)
        c = make_candle(100.0, 80.0, 90.0, 50)
        engine.apply_vwap("NIFTY", c)
        engine.reset_session()
        acc = store.get_vwap_accumulator("NIFTY")
        assert acc.cum_vol == 0.0

    def test_get_current_vwap_before_any_candle(self) -> None:
        store = StateStore()
        engine = VWAPEngine(store)
        assert engine.get_current_vwap("NIFTY") == 0.0

    def test_vwap_survives_symbol_isolation(self) -> None:
        """Two symbols should have independent VWAP accumulators."""
        store = StateStore()
        engine = VWAPEngine(store)
        engine.apply_vwap("NIFTY", make_candle(100.0, 90.0, 95.0, 100))
        engine.apply_vwap("BANKNIFTY", make_candle(200.0, 180.0, 190.0, 50))
        assert engine.get_current_vwap("NIFTY") != engine.get_current_vwap("BANKNIFTY")
