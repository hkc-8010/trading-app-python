"""Combines CE and PE candles into a synthetic straddle candle."""

from __future__ import annotations

from scanner.state import CandleRow


class StraddleEngine:
    """Builds synthetic straddle OHLCV candles from individual CE and PE candles.

    Straddle Price  = CE_close + PE_close
    Straddle Volume = CE_volume + PE_volume
    Straddle High   = CE_high + PE_high
    Straddle Low    = CE_low + PE_low
    Straddle Open   = CE_open + PE_open
    """

    @staticmethod
    def build_straddle(ce_candle: CandleRow, pe_candle: CandleRow) -> CandleRow:
        """Combine a CE and PE candle into a synthetic straddle candle.

        Args:
            ce_candle: Completed 1-minute candle for the CE leg.
            pe_candle: Completed 1-minute candle for the PE leg.

        Returns:
            Synthetic CandleRow representing the combined straddle instrument.
            The timestamp is taken from ce_candle (both legs share the same minute).
        """
        return CandleRow(
            timestamp=ce_candle.timestamp,
            open=ce_candle.open + pe_candle.open,
            high=ce_candle.high + pe_candle.high,
            low=ce_candle.low + pe_candle.low,
            close=ce_candle.close + pe_candle.close,
            volume=ce_candle.volume + pe_candle.volume,
        )
