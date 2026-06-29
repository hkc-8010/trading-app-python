"""DhanHQ broker adapter using the dhanhq SDK."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from scanner.brokers.base import BrokerAdapter, OnTickCallback
from scanner.instruments import Instrument
from scanner.state import Tick

logger = logging.getLogger(__name__)

# DhanHQ instrument type constants in their CSV master
_DHAN_INSTRUMENT_TYPE_MAP = {
    "OPTIDX": "CE",  # index options — check option_type field separately
    "OPTSTK": "CE",  # stock options — check option_type field separately
    "FUTIDX": "FUT",
    "FUTSTK": "FUT",
    "INDEX": "EQ",
    "EQUITY": "EQ",
}

# DhanHQ exchange segment identifiers
_NSE_FNO = "NSE_FNO"
_NSE_EQ = "NSE_EQ"


class DhanAdapter(BrokerAdapter):
    """BrokerAdapter implementation for DhanHQ.

    Uses dhanhq.marketfeed for WebSocket and dhanhq.dhanhq for REST.
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._dhan: Any = None  # dhanhq.dhanhq instance
        self._feed: Any = None  # dhanhq.marketfeed instance
        self._callback: OnTickCallback | None = None
        self._subscribed_tokens: set[int] = set()
        # Track last-seen cumulative day volume per token to compute delta
        self._last_volume: dict[int, int] = {}

    async def connect(self) -> None:
        """Initialise DhanHQ REST and WebSocket clients."""
        try:
            from dhanhq import dhanhq, marketfeed  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("dhanhq package not installed. Run: pip install dhanhq") from exc

        self._dhan = dhanhq(self._client_id, self._access_token)
        self._feed = marketfeed.DhanFeed(
            client_id=self._client_id,
            access_token=self._access_token,
            instruments=[],
            subscription_code=marketfeed.Ticker,
            on_ticks=self._on_raw_tick,
        )
        logger.info("DhanAdapter connected (client_id=%s)", self._client_id)

    async def disconnect(self) -> None:
        if self._feed is not None:
            try:
                self._feed.disconnect()
            except Exception:
                pass
        logger.info("DhanAdapter disconnected")

    async def fetch_instruments(self) -> list[Instrument]:
        """Download and parse the DhanHQ NSE F&O master CSV."""
        import csv
        import io

        import aiohttp

        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                text = await resp.text()

        instruments: list[Instrument] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                inst = self._parse_dhan_row(row)
            except (KeyError, ValueError):
                continue
            if inst is not None:
                instruments.append(inst)

        logger.info("DhanAdapter: loaded %d instruments", len(instruments))
        return instruments

    def _parse_dhan_row(self, row: dict[str, str]) -> Instrument | None:
        segment = row.get("SEM_EXM_EXCH_ID", "")
        if segment not in (_NSE_FNO, _NSE_EQ):
            return None

        inst_type_raw = row.get("SEM_INSTRUMENT_NAME", "")
        symbol = row.get("SEM_TRADING_SYMBOL", "").split("-")[0].strip()
        token = int(row["SEM_SMST_SECURITY_ID"])
        lot_size = int(row.get("SEM_LOT_UNITS", 1) or 1)

        if inst_type_raw in ("OPTIDX", "OPTSTK"):
            option_type = row.get("SEM_OPTION_TYPE", "")
            if option_type not in ("CE", "PE"):
                return None
            expiry = row.get("SEM_EXPIRY_DATE", "")
            strike = float(row.get("SEM_STRIKE_PRICE", 0))
            return Instrument(
                token=token,
                symbol=symbol,
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                instrument_type=option_type,
                lot_size=lot_size,
            )
        elif inst_type_raw in ("FUTIDX", "FUTSTK"):
            expiry = row.get("SEM_EXPIRY_DATE", "")
            return Instrument(
                token=token,
                symbol=symbol,
                expiry=expiry,
                strike=0.0,
                option_type="",
                instrument_type="FUT",
                lot_size=lot_size,
            )
        elif inst_type_raw in ("INDEX", "EQUITY") and segment == _NSE_EQ:
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
        # DhanHQ requires (exchange_segment, security_id) pairs
        instruments = [(self._token_to_segment(t), str(t)) for t in new_tokens]
        if self._feed is not None:
            self._feed.subscribe(instruments)
        self._subscribed_tokens.update(new_tokens)
        logger.debug("DhanAdapter: subscribed %d tokens", len(new_tokens))

    async def unsubscribe_ticks(self, tokens: list[int]) -> None:
        tokens_to_remove = [t for t in tokens if t in self._subscribed_tokens]
        if not tokens_to_remove and self._feed is not None:
            instruments = [(self._token_to_segment(t), str(t)) for t in tokens_to_remove]
            self._feed.unsubscribe(instruments)
        self._subscribed_tokens.difference_update(tokens_to_remove)
        logger.debug("DhanAdapter: unsubscribed %d tokens", len(tokens_to_remove))

    def _on_raw_tick(self, data: dict[str, Any]) -> None:
        """Convert DhanHQ raw tick dict → Tick and invoke async callback."""
        try:
            token = int(data["security_id"])
            ltp = float(data.get("LTP", data.get("last_price", 0)))
            cum_vol = int(data.get("volume", 0))
            # Convert cumulative day volume to per-tick delta
            last = self._last_volume.get(token, cum_vol)
            delta = max(0, cum_vol - last)
            self._last_volume[token] = cum_vol
            tick = Tick(token=token, ltp=ltp, volume=delta, timestamp=time.time())
            if self._callback is not None:
                asyncio.create_task(self._callback(tick))
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("DhanAdapter: malformed tick %s — %s", data, exc)

    @staticmethod
    def _token_to_segment(token: int) -> str:
        # DhanHQ uses NSE_FNO for options/futures; a more robust implementation
        # would look this up from the instrument registry.
        return _NSE_FNO
