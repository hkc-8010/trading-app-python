"""ATM (At-The-Money) engine: tracks rolling strikes and manages subscriptions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from scanner.brokers.base import BrokerAdapter, OnTickCallback
from scanner.instruments import InstrumentRegistry

logger = logging.getLogger(__name__)


@dataclass
class _ATMState:
    """Per-symbol ATM state."""

    atm_strike: float
    ce_token: int | None
    pe_token: int | None
    expiry: str


class ATMEngine:
    """Dynamically tracks and rolls ATM strike subscriptions per underlying.

    For each underlying symbol, this engine:
    1. Maintains the current ATM strike and its CE/PE WebSocket subscriptions.
    2. On every spot tick, re-computes the ATM strike.
    3. If the strike has changed, unsubscribes old CE/PE tokens and subscribes new ones.

    ATM formula: Round(LTP / strike_step) * strike_step
    """

    def __init__(
        self,
        registry: InstrumentRegistry,
        broker: BrokerAdapter,
        tick_callback: OnTickCallback,
    ) -> None:
        self._registry = registry
        self._broker = broker
        self._tick_callback = tick_callback
        self._state: dict[str, _ATMState] = {}  # symbol → state

    def compute_atm(self, symbol: str, ltp: float) -> float:
        """Compute the ATM strike for a given spot LTP.

        Args:
            symbol: Underlying symbol.
            ltp: Current spot last traded price.

        Returns:
            Nearest ATM strike rounded to the symbol's strike step.
        """
        step = self._registry.get_strike_step(symbol)
        return round(ltp / step) * step

    async def tick(self, symbol: str, ltp: float, expiry: str) -> None:
        """Process a spot/futures tick and roll ATM subscription if needed.

        Args:
            symbol: Underlying symbol.
            ltp: Current spot last traded price.
            expiry: Nearest active expiry to use for option token lookup.
        """
        new_atm = self.compute_atm(symbol, ltp)
        current = self._state.get(symbol)

        if current is not None and current.atm_strike == new_atm and current.expiry == expiry:
            return  # no roll needed

        # Determine new CE/PE tokens
        ce_token, pe_token = self._registry.get_option_tokens(symbol, expiry, new_atm)

        if ce_token is None or pe_token is None:
            logger.warning(
                "ATM tokens not found: %s %s strike=%.0f", symbol, expiry, new_atm
            )
            return

        # Unsubscribe old tokens
        old_tokens: list[int] = []
        if current is not None:
            if current.ce_token is not None:
                old_tokens.append(current.ce_token)
            if current.pe_token is not None:
                old_tokens.append(current.pe_token)
        if old_tokens:
            await self._broker.unsubscribe_ticks(old_tokens)
            logger.debug("ATM roll %s: unsubscribed old tokens %s", symbol, old_tokens)

        # Subscribe new tokens
        await self._broker.subscribe_ticks([ce_token, pe_token], self._tick_callback)
        logger.info(
            "ATM roll %s: %.0f → %.0f (expiry=%s, CE=%d, PE=%d)",
            symbol,
            current.atm_strike if current else 0,
            new_atm,
            expiry,
            ce_token,
            pe_token,
        )

        self._state[symbol] = _ATMState(
            atm_strike=new_atm,
            ce_token=ce_token,
            pe_token=pe_token,
            expiry=expiry,
        )

    def get_active_tokens(self, symbol: str) -> tuple[int | None, int | None]:
        """Return the currently subscribed (CE token, PE token) for a symbol."""
        state = self._state.get(symbol)
        if state is None:
            return None, None
        return state.ce_token, state.pe_token

    def get_active_strike(self, symbol: str) -> float | None:
        """Return the current ATM strike for a symbol, or None if not yet set."""
        state = self._state.get(symbol)
        return state.atm_strike if state else None

    def get_active_expiry(self, symbol: str) -> str | None:
        """Return the current near expiry being tracked for a symbol."""
        state = self._state.get(symbol)
        return state.expiry if state else None

    def active_symbols(self) -> list[str]:
        """Return all symbols currently being tracked."""
        return list(self._state.keys())
