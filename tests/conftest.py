"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from scanner.instruments import Instrument, InstrumentRegistry
from scanner.state import StateStore


@pytest.fixture
def basic_instruments() -> list[Instrument]:
    """A minimal set of instruments: NIFTY spot, one CE, one PE."""
    return [
        Instrument(token=1001, symbol="NIFTY", expiry="", strike=0.0, option_type="", instrument_type="EQ"),
        Instrument(token=2001, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2002, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="PE", instrument_type="PE"),
        Instrument(token=2003, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2004, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="PE", instrument_type="PE"),
        Instrument(token=2005, symbol="NIFTY", expiry="2025-07-31", strike=22100.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2006, symbol="NIFTY", expiry="2025-07-31", strike=22100.0, option_type="PE", instrument_type="PE"),
    ]


@pytest.fixture
def registry(basic_instruments: list[Instrument]) -> InstrumentRegistry:
    return InstrumentRegistry(basic_instruments, strike_step_overrides={"NIFTY": 50})


@pytest.fixture
def store() -> StateStore:
    return StateStore()
