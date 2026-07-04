"""Runtime configuration for the Discord AI office assistant."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_MAX_HISTORY_MESSAGES = 12
DEFAULT_OFFICE_WS_URL = "ws://localhost:3001/ws"


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    openai_api_key: str
    openai_model: str = DEFAULT_OPENAI_MODEL
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES
    office_ws_url: str = DEFAULT_OFFICE_WS_URL
    office_alert_channel_id: int | None = None


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc

    if value < 2:
        raise ConfigError(f"{name} must be at least 2.")

    return value


def _optional_int_env(name: str) -> int | None:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def load_settings() -> Settings:
    """Load and validate settings from .env and the process environment."""

    load_dotenv()

    return Settings(
        discord_token=_required_env("DISCORD_TOKEN"),
        openai_api_key=_required_env("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
        or DEFAULT_OPENAI_MODEL,
        max_history_messages=_int_env(
            "MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES
        ),
        office_ws_url=os.getenv("OFFICE_WS_URL", DEFAULT_OFFICE_WS_URL).strip()
        or DEFAULT_OFFICE_WS_URL,
        office_alert_channel_id=_optional_int_env("OFFICE_ALERT_CHANNEL_ID"),
    )
