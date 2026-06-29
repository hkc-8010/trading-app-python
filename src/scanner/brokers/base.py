"""Abstract broker adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from scanner.instruments import Instrument
from scanner.state import Tick

OnTickCallback = Callable[[Tick], Awaitable[None]]


class BrokerAdapter(ABC):
    """Common interface for all broker WebSocket + REST integrations.

    Implementors: DhanAdapter, ZerodhaAdapter.
    The adapter is responsible for normalising tick volume to a per-tick delta
    (not cumulative daily volume) before invoking the callback.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Authenticate and open the WebSocket connection."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the WebSocket and release resources."""
        ...

    @abstractmethod
    async def fetch_instruments(self) -> list[Instrument]:
        """Download the full master instrument list via REST.

        Returns:
            All available instruments (EQ, FUT, CE, PE across all expiries).
        """
        ...

    @abstractmethod
    async def subscribe_ticks(self, tokens: list[int], callback: OnTickCallback) -> None:
        """Subscribe to live tick feed for the given instrument tokens.

        The same callback is used for all tokens; the Tick.token field
        identifies which instrument each tick belongs to.

        Args:
            tokens: List of broker instrument tokens to subscribe.
            callback: Async function called for every incoming tick.
        """
        ...

    @abstractmethod
    async def unsubscribe_ticks(self, tokens: list[int]) -> None:
        """Unsubscribe from the live tick feed for the given tokens.

        Args:
            tokens: List of broker instrument tokens to unsubscribe.
        """
        ...
