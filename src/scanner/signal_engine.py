"""VWAP crossover signal detection for the straddle universe and user strikes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from scanner.config import UserStrike
from scanner.state import CandleRow, StateStore

logger = logging.getLogger(__name__)


class SignalType(Enum):
    VWAP_CROSSOVER_UP = "VWAP_CROSSOVER_UP"
    VWAP_CROSSOVER_DOWN = "VWAP_CROSSOVER_DOWN"


@dataclass
class Signal:
    """A single scanner signal event."""

    signal_type: SignalType
    underlying: str
    price: float
    vwap: float
    timestamp: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "underlying": self.underlying,
            "price": self.price,
            "vwap": self.vwap,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }


def _straddle_key(symbol: str) -> str:
    return f"straddle:{symbol}"


def _user_strike_key(strike: UserStrike) -> str:
    return f"{strike.symbol}:{strike.expiry}:{int(strike.strike)}:{strike.option_type}"


def _detect_crossover(
    prev: CandleRow, curr: CandleRow
) -> SignalType | None:
    """Detect a VWAP crossover between two consecutive candles."""
    if prev.close <= prev.vwap and curr.close > curr.vwap:
        return SignalType.VWAP_CROSSOVER_UP
    if prev.close >= prev.vwap and curr.close < curr.vwap:
        return SignalType.VWAP_CROSSOVER_DOWN
    return None


class SignalEngine:
    """Runs VWAP crossover scans across all straddle series and user strikes."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def scan_all(self, symbols: list[str]) -> list[Signal]:
        """Scan the most recent two candles for every symbol in the universe.

        Args:
            symbols: List of underlying symbols to scan (e.g. ["NIFTY", "RELIANCE"]).

        Returns:
            List of Signals fired this minute. Empty if no crossovers detected.
        """
        signals: list[Signal] = []
        for symbol in symbols:
            key = _straddle_key(symbol)
            candles = self._store.get_candles(key)
            if len(candles) < 2:
                continue
            prev, curr = candles[-2], candles[-1]
            signal_type = _detect_crossover(prev, curr)
            if signal_type is not None:
                direction = "above" if signal_type == SignalType.VWAP_CROSSOVER_UP else "below"
                signals.append(
                    Signal(
                        signal_type=signal_type,
                        underlying=symbol,
                        price=curr.close,
                        vwap=curr.vwap,
                        timestamp=curr.timestamp,
                        detail=(
                            f"{symbol} straddle closed {direction} VWAP: "
                            f"close={curr.close:.2f}, VWAP={curr.vwap:.2f}"
                        ),
                    )
                )
        return signals

    def scan_user_strike(self, strike: UserStrike) -> list[Signal]:
        """Scan the most recent two candles for a single user-defined strike.

        Args:
            strike: The UserStrike configuration to evaluate.

        Returns:
            List containing at most one Signal for this strike.
        """
        key = _user_strike_key(strike)
        candles = self._store.get_candles(key)
        if len(candles) < 2:
            return []
        prev, curr = candles[-2], candles[-1]
        signal_type = _detect_crossover(prev, curr)
        if signal_type is None:
            return []
        action_hint = (
            "BUY signal"
            if signal_type == SignalType.VWAP_CROSSOVER_UP
            else "SELL signal"
        )
        return [
            Signal(
                signal_type=signal_type,
                underlying=strike.symbol,
                price=curr.close,
                vwap=curr.vwap,
                timestamp=curr.timestamp,
                detail=(
                    f"USER STRIKE {strike.symbol} {strike.expiry} "
                    f"{int(strike.strike)}{strike.option_type} {strike.action} — "
                    f"{action_hint}: close={curr.close:.2f}, VWAP={curr.vwap:.2f}"
                ),
            )
        ]

    def scan_all_user_strikes(self, strikes: list[UserStrike]) -> list[Signal]:
        """Scan all user-defined strikes.

        Args:
            strikes: List of UserStrike objects from config.

        Returns:
            Combined list of Signals from all user strikes.
        """
        signals: list[Signal] = []
        for strike in strikes:
            signals.extend(self.scan_user_strike(strike))
        return signals
