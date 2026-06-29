"""Tests for signal_engine.py — SignalEngine."""

from __future__ import annotations

import asyncio

import pytest

from scanner.config import UserStrike
from scanner.signal_engine import SignalEngine, SignalType, _straddle_key, _user_strike_key
from scanner.state import CandleRow, StateStore


def _make_candle(close: float, vwap: float, ts: float = 60.0) -> CandleRow:
    return CandleRow(
        timestamp=ts, open=close, high=close + 5, low=close - 5,
        close=close, volume=100, vwap=vwap,
    )


def _push_candles(store: StateStore, key: str, *args: tuple[float, float]) -> None:
    for i, (c, v) in enumerate(args):
        asyncio.run(store.append_candle(key, _make_candle(c, v, ts=float(i + 1) * 60)))


class TestSignalEngine:
    def test_crossover_up(self) -> None:
        store = StateStore()
        _push_candles(store, _straddle_key("NIFTY"), (195.0, 200.0), (205.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_all(["NIFTY"])
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.VWAP_CROSSOVER_UP

    def test_crossover_down(self) -> None:
        store = StateStore()
        _push_candles(store, _straddle_key("NIFTY"), (205.0, 200.0), (195.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_all(["NIFTY"])
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.VWAP_CROSSOVER_DOWN

    def test_no_signal_both_above(self) -> None:
        store = StateStore()
        _push_candles(store, _straddle_key("NIFTY"), (205.0, 200.0), (210.0, 200.0))
        engine = SignalEngine(store)
        assert engine.scan_all(["NIFTY"]) == []

    def test_no_signal_insufficient_candles(self) -> None:
        store = StateStore()
        _push_candles(store, _straddle_key("NIFTY"), (205.0, 200.0))
        engine = SignalEngine(store)
        assert engine.scan_all(["NIFTY"]) == []

    def test_scan_multiple_symbols(self) -> None:
        store = StateStore()
        _push_candles(store, _straddle_key("NIFTY"), (195.0, 200.0), (205.0, 200.0))
        _push_candles(store, _straddle_key("BANKNIFTY"), (205.0, 200.0), (195.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_all(["NIFTY", "BANKNIFTY"])
        assert len(signals) == 2
        types = {s.underlying: s.signal_type for s in signals}
        assert types["NIFTY"] == SignalType.VWAP_CROSSOVER_UP
        assert types["BANKNIFTY"] == SignalType.VWAP_CROSSOVER_DOWN


class TestSignalEngineUserStrikes:
    @pytest.fixture
    def strike(self) -> UserStrike:
        return UserStrike(symbol="NIFTY", expiry="2025-07-31", strike=22000, option_type="CE", action="BUY")

    def test_user_strike_crossover_up(self, strike: UserStrike) -> None:
        store = StateStore()
        key = _user_strike_key(strike)
        _push_candles(store, key, (195.0, 200.0), (205.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_user_strike(strike)
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.VWAP_CROSSOVER_UP
        assert "BUY" in signals[0].detail

    def test_user_strike_crossover_down(self, strike: UserStrike) -> None:
        store = StateStore()
        key = _user_strike_key(strike)
        _push_candles(store, key, (205.0, 200.0), (195.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_user_strike(strike)
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.VWAP_CROSSOVER_DOWN

    def test_user_strike_no_crossover(self, strike: UserStrike) -> None:
        store = StateStore()
        key = _user_strike_key(strike)
        _push_candles(store, key, (205.0, 200.0), (210.0, 200.0))
        engine = SignalEngine(store)
        assert engine.scan_user_strike(strike) == []

    def test_scan_all_user_strikes(self) -> None:
        store = StateStore()
        strikes = [
            UserStrike("NIFTY", "2025-07-31", 22000, "CE", "BUY"),
            UserStrike("BANKNIFTY", "2025-07-31", 47000, "PE", "SELL"),
        ]
        for s in strikes:
            _push_candles(store, _user_strike_key(s), (195.0, 200.0), (205.0, 200.0))
        engine = SignalEngine(store)
        signals = engine.scan_all_user_strikes(strikes)
        assert len(signals) == 2

    def test_signal_to_dict(self, strike: UserStrike) -> None:
        store = StateStore()
        key = _user_strike_key(strike)
        _push_candles(store, key, (195.0, 200.0), (205.0, 200.0))
        engine = SignalEngine(store)
        sig = engine.scan_user_strike(strike)[0]
        d = sig.to_dict()
        assert d["signal_type"] == "VWAP_CROSSOVER_UP"
        assert d["underlying"] == "NIFTY"
