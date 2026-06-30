"""DhanHQ broker adapter using the dhanhq SDK v2."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from scanner.brokers.base import BrokerAdapter, OnTickCallback
from scanner.instruments import Instrument
from scanner.state import Tick

logger = logging.getLogger(__name__)

# DhanHQ exchange segment identifiers (int constants on MarketFeed)
_NSE_FNO_STR = "NSE_FNO"
_NSE_EQ_STR = "NSE_EQ"

# MarketFeed.NSE_FNO = 2, MarketFeed.NSE = 1, MarketFeed.IDX = 0
# NSE_FNO covers futures + options; NSE covers equity; IDX covers indices
_NSE_FNO_INT = 2   # MarketFeed.NSE_FNO
_NSE_EQ_INT  = 1   # MarketFeed.NSE
_IDX_INT     = 0   # MarketFeed.IDX


class DhanAdapter(BrokerAdapter):
    """BrokerAdapter implementation for DhanHQ SDK v2.

    SDK v2 API changes:
    - Credentials are wrapped in DhanContext(client_id, access_token)
    - REST client: dhanhq(dhan_context)
    - WebSocket: marketfeed.MarketFeed(dhan_context, instruments, on_message=...)
    - Callback signature: on_message(ws, data) where data is a parsed dict
    - MarketFeed runs in its own thread → callbacks must use run_coroutine_threadsafe

    CE/PE tokens use Quote mode (17) to get LTQ (last traded qty) for VWAP.
    Spot/futures tokens use Ticker mode (15) — only LTP needed for ATM tracking.
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token
        self._context: Any = None   # DhanContext
        self._dhan: Any = None      # dhanhq REST client
        self._feed: Any = None      # MarketFeed WebSocket client
        self._callback: OnTickCallback | None = None
        self._subscribed_tokens: set[int] = set()
        # Spot tokens get Ticker mode; everything else gets Quote mode for volume
        self._spot_tokens: set[int] = set()
        self._main_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Initialise DhanContext and REST client. WebSocket starts on first subscribe."""
        try:
            from dhanhq import DhanContext, dhanhq  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("dhanhq package not installed. Run: pip install dhanhq") from exc

        self._context = DhanContext(self._client_id, self._access_token)
        self._dhan = dhanhq(self._context)
        self._main_loop = asyncio.get_event_loop()
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
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
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

    @staticmethod
    def _parse_dhan_row(row: dict[str, str]) -> Instrument | None:
        # CSV uses SEM_EXM_EXCH_ID="NSE" for all NSE instruments.
        # SEM_SEGMENT: "D"=F&O, "E"=Equity, "I"=Index, "C"=Currency (skip).
        if row.get("SEM_EXM_EXCH_ID") != "NSE":
            return None

        seg = row.get("SEM_SEGMENT", "")
        if seg not in ("D", "E", "I"):
            return None

        inst_type = row.get("SEM_INSTRUMENT_NAME", "")
        # Trading symbol format: "SYMBOL-MonYear-FUT" or "SYMBOL-MonYear-STRIKE-CE"
        symbol = row.get("SEM_TRADING_SYMBOL", "").split("-")[0].strip()
        token = int(row["SEM_SMST_SECURITY_ID"])
        lot_size = int(float(row.get("SEM_LOT_UNITS", 1) or 1))

        # Expiry: strip the time component "2026-06-30 14:30:00" → "2026-06-30"
        expiry_raw = row.get("SEM_EXPIRY_DATE", "")
        expiry = expiry_raw.split(" ")[0] if expiry_raw else ""

        if inst_type in ("OPTIDX", "OPTSTK") and seg == "D":
            option_type = row.get("SEM_OPTION_TYPE", "")
            if option_type not in ("CE", "PE"):
                return None
            strike = float(row.get("SEM_STRIKE_PRICE", 0) or 0)
            return Instrument(
                token=token, symbol=symbol, expiry=expiry, strike=strike,
                option_type=option_type, instrument_type=option_type, lot_size=lot_size,
            )

        if inst_type in ("FUTIDX", "FUTSTK") and seg == "D":
            return Instrument(
                token=token, symbol=symbol, expiry=expiry, strike=0.0,
                option_type="", instrument_type="FUT", lot_size=lot_size,
            )

        if inst_type == "INDEX" and seg == "I":
            # Index instruments use the full trading symbol as the name
            return Instrument(
                token=token, symbol=symbol, expiry="", strike=0.0,
                option_type="", instrument_type="EQ", lot_size=1,
            )

        if inst_type == "EQUITY" and seg == "E":
            return Instrument(
                token=token, symbol=symbol, expiry="", strike=0.0,
                option_type="", instrument_type="EQ", lot_size=1,
            )

        return None

    async def subscribe_ticks(
        self, tokens: list[int], callback: OnTickCallback, *, is_spot: bool = False
    ) -> None:
        """Subscribe to live ticks.

        Args:
            tokens: Broker instrument tokens to subscribe.
            callback: Async callback invoked for each tick.
            is_spot: If True, subscribe in Ticker mode (LTP only).
                     If False (default), subscribe in Quote mode (LTP + LTQ volume).
        """
        from dhanhq.marketfeed import MarketFeed  # type: ignore[import]

        self._callback = callback
        new_tokens = [t for t in tokens if t not in self._subscribed_tokens]
        if not new_tokens:
            return

        if is_spot:
            self._spot_tokens.update(new_tokens)

        # Build instrument tuples: (exchange_segment_int, security_id_int, subscription_type)
        sub_type = MarketFeed.Ticker if is_spot else MarketFeed.Quote
        instruments = [(_NSE_FNO_INT, t, sub_type) for t in new_tokens]

        if self._feed is None:
            self._feed = MarketFeed(
                dhan_context=self._context,
                instruments=instruments,
                version="v2",
                on_message=self._on_raw_message,
                on_error=self._on_error,
            )
            self._feed.start()  # runs in a background daemon thread
            logger.info("DhanAdapter: WebSocket feed started")
        else:
            self._feed.subscribe_symbols(instruments)

        self._subscribed_tokens.update(new_tokens)
        logger.debug("DhanAdapter: subscribed %d tokens (is_spot=%s)", len(new_tokens), is_spot)

    async def unsubscribe_ticks(self, tokens: list[int]) -> None:
        tokens_to_remove = [t for t in tokens if t in self._subscribed_tokens]
        if tokens_to_remove and self._feed is not None:
            instruments = [(_NSE_FNO_INT, t) for t in tokens_to_remove]
            self._feed.unsubscribe_symbols(instruments)
        self._subscribed_tokens.difference_update(tokens_to_remove)
        self._spot_tokens.difference_update(tokens_to_remove)
        logger.debug("DhanAdapter: unsubscribed %d tokens", len(tokens_to_remove))

    def _on_raw_message(self, _ws: Any, data: Any) -> None:
        """Convert DhanHQ MarketFeed message → Tick and schedule the async callback.

        Called from MarketFeed's background thread, so we use
        run_coroutine_threadsafe to hand off to the main asyncio loop.
        """
        if not isinstance(data, dict) or self._callback is None:
            return
        try:
            token = int(data["security_id"])
            ltp = float(data["LTP"])
            # Quote Data provides LTQ (last traded quantity per tick — already a delta).
            # Ticker Data has no volume field; default to 0.
            volume = int(data.get("LTQ", 0))
            tick = Tick(token=token, ltp=ltp, volume=volume, timestamp=time.time())
            if self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(self._callback(tick), self._main_loop)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("DhanAdapter: malformed tick %s — %s", data, exc)

    def _on_error(self, _ws: Any, error: Any) -> None:
        logger.error("DhanAdapter WebSocket error: %s", error)
