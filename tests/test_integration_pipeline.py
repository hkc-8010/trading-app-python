"""Integration test: tick → candle → straddle → VWAP → signal pipeline."""

from __future__ import annotations

import asyncio
import time

import pytest

from scanner.candle_builder import CandleBuilder
from scanner.signal_engine import SignalEngine, SignalType, _straddle_key
from scanner.state import StateStore, Tick
from scanner.straddle_engine import StraddleEngine
from scanner.vwap_engine import VWAPEngine


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_tick_to_signal_pipeline(self) -> None:
        """Simulate two 1-minute candles producing a VWAP crossover signal."""
        store = StateStore()
        candle_builder = CandleBuilder()
        straddle_engine = StraddleEngine()
        vwap_engine = VWAPEngine(store)
        signal_engine = SignalEngine(store)

        symbol = "NIFTY"
        ce_token, pe_token = 2001, 2002
        close_ts_1, close_ts_2 = 60.0, 120.0

        # ── Minute 1: straddle close < VWAP ──────────────────────────────────
        # CE ticks
        for ltp in [100.0, 102.0, 98.0, 99.0]:
            candle_builder.on_tick(Tick(ce_token, ltp, volume=10, timestamp=time.time()))
        # PE ticks
        for ltp in [110.0, 112.0, 108.0, 109.0]:
            candle_builder.on_tick(Tick(pe_token, ltp, volume=10, timestamp=time.time()))

        ce1 = candle_builder.close_candle(ce_token, close_ts_1)
        pe1 = candle_builder.close_candle(pe_token, close_ts_1)
        assert ce1 is not None and pe1 is not None

        straddle1 = straddle_engine.build_straddle(ce1, pe1)
        vwap1 = vwap_engine.apply_vwap(symbol, straddle1)
        # Artificially check that VWAP was annotated
        assert straddle1.vwap == pytest.approx(vwap1)
        await store.append_candle(_straddle_key(symbol), straddle1)

        # ── Minute 2: straddle close > VWAP → crossover UP ──────────────────
        # Higher CE ticks
        for ltp in [120.0, 125.0, 118.0, 124.0]:
            candle_builder.on_tick(Tick(ce_token, ltp, volume=50, timestamp=time.time()))
        # Higher PE ticks
        for ltp in [130.0, 135.0, 128.0, 133.0]:
            candle_builder.on_tick(Tick(pe_token, ltp, volume=50, timestamp=time.time()))

        ce2 = candle_builder.close_candle(ce_token, close_ts_2)
        pe2 = candle_builder.close_candle(pe_token, close_ts_2)
        assert ce2 is not None and pe2 is not None

        straddle2 = straddle_engine.build_straddle(ce2, pe2)
        vwap_engine.apply_vwap(symbol, straddle2)
        await store.append_candle(_straddle_key(symbol), straddle2)

        # ── Signal scan ───────────────────────────────────────────────────────
        signals = signal_engine.scan_all([symbol])

        # With high-priced minute-2 ticks, straddle2.close should be > straddle2.vwap
        # (the VWAP is the weighted average of both minutes, so minute-2 close beats it)
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.VWAP_CROSSOVER_UP
        assert signals[0].underlying == symbol

    @pytest.mark.asyncio
    async def test_vwap_continuous_across_two_candles(self) -> None:
        """VWAP accumulates across candles without reset."""
        store = StateStore()
        candle_builder = CandleBuilder()
        straddle_engine = StraddleEngine()
        vwap_engine = VWAPEngine(store)

        symbol = "NIFTY"
        ce_token, pe_token = 3001, 3002

        # Candle 1
        candle_builder.on_tick(Tick(ce_token, 100.0, 100, 1.0))
        candle_builder.on_tick(Tick(pe_token, 100.0, 100, 1.0))
        ce1 = candle_builder.close_candle(ce_token, 60.0)
        pe1 = candle_builder.close_candle(pe_token, 60.0)
        assert ce1 and pe1
        s1 = straddle_engine.build_straddle(ce1, pe1)
        v1 = vwap_engine.apply_vwap(symbol, s1)

        # Candle 2
        candle_builder.on_tick(Tick(ce_token, 200.0, 100, 61.0))
        candle_builder.on_tick(Tick(pe_token, 200.0, 100, 61.0))
        ce2 = candle_builder.close_candle(ce_token, 120.0)
        pe2 = candle_builder.close_candle(pe_token, 120.0)
        assert ce2 and pe2
        s2 = straddle_engine.build_straddle(ce2, pe2)
        v2 = vwap_engine.apply_vwap(symbol, s2)

        # VWAP must be between the two straddle closes
        assert s1.close < v2 < s2.close or s2.close < v2 < s1.close or v2 == pytest.approx(
            (s1.close + s2.close) / 2, rel=0.01
        )
        # Accumulator should have double the volume of candle 1
        acc = store.get_vwap_accumulator(symbol)
        assert acc.cum_vol == s1.volume + s2.volume
