"""Instrument registry: maps symbols/strikes to broker tokens."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from math import gcd


@dataclass
class Instrument:
    """A single tradable instrument from the broker master list."""

    token: int
    symbol: str
    expiry: str  # "YYYY-MM-DD" for derivatives, "" for equities
    strike: float  # 0.0 for non-options
    option_type: str  # "CE", "PE", or "" for spot/futures
    instrument_type: str  # "EQ", "FUT", "CE", "PE"
    lot_size: int = 1


class InstrumentRegistry:
    """Efficient lookup structure built from the broker's master instrument list.

    Supports:
    - Token → Instrument lookup
    - (symbol, expiry, strike, option_type) → token lookup
    - Automatic strike-step inference per symbol
    - Spot/futures token lookup by symbol
    """

    def __init__(
        self,
        instruments: list[Instrument],
        strike_step_overrides: dict[str, int] | None = None,
    ) -> None:
        self._strike_step_overrides = strike_step_overrides or {}
        self._by_token: dict[int, Instrument] = {i.token: i for i in instruments}
        self._by_key: dict[tuple[str, str, float, str], int] = {}
        self._spot_tokens: dict[str, int] = {}
        _strikes_by_symbol: dict[str, list[float]] = {}

        for inst in instruments:
            if inst.option_type in ("CE", "PE"):
                key = (inst.symbol, inst.expiry, inst.strike, inst.option_type)
                self._by_key[key] = inst.token
                _strikes_by_symbol.setdefault(inst.symbol, []).append(inst.strike)
            elif inst.instrument_type in ("EQ", "FUT") and inst.strike == 0.0:
                # Keep the futures token (prefer FUT over EQ for F&O underlyings)
                if inst.symbol not in self._spot_tokens or inst.instrument_type == "FUT":
                    self._spot_tokens[inst.symbol] = inst.token

        # Infer strike step per symbol from the GCD of all listed strikes
        self._strike_steps: dict[str, int] = {}
        for symbol, strikes in _strikes_by_symbol.items():
            unique = sorted({int(s) for s in strikes if s > 0})
            if len(unique) >= 2:
                diffs = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]
                self._strike_steps[symbol] = reduce(gcd, diffs)

    def get_instrument(self, token: int) -> Instrument | None:
        """Look up instrument by broker token."""
        return self._by_token.get(token)

    def get_token(
        self, symbol: str, expiry: str, strike: float, option_type: str
    ) -> int | None:
        """Return the broker token for a specific option contract."""
        return self._by_key.get((symbol, expiry, strike, option_type))

    def get_option_tokens(
        self, symbol: str, expiry: str, strike: float
    ) -> tuple[int | None, int | None]:
        """Return (CE token, PE token) for a given strike.

        Returns:
            Tuple of (ce_token, pe_token); either may be None if not found.
        """
        ce = self._by_key.get((symbol, expiry, strike, "CE"))
        pe = self._by_key.get((symbol, expiry, strike, "PE"))
        return ce, pe

    def get_strike_step(self, symbol: str) -> int:
        """Return the option strike interval for a symbol.

        Checks overrides first, then falls back to inferred step, then 100.
        """
        if symbol in self._strike_step_overrides:
            return self._strike_step_overrides[symbol]
        return self._strike_steps.get(symbol, 100)

    def get_spot_token(self, symbol: str) -> int | None:
        """Return the spot/futures token for a given underlying symbol."""
        return self._spot_tokens.get(symbol)

    def get_all_spot_tokens(self) -> dict[str, int]:
        """Return {symbol: token} for all known spot/futures instruments."""
        return dict(self._spot_tokens)

    def list_symbols(self) -> list[str]:
        """Return all symbols that have option chains."""
        return list(self._strike_steps.keys())
