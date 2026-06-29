"""Zerodha Kite Connect broker adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from scanner.brokers.base import BrokerAdapter, OnTickCallback
from scanner.instruments import Instrument
from scanner.state import Tick

logger = logging.getLogger(__name__)


class ZerodhaAdapter(BrokerAdapter):
    """BrokerAdapter implementation for Zerodha Kite Connect.

    Uses kiteconnect.KiteConnect for REST and kiteconnect.KiteTicker for WebSocket.
    """

    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._kite: Any = None  # KiteConnect instance
        self._ticker: Any = None  # KiteTicker instance
        self._callback: OnTickCallback | None = None
        self._subscribed_tokens: set[int] = set()
        # KiteTicker sends LTQ (last traded quantity) per tick — no delta needed
        self._connected = asyncio.Event()

    async def connect(self) -> None:
        try:
            from kiteconnect import KiteConnect, KiteTicker  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "kiteconnect package not installed. Run: pip install kiteconnect"
            ) from exc

        self._kite = KiteConnect(api_key=self._api_key)
        self._kite.set_access_token(self._access_token)

        self._ticker = KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks = self._on_raw_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_error = self._on_error
        self._ticker.on_close = self._on_close

        # KiteTicker runs its own thread; connect() is non-blocking
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, self._ticker.connect, True)

        # Wait until the on_connect callback fires (max 10s)
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("ZerodhaAdapter: WebSocket connection timed out")

        logger.info("ZerodhaAdapter connected")

    async def disconnect(self) -> None:
        if self._ticker is not None:
            self._ticker.close()
        logger.info("ZerodhaAdapter disconnected")

    async def fetch_instruments(self) -> list[Instrument]:
        """Download NSE and NSE F&O instrument lists from Kite REST API."""
        if self._kite is None:
            raise RuntimeError("Not connected — call connect() first")

        loop = asyncio.get_event_loop()
        raw_nse = await loop.run_in_executor(None, self._kite.instruments, "NSE")
        raw_nfo = await loop.run_in_executor(None, self._kite.instruments, "NFO")

        instruments: list[Instrument] = []
        for row in list(raw_nse) + list(raw_nfo):
            inst = self._parse_kite_row(row)
            if inst is not None:
                instruments.append(inst)

        logger.info("ZerodhaAdapter: loaded %d instruments", len(instruments))
        return instruments

    @staticmethod
    def _parse_kite_row(row: dict[str, Any]) -> Instrument | None:
        instrument_type: str = str(row.get("instrument_type", ""))
        exchange: str = str(row.get("exchange", ""))

        if exchange not in ("NSE", "NFO"):
            return None

        token = int(row["instrument_token"])
        symbol: str = str(row.get("name", row.get("tradingsymbol", "")))
        expiry_raw = row.get("expiry", "")
        expiry = str(expiry_raw) if expiry_raw else ""
        strike = float(row.get("strike", 0) or 0)
        lot_size = int(row.get("lot_size", 1) or 1)

        if instrument_type in ("CE", "PE"):
            return Instrument(
                token=token,
                symbol=symbol,
                expiry=expiry,
                strike=strike,
                option_type=instrument_type,
                instrument_type=instrument_type,
                lot_size=lot_size,
            )
        elif instrument_type == "FUT":
            return Instrument(
                token=token,
                symbol=symbol,
                expiry=expiry,
                strike=0.0,
                option_type="",
                instrument_type="FUT",
                lot_size=lot_size,
            )
        elif instrument_type == "EQ" and exchange == "NSE":
            return Instrument(
                token=token,
                symbol=symbol,
                expiry="",
                strike=0.0,
                option_type="",
                instrument_type="EQ",
                lot_size=1,
            )
        return None

    async def subscribe_ticks(self, tokens: list[int], callback: OnTickCallback) -> None:
        self._callback = callback
        new_tokens = [t for t in tokens if t not in self._subscribed_tokens]
        if not new_tokens:
            return
        if self._ticker is not None:
            self._ticker.subscribe(new_tokens)
            self._ticker.set_mode(self._ticker.MODE_LTP, new_tokens)
        self._subscribed_tokens.update(new_tokens)
        logger.debug("ZerodhaAdapter: subscribed %d tokens", len(new_tokens))

    async def unsubscribe_ticks(self, tokens: list[int]) -> None:
        to_remove = [t for t in tokens if t in self._subscribed_tokens]
        if to_remove and self._ticker is not None:
            self._ticker.unsubscribe(to_remove)
        self._subscribed_tokens.difference_update(to_remove)
        logger.debug("ZerodhaAdapter: unsubscribed %d tokens", len(to_remove))

    def _on_raw_ticks(self, _ws: Any, ticks: list[dict[str, Any]]) -> None:
        for data in ticks:
            try:
                token = int(data["instrument_token"])
                ltp = float(data["last_price"])
                # KiteTicker MODE_LTP provides last_traded_quantity per tick
                volume = int(data.get("last_traded_quantity", 0))
                tick = Tick(token=token, ltp=ltp, volume=volume, timestamp=time.time())
                if self._callback is not None:
                    asyncio.create_task(self._callback(tick))
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("ZerodhaAdapter: malformed tick %s — %s", data, exc)

    def _on_connect(self, _ws: Any, _response: Any) -> None:
        self._connected.set()

    def _on_error(self, _ws: Any, code: int, reason: str) -> None:
        logger.error("ZerodhaAdapter WebSocket error %s: %s", code, reason)

    def _on_close(self, _ws: Any, code: int, reason: str) -> None:
        logger.warning("ZerodhaAdapter WebSocket closed %s: %s", code, reason)
        self._connected.clear()
