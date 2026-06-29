"""Application configuration loaded from .env and config/settings.yaml."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class UserStrike:
    """A static, user-defined option strike with an associated trading action."""

    symbol: str
    expiry: str
    strike: float
    option_type: str  # "CE" or "PE"
    action: str  # "BUY" or "SELL"


@dataclass
class AppConfig:
    """Runtime configuration for the scanner, merged from env vars and settings.yaml."""

    broker: str
    market_open: str
    scan_interval_seconds: int
    snapshot_interval_seconds: int
    snapshot_path: Path
    strike_step_overrides: dict[str, int]
    dhan_client_id: str
    dhan_access_token: str
    kite_api_key: str
    kite_access_token: str

    @classmethod
    def load(cls, settings_path: Path = Path("config/settings.yaml")) -> AppConfig:
        """Load config from .env and the given settings YAML file.

        Args:
            settings_path: Path to the YAML settings file.

        Returns:
            Populated AppConfig instance.

        Raises:
            FileNotFoundError: If settings_path does not exist.
        """
        load_dotenv()
        with settings_path.open() as fh:
            cfg: dict = yaml.safe_load(fh) or {}

        return cls(
            broker=os.getenv("BROKER", cfg.get("broker", "dhan")),
            market_open=cfg.get("market_open", "09:15"),
            scan_interval_seconds=int(cfg.get("scan_interval_seconds", 60)),
            snapshot_interval_seconds=int(cfg.get("snapshot_interval_seconds", 1)),
            snapshot_path=Path(cfg.get("snapshot_path", "data/snapshot.json")),
            strike_step_overrides=cfg.get("strike_step_overrides", {}),
            dhan_client_id=os.getenv("DHAN_CLIENT_ID", ""),
            dhan_access_token=os.getenv("DHAN_ACCESS_TOKEN", ""),
            kite_api_key=os.getenv("KITE_API_KEY", ""),
            kite_access_token=os.getenv("KITE_ACCESS_TOKEN", ""),
        )


@dataclass
class UserStrikesConfig:
    """Collection of user-defined static strikes loaded from JSON."""

    strikes: list[UserStrike] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = Path("config/user_strikes.json")) -> UserStrikesConfig:
        """Load user strikes from JSON file.

        Args:
            path: Path to the user_strikes.json file.

        Returns:
            UserStrikesConfig with parsed strikes. Returns empty config if file absent.
        """
        if not path.exists():
            return cls(strikes=[])
        with path.open() as fh:
            data: dict = json.load(fh)
        strikes = [UserStrike(**s) for s in data.get("strikes", [])]
        return cls(strikes=strikes)
