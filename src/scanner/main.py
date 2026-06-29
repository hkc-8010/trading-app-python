"""Entry point: asyncio orchestration loop for the Rolling ATM Straddle Scanner."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path

from scanner.atm_engine import ATMEngine
from scanner.brokers.base import BrokerAdapter, OnTickCallback
from scanner.candle_builder import CandleBuilder
from scanner.config import AppConfig, UserStrike, UserStrikesConfig
from scanner.instruments import InstrumentRegistry
from scanner.signal_engine import SignalEngine, _straddle_key, _user_strike_key
from scanner.snapshot import SnapshotWriter
from scanner.state import StateStore, Tick
from scanner.straddle_engine import StraddleEngine
from scanner.vwap_engine import VWAPEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Nearest weekly/monthly expiry is resolved externally; for now, use the first
# upcoming expiry found in the registry for each symbol.  Production code
# should call a dedicated near-expiry resolver.
_NEAREST_EXPIRY: dict[str, str] = {}


def _resolve_broker(cfg: AppConfig) -> BrokerAdapter:
    if cfg.broker == "dhan":
        from scanner.brokers.dhan import DhanAdapter
        return DhanAdapter(cfg.dhan_client_id, cfg.dhan_access_token)
    elif cfg.broker == "zerodha":
        from scanner.brokers.zerodha import ZerodhaAdapter
        return ZerodhaAdapter(cfg.kite_api_key, cfg.kite_access_token)
    raise ValueError(f"Unknown broker: {cfg.broker!r}")


def _next_minute_boundary(now: float) -> float:
    """Return the unix timestamp of the next whole-minute boundary."""
    return math.ceil(now / 60) * 60


async def run(cfg: AppConfig | None = None) -> None:
    """Main scanner loop.

    Args:
        cfg: AppConfig to use; if None, loads from settings.yaml and .env.
    """
    if cfg is None:
        cfg = AppConfig.load()

    store = StateStore()
    candle_builder = CandleBuilder()
    straddle_engine = StraddleEngine()
    vwap_engine = VWAPEngine(store)
    signal_engine = SignalEngine(store)
    snapshot_writer = SnapshotWriter(store, cfg.snapshot_path)

    broker = _resolve_broker(cfg)
    await broker.connect()

    # ── 1. Load master instrument list ───────────────────────────────────────
    instruments = await broker.fetch_instruments()
    registry = InstrumentRegistry(instruments, cfg.strike_step_overrides)
    logger.info("Registry built: %d option-chain symbols", len(registry.list_symbols()))

    # ── 2. Infer nearest expiry per symbol ───────────────────────────────────
    # Build {symbol: nearest_expiry} from the registry's internal key set.
    # (We use the registry's private _by_key to extract expiries; a cleaner API
    # would expose this directly but we defer that to a future refactor.)
    from collections import defaultdict
    symbol_expiries: dict[str, list[str]] = defaultdict(list)
    for (sym, exp, _, _) in registry._by_key:  # type: ignore[attr-defined]
        if exp:
            symbol_expiries[sym].append(exp)
    for sym, exps in symbol_expiries.items():
        _NEAREST_EXPIRY[sym] = sorted(set(exps))[0]

    # ── 3. Build shared tick callback ─────────────────────────────────────────
    spot_tokens: dict[int, str] = {v: k for k, v in registry.get_all_spot_tokens().items()}

    async def on_tick(tick: Tick) -> None:
        candle_builder.on_tick(tick)
        await store.push_tick(tick)
        # Route spot ticks to ATM engine for roll detection
        if tick.token in spot_tokens:
            symbol = spot_tokens[tick.token]
            expiry = _NEAREST_EXPIRY.get(symbol, "")
            if expiry:
                await atm_engine.tick(symbol, tick.ltp, expiry)

    # ── 4. Initialise ATM engine ───────────────────────────────────────────
    atm_engine = ATMEngine(registry, broker, on_tick)

    # ── 5. Subscribe to spot/futures tickers ─────────────────────────────────
    spot_token_list = list(spot_tokens.keys())
    await broker.subscribe_ticks(spot_token_list, on_tick)
    logger.info("Subscribed to %d spot/futures tokens", len(spot_token_list))

    # ── 6. Load user-defined strikes ─────────────────────────────────────────
    user_cfg = UserStrikesConfig.load()
    user_strikes: list[UserStrike] = user_cfg.strikes

    async def subscribe_user_strikes() -> None:
        for us in user_strikes:
            token = registry.get_token(us.symbol, us.expiry, us.strike, us.option_type)
            if token is None:
                logger.warning(
                    "User strike not found: %s %s %s%s", us.symbol, us.expiry, us.strike, us.option_type
                )
                continue

            async def _on_user_strike_tick(tick: Tick, _us: UserStrike = us) -> None:
                # Route tick to a named candle series for the user strike
                key = _user_strike_key(_us)
                # CandleBuilder uses token — create a pseudo-token from the key hash
                pseudo_token = hash(key) & 0x7FFFFFFF
                from scanner.state import Tick as _Tick
                pseudo_tick = _Tick(
                    token=pseudo_token,
                    ltp=tick.ltp,
                    volume=tick.volume,
                    timestamp=tick.timestamp,
                )
                candle_builder.on_tick(pseudo_tick)
                await store.push_tick(pseudo_tick)

            await broker.subscribe_ticks([token], _on_user_strike_tick)
            logger.info("Subscribed user strike: %s %s %s%s", us.symbol, us.expiry, us.strike, us.option_type)

    await subscribe_user_strikes()

    # Reset VWAP accumulators at session start
    vwap_engine.reset_session()

    # ── 7. Start loops ────────────────────────────────────────────────────────
    async def candle_close_loop() -> None:
        """Fires at every 1-minute boundary to build straddles and check signals."""
        while True:
            now = time.time()
            wait = _next_minute_boundary(now) - now
            await asyncio.sleep(wait)
            close_ts = time.time()

            all_signals = []

            for symbol in atm_engine.active_symbols():
                ce_token, pe_token = atm_engine.get_active_tokens(symbol)
                if ce_token is None or pe_token is None:
                    continue

                ce_candle = candle_builder.close_candle(ce_token, close_ts)
                pe_candle = candle_builder.close_candle(pe_token, close_ts)

                if ce_candle is None or pe_candle is None:
                    logger.debug("Missing candle for %s (CE=%s PE=%s)", symbol, ce_candle, pe_candle)
                    continue

                straddle = straddle_engine.build_straddle(ce_candle, pe_candle)
                vwap_engine.apply_vwap(symbol, straddle)
                key = _straddle_key(symbol)
                await store.append_candle(key, straddle)

            # Universe crossover scan
            all_signals.extend(signal_engine.scan_all(atm_engine.active_symbols()))

            # User-defined strike candles
            for us in user_strikes:
                key = _user_strike_key(us)
                pseudo_token = hash(key) & 0x7FFFFFFF
                us_candle = candle_builder.close_candle(pseudo_token, close_ts)
                if us_candle is not None:
                    vwap_engine.apply_vwap(us.symbol, us_candle)
                    await store.append_candle(key, us_candle)

            all_signals.extend(signal_engine.scan_all_user_strikes(user_strikes))
            await store.record_signals([s.to_dict() for s in all_signals])

            for sig in all_signals:
                logger.info("SIGNAL %s", sig.detail)

    async def snapshot_loop() -> None:
        while True:
            snapshot_writer.write()
            await asyncio.sleep(cfg.snapshot_interval_seconds)  # type: ignore[union-attr]

    try:
        await asyncio.gather(candle_close_loop(), snapshot_loop())
    finally:
        await broker.disconnect()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
