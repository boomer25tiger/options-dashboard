"""
Configuration and credential loading for the data layer.

Keys are read from the local .env file (git-ignored) or the process environment.
Every fetcher also accepts explicit credentials, so a future per-user key source
(for a hosted, bring-your-own-keys deployment) can pass them in without changing
the data layer. Nothing here prints secrets.
"""
import os
from dataclasses import dataclass
from typing import Dict, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

_ALPACA_KEYS = (
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "APCA_API_DATA_URL",
    "APCA_API_BASE_URL",
)


def load_env(path: str = DEFAULT_ENV_PATH) -> Dict[str, str]:
    """Parse KEY=VALUE lines from a .env file into a dict. Missing file -> {}."""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def _merged_env() -> Dict[str, str]:
    """.env values, with real process environment variables taking precedence."""
    merged = load_env()
    for key in _ALPACA_KEYS:
        if os.environ.get(key):
            merged[key] = os.environ[key]
    return merged


@dataclass(frozen=True)
class AlpacaCredentials:
    key_id: str
    secret: str


@dataclass(frozen=True)
class Settings:
    data_url: str
    account_url: str


def get_settings(env: Optional[Dict[str, str]] = None) -> Settings:
    env = env if env is not None else _merged_env()
    return Settings(
        data_url=env.get("APCA_API_DATA_URL", "https://data.alpaca.markets"),
        account_url=env.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets"),
    )


def get_alpaca_credentials(env: Optional[Dict[str, str]] = None) -> AlpacaCredentials:
    """Return AlpacaCredentials, or raise a clear error if keys are absent."""
    env = env if env is not None else _merged_env()
    key_id = env.get("APCA_API_KEY_ID")
    secret = env.get("APCA_API_SECRET_KEY")
    if not key_id or not secret:
        raise RuntimeError(
            "Alpaca keys not found. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
            "in the local .env file (see .env.example)."
        )
    return AlpacaCredentials(key_id=key_id, secret=secret)


def mask(value: Optional[str]) -> str:
    """Mask a secret for logging. Never returns the full value."""
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return value[0] + "***"
    return value[:4] + "..." + value[-2:]
