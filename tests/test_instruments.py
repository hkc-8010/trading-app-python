"""Tests for instruments.py — InstrumentRegistry."""

from __future__ import annotations

import pytest

from scanner.instruments import Instrument, InstrumentRegistry


@pytest.fixture
def instruments() -> list[Instrument]:
    return [
        Instrument(token=1001, symbol="NIFTY", expiry="", strike=0.0, option_type="", instrument_type="EQ"),
        Instrument(token=1002, symbol="NIFTY", expiry="2025-07-31", strike=0.0, option_type="", instrument_type="FUT"),
        Instrument(token=2001, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2002, symbol="NIFTY", expiry="2025-07-31", strike=22000.0, option_type="PE", instrument_type="PE"),
        Instrument(token=2003, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2004, symbol="NIFTY", expiry="2025-07-31", strike=22050.0, option_type="PE", instrument_type="PE"),
        Instrument(token=2005, symbol="NIFTY", expiry="2025-07-31", strike=22100.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2006, symbol="NIFTY", expiry="2025-07-31", strike=22100.0, option_type="PE", instrument_type="PE"),
    ]


@pytest.fixture
def reg(instruments: list[Instrument]) -> InstrumentRegistry:
    return InstrumentRegistry(instruments, strike_step_overrides={"NIFTY": 50})


def test_get_instrument_by_token(reg: InstrumentRegistry) -> None:
    inst = reg.get_instrument(2001)
    assert inst is not None
    assert inst.symbol == "NIFTY"
    assert inst.option_type == "CE"


def test_get_token_roundtrip(reg: InstrumentRegistry) -> None:
    token = reg.get_token("NIFTY", "2025-07-31", 22000.0, "CE")
    assert token == 2001


def test_get_token_missing(reg: InstrumentRegistry) -> None:
    assert reg.get_token("NIFTY", "2025-07-31", 99999.0, "CE") is None


def test_get_option_tokens(reg: InstrumentRegistry) -> None:
    ce, pe = reg.get_option_tokens("NIFTY", "2025-07-31", 22050.0)
    assert ce == 2003
    assert pe == 2004


def test_strike_step_override(reg: InstrumentRegistry) -> None:
    assert reg.get_strike_step("NIFTY") == 50


def test_strike_step_inferred() -> None:
    instruments = [
        Instrument(token=1, symbol="XYZ", expiry="2025-07-31", strike=100.0, option_type="CE", instrument_type="CE"),
        Instrument(token=2, symbol="XYZ", expiry="2025-07-31", strike=200.0, option_type="CE", instrument_type="CE"),
        Instrument(token=3, symbol="XYZ", expiry="2025-07-31", strike=300.0, option_type="CE", instrument_type="CE"),
    ]
    reg = InstrumentRegistry(instruments)
    assert reg.get_strike_step("XYZ") == 100


def test_strike_step_default_unknown_symbol(reg: InstrumentRegistry) -> None:
    assert reg.get_strike_step("UNKNOWN") == 100


def test_get_spot_token_prefers_futures(reg: InstrumentRegistry) -> None:
    # FUT (token=1002) should beat EQ (token=1001) for NIFTY
    assert reg.get_spot_token("NIFTY") == 1002


def test_get_all_spot_tokens(reg: InstrumentRegistry) -> None:
    tokens = reg.get_all_spot_tokens()
    assert "NIFTY" in tokens


def test_list_symbols(reg: InstrumentRegistry) -> None:
    assert "NIFTY" in reg.list_symbols()
