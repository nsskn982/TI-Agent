"""Environment-driven settings. `.env` at the repo root is loaded if present."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def require(name: str) -> str:
    value = env(name)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def env_int(name: str, default: int) -> int:
    value = env(name)
    return int(value) if value is not None else default
