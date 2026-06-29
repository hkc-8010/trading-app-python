"""Continuous VWAP engine: accumulates across ATM strike rolls."""

from __future__ import annotations

from scanner.state import CandleRow, StateStore, VWAPAccumulator


class VWAPEngine:
    """Computes and annotates VWAP on straddle candles.

    The VWAP accumulator per symbol is stored in StateStore and is NEVER reset
    when the ATM strike rolls — only reset at session start (9:15 AM).
    This produces one unbroken VWAP line per underlying for the entire day.

    Formula:
        VWAP = Σ(TP × Volume) / Σ(Volume)
        Typical Price (TP) = (High + Low + Close) / 3
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def apply_vwap(self, symbol: str, candle: CandleRow) -> float:
        """Update the symbol's VWAP accumulator and annotate the candle in-place.

        Args:
            symbol: Underlying symbol (e.g. "NIFTY").
            candle: Completed synthetic straddle candle to annotate.

        Returns:
            The current VWAP value after incorporating this candle.
        """
        acc: VWAPAccumulator = self._store.get_vwap_accumulator(symbol)
        vwap = acc.update(candle)
        candle.vwap = vwap
        return vwap

    def reset_session(self) -> None:
        """Reset all VWAP accumulators for a fresh trading session (9:15 AM)."""
        self._store.reset_all_vwap_accumulators()

    def get_current_vwap(self, symbol: str) -> float:
        """Return the current VWAP without updating any candle.

        Args:
            symbol: Underlying symbol.

        Returns:
            Current VWAP, or 0.0 if no candles have been processed yet.
        """
        acc = self._store.get_vwap_accumulator(symbol)
        if acc.cum_vol == 0:
            return 0.0
        return acc.cum_tp_vol / acc.cum_vol
