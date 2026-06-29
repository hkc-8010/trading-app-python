"""Tests for state.py — StateStore and VWAPAccumulator."""

from __future__ import annotations

import pytest

from scanner.state import CandleRow, StateStore, Tick, VWAPAccumulator


@pytest.fixture
def candle() -> CandleRow:
    return CandleRow(timestamp=1000.0, open=200.0, high=210.0, low=195.0, close=205.0, volume=100)


class TestVWAPAccumulator:
    def test_first_candle(self, candle: CandleRow) -> None:
        acc = VWAPAccumulator()
        vwap = acc.update(candle)
        tp = (candle.high + candle.low + candle.close) / 3
        assert vwap == pytest.approx(tp)

    def test_two_candles_weighted(self) -> None:
        acc = VWAPAccumulator()
        c1 = CandleRow(timestamp=1.0, open=100.0, high=110.0, low=90.0, close=100.0, volume=10)
        c2 = CandleRow(timestamp=2.0, open=200.0, high=220.0, low=180.0, close=200.0, volume=20)
        acc.update(c1)
        vwap = acc.update(c2)
        tp1 = (110 + 90 + 100) / 3  # 100.0
        tp2 = (220 + 180 + 200) / 3  # 200.0
        expected = (tp1 * 10 + tp2 * 20) / 30
        assert vwap == pytest.approx(expected)

    def test_zero_volume_returns_zero(self) -> None:
        acc = VWAPAccumulator()
        c = CandleRow(timestamp=1.0, open=100.0, high=100.0, low=100.0, close=100.0, volume=0)
        assert acc.update(c) == 0.0

    def test_reset(self, candle: CandleRow) -> None:
        acc = VWAPAccumulator()
        acc.update(candle)
        acc.reset()
        assert acc.cum_tp_vol == 0.0
        assert acc.cum_vol == 0.0


class TestStateStore:
    @pytest.mark.asyncio
    async def test_push_and_get_tick(self) -> None:
        store = StateStore()
        tick = Tick(token=42, ltp=100.0, volume=5, timestamp=1.0)
        await store.push_tick(tick)
        ticks = store.get_ticks(42)
        assert len(ticks) == 1
        assert ticks[0].ltp == 100.0

    @pytest.mark.asyncio
    async def test_tick_ring_buffer(self) -> None:
        store = StateStore(tick_buffer_size=3)
        for i in range(5):
            await store.push_tick(Tick(token=1, ltp=float(i), volume=1, timestamp=float(i)))
        ticks = store.get_ticks(1)
        assert len(ticks) == 3
        assert ticks[-1].ltp == 4.0  # most recent

    @pytest.mark.asyncio
    async def test_append_and_get_candle(self) -> None:
        store = StateStore()
        c = CandleRow(timestamp=1.0, open=100.0, high=110.0, low=90.0, close=105.0, volume=50)
        await store.append_candle("straddle:NIFTY", c)
        candles = store.get_candles("straddle:NIFTY")
        assert len(candles) == 1
        assert candles[0].close == 105.0

    def test_vwap_accumulator_created_on_demand(self) -> None:
        store = StateStore()
        acc = store.get_vwap_accumulator("NIFTY")
        assert acc.cum_vol == 0.0

    def test_vwap_accumulator_persistent(self) -> None:
        store = StateStore()
        acc1 = store.get_vwap_accumulator("NIFTY")
        acc1.cum_vol = 99.0
        acc2 = store.get_vwap_accumulator("NIFTY")
        assert acc2.cum_vol == 99.0  # same object

    @pytest.mark.asyncio
    async def test_record_and_get_signals(self) -> None:
        store = StateStore()
        await store.record_signals([{"signal_type": "VWAP_CROSSOVER_UP", "underlying": "NIFTY"}])
        signals = store.get_signals()
        assert len(signals) == 1

    def test_snapshot_candles_is_copy(self) -> None:
        store = StateStore()
        import asyncio
        asyncio.run(
            store.append_candle("k", CandleRow(1.0, 1.0, 1.0, 1.0, 1.0, 1))
        )
        snap = store.snapshot_candles()
        snap["k"].append(CandleRow(2.0, 2.0, 2.0, 2.0, 2.0, 2))
        assert len(store.get_candles("k")) == 1  # original not mutated
