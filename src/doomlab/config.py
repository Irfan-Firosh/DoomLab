"""Runtime settings for the Purdue RCAC model endpoint, loaded from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DEFAULT_BASE_URL = "https://genai.rcac.purdue.edu"
DEFAULT_MODEL = "qwen3.8:27b"
PLACEHOLDER_KEY = "REPLACE_LOCALLY"


class ConfigError(RuntimeError):
    """Raised when required settings are missing or still placeholders."""


def normalize_base_url(raw: str) -> str:
    """Accept the host with or without a trailing /api so paths are never doubled."""
    url = raw.strip().rstrip("/")
    return url.removesuffix("/api")


@dataclass(frozen=True)
class Settings:
    base_url: str
    model_id: str
    api_key: str = field(repr=False)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/api/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/models"


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    api_key = os.environ.get("RCAC_API_KEY", "").strip()
    if not api_key or api_key == PLACEHOLDER_KEY:
        raise ConfigError("RCAC_API_KEY is missing; copy .env.example to .env and add your key")
    return Settings(
        base_url=normalize_base_url(os.environ.get("RCAC_BASE_URL", DEFAULT_BASE_URL)),
        model_id=os.environ.get("RCAC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        api_key=api_key,
    )
