"""Tests for atm_engine.py — ATMEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.atm_engine import ATMEngine
from scanner.instruments import Instrument, InstrumentRegistry


@pytest.fixture
def registry() -> InstrumentRegistry:
    instruments = [
        Instrument(token=2001, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2002, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="PE", instrument_type="PE"),
        Instrument(token=2003, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2004, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="PE", instrument_type="PE"),
    ]
    return InstrumentRegistry(instruments, strike_step_overrides={"NIFTY": 50})


@pytest.fixture
def broker() -> MagicMock:
    b = MagicMock()
    b.subscribe_ticks = AsyncMock()
    b.unsubscribe_ticks = AsyncMock()
    return b


@pytest.fixture
def callback() -> AsyncMock:
    return AsyncMock()


class TestATMEngine:
    def test_compute_atm_rounds_down(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        assert engine.compute_atm("NIFTY", 22020.0) == 22000.0

    def test_compute_atm_rounds_up(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        assert engine.compute_atm("NIFTY", 22030.0) == 22050.0

    def test_compute_atm_exact(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        assert engine.compute_atm("NIFTY", 22050.0) == 22050.0

    @pytest.mark.asyncio
    async def test_first_tick_subscribes(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        await engine.tick("NIFTY", 22010.0, "2025-07-31")
        broker.subscribe_ticks.assert_awaited_once()
        ce, pe = engine.get_active_tokens("NIFTY")
        assert ce == 2001
        assert pe == 2002

    @pytest.mark.asyncio
    async def test_same_atm_no_resubscribe(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        await engine.tick("NIFTY", 22010.0, "2025-07-31")
        await engine.tick("NIFTY", 22015.0, "2025-07-31")  # still 22000 ATM
        assert broker.subscribe_ticks.await_count == 1

    @pytest.mark.asyncio
    async def test_roll_unsubscribes_old_subscribes_new(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        await engine.tick("NIFTY", 22010.0, "2025-07-31")  # ATM = 22000
        await engine.tick("NIFTY", 22060.0, "2025-07-31")  # ATM = 22050
        assert broker.unsubscribe_ticks.await_count == 1
        old_tokens = broker.unsubscribe_ticks.call_args[0][0]
        assert set(old_tokens) == {2001, 2002}
        assert broker.subscribe_ticks.await_count == 2  # initial + roll
        new_tokens = broker.subscribe_ticks.call_args[0][0]
        assert set(new_tokens) == {2003, 2004}

    @pytest.mark.asyncio
    async def test_unknown_strike_skipped(self, registry: InstrumentRegistry, broker: MagicMock, callback: AsyncMock) -> None:
        engine = ATMEngine(registry, broker, callback)
        # LTP that maps to a strike not in registry
        await engine.tick("NIFTY", 99000.0, "2025-07-31")
        broker.subscribe_ticks.assert_not_awaited()
