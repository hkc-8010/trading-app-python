"""In-memory state store: ticks, OHLCV candles, and VWAP accumulators."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Tick:
    """A single market tick from the broker WebSocket."""

    token: int
    ltp: float  # last traded price
    volume: int  # traded quantity for this tick (delta, not cumulative)
    timestamp: float  # unix epoch seconds


@dataclass
class CandleRow:
    """One 1-minute OHLCV candle, optionally annotated with a VWAP value."""

    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0


@dataclass
class VWAPAccumulator:
    """Continuous VWAP state that survives ATM strike rolls.

    Accumulates Σ(TP × Volume) and Σ(Volume) from market open.
    Never reset mid-session; reset only at 9:15 AM startup.
    """

    cum_tp_vol: float = 0.0
    cum_vol: float = 0.0

    def update(self, candle: CandleRow) -> float:
        """Apply one candle and return the updated VWAP.

        Args:
            candle: Completed 1-minute OHLCV candle.

        Returns:
            Current VWAP value, or 0.0 if no volume seen yet.
        """
        tp = (candle.high + candle.low + candle.close) / 3.0
        self.cum_tp_vol += tp * candle.volume
        self.cum_vol += candle.volume
        return self.cum_tp_vol / self.cum_vol if self.cum_vol > 0 else 0.0

    def reset(self) -> None:
        """Reset accumulators for a new trading session."""
        self.cum_tp_vol = 0.0
        self.cum_vol = 0.0


class StateStore:
    """Thread-safe (asyncio) store for ticks, candles, and VWAP accumulators."""

    def __init__(self, tick_buffer_size: int = 500) -> None:
        self._tick_buffer_size = tick_buffer_size
        self._ticks: dict[int, deque[Tick]] = {}
        self._candles: dict[str, list[CandleRow]] = {}
        self._vwap_accumulators: dict[str, VWAPAccumulator] = {}
        self._signals: list[dict] = []
        self._lock = asyncio.Lock()

    async def push_tick(self, tick: Tick) -> None:
        """Append tick to token's ring buffer."""
        async with self._lock:
            if tick.token not in self._ticks:
                self._ticks[tick.token] = deque(maxlen=self._tick_buffer_size)
            self._ticks[tick.token].append(tick)

    def get_ticks(self, token: int) -> list[Tick]:
        """Return a snapshot of buffered ticks for a token."""
        return list(self._ticks.get(token, []))

    async def append_candle(self, key: str, candle: CandleRow) -> None:
        """Append a completed candle under the given series key."""
        async with self._lock:
            if key not in self._candles:
                self._candles[key] = []
            self._candles[key].append(candle)

    def get_candles(self, key: str) -> list[CandleRow]:
        """Return a snapshot of the candle series for a key."""
        return list(self._candles.get(key, []))

    def get_all_candle_keys(self) -> list[str]:
        return list(self._candles.keys())

    def get_vwap_accumulator(self, symbol: str) -> VWAPAccumulator:
        """Return (creating if absent) the VWAP accumulator for a symbol."""
        if symbol not in self._vwap_accumulators:
            self._vwap_accumulators[symbol] = VWAPAccumulator()
        return self._vwap_accumulators[symbol]

    def reset_all_vwap_accumulators(self) -> None:
        """Reset all VWAP accumulators for a new session."""
        for acc in self._vwap_accumulators.values():
            acc.reset()

    async def record_signals(self, signals: list[dict]) -> None:
        """Overwrite the latest signal list (kept for dashboard snapshot)."""
        async with self._lock:
            self._signals = list(signals)

    def get_signals(self) -> list[dict]:
        return list(self._signals)

    def snapshot_candles(self) -> dict[str, list[CandleRow]]:
        """Return a shallow copy of all candle series (safe for snapshotting)."""
        return {k: list(v) for k, v in self._candles.items()}
