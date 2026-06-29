"""Tests for config.py — AppConfig and UserStrikesConfig."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scanner.config import AppConfig, UserStrike, UserStrikesConfig


class TestAppConfig:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        settings = {
            "broker": "zerodha",
            "market_open": "09:15",
            "scan_interval_seconds": 30,
            "snapshot_interval_seconds": 2,
            "snapshot_path": "data/snap.json",
            "strike_step_overrides": {"NIFTY": 50},
        }
        settings_path = tmp_path / "settings.yaml"
        settings_path.write_text(yaml.dump(settings))

        cfg = AppConfig.load(settings_path)
        assert cfg.broker == "zerodha"
        assert cfg.scan_interval_seconds == 30
        assert cfg.strike_step_overrides["NIFTY"] == 50

    def test_broker_overridden_by_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        settings_path = tmp_path / "settings.yaml"
        settings_path.write_text(yaml.dump({"broker": "dhan"}))
        monkeypatch.setenv("BROKER", "zerodha")
        cfg = AppConfig.load(settings_path)
        assert cfg.broker == "zerodha"

    def test_missing_settings_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            AppConfig.load(Path("/nonexistent/settings.yaml"))


class TestUserStrikesConfig:
    def test_load_from_json(self, tmp_path: Path) -> None:
        data = {
            "strikes": [
                {"symbol": "NIFTY", "expiry": "2025-07-31", "strike": 22000, "option_type": "CE", "action": "BUY"},
                {"symbol": "BANKNIFTY", "expiry": "2025-07-31", "strike": 47000, "option_type": "PE", "action": "SELL"},
            ]
        }
        path = tmp_path / "user_strikes.json"
        path.write_text(json.dumps(data))
        cfg = UserStrikesConfig.load(path)
        assert len(cfg.strikes) == 2
        assert cfg.strikes[0].symbol == "NIFTY"
        assert cfg.strikes[1].action == "SELL"

    def test_missing_file_returns_empty(self) -> None:
        cfg = UserStrikesConfig.load(Path("/nonexistent/user_strikes.json"))
        assert cfg.strikes == []

    def test_empty_strikes_list(self, tmp_path: Path) -> None:
        path = tmp_path / "user_strikes.json"
        path.write_text(json.dumps({"strikes": []}))
        cfg = UserStrikesConfig.load(path)
        assert cfg.strikes == []
