"""Aggregates incoming ticks into 1-minute OHLCV candles."""

from __future__ import annotations

from dataclasses import dataclass, field

from scanner.state import CandleRow, Tick


@dataclass
class _CandleAccumulator:
    """Mutable OHLCV accumulator for a single in-progress candle."""

    open: float
    high: float
    low: float
    close: float
    volume: int
    start_timestamp: float


class CandleBuilder:
    """Stateful per-token tick aggregator.

    Usage:
        builder = CandleBuilder()
        builder.on_tick(tick)   # call for every incoming tick
        candle = builder.close_candle(token, close_ts)  # called at minute boundary
    """

    def __init__(self) -> None:
        self._accumulators: dict[int, _CandleAccumulator] = {}

    def on_tick(self, tick: Tick) -> None:
        """Incorporate a tick into the current in-progress candle for that token.

        Args:
            tick: Incoming market tick. tick.volume is delta (not cumulative).
        """
        token = tick.token
        if token not in self._accumulators:
            self._accumulators[token] = _CandleAccumulator(
                open=tick.ltp,
                high=tick.ltp,
                low=tick.ltp,
                close=tick.ltp,
                volume=tick.volume,
                start_timestamp=tick.timestamp,
            )
        else:
            acc = self._accumulators[token]
            acc.high = max(acc.high, tick.ltp)
            acc.low = min(acc.low, tick.ltp)
            acc.close = tick.ltp
            acc.volume += tick.volume

    def close_candle(self, token: int, close_timestamp: float) -> CandleRow | None:
        """Finalise and return the 1-minute candle for a token, then reset.

        Args:
            token: Broker instrument token.
            close_timestamp: Unix timestamp assigned as the candle's close time.

        Returns:
            Completed CandleRow, or None if no ticks arrived for this token.
        """
        acc = self._accumulators.pop(token, None)
        if acc is None:
            return None
        return CandleRow(
            timestamp=close_timestamp,
            open=acc.open,
            high=acc.high,
            low=acc.low,
            close=acc.close,
            volume=acc.volume,
        )

    def active_tokens(self) -> list[int]:
        """Return tokens that have received at least one tick this minute."""
        return list(self._accumulators.keys())
