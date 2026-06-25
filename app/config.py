"""Runtime configuration for the optional AI Insights layer.

The core viewer and analysis pipeline never touch any of this — they stay fully
local with no network calls. These settings gate *only* the optional, Gemini-backed
"AI Insights" report (see ``app/insights.py``). Values come
from environment variables, optionally seeded from a project-root ``.env`` file via a
tiny KEY=VALUE parser (no ``python-dotenv`` dependency needed).
"""

from __future__ import annotations

import os

from app.paths import ROOT_DIR


def _load_dotenv() -> None:
    """Seed ``os.environ`` from a project-root ``.env`` (real env vars take precedence)."""
    env_path = ROOT_DIR / ".env"
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv()


class Settings:
    """Resolved AI-Insights settings, read once at import time."""

    def __init__(self) -> None:
        self.provider = os.getenv("INSIGHTS_PROVIDER", "gemini").strip().lower()
        self.api_key = (
            os.getenv("INSIGHTS_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        ).strip()
        self.model = os.getenv("INSIGHTS_MODEL", "gemini-2.5-flash").strip()
        try:
            self.max_image_mb = float(os.getenv("INSIGHTS_MAX_IMAGE_MB", "4"))
        except ValueError:
            self.max_image_mb = 4.0

        # Per-IP cap on the cost-bearing insights endpoint (calls/minute). 0
        # disables the limiter. Defends a configured key from quota/billing abuse.
        try:
            self.rate_limit_per_min = int(os.getenv("INSIGHTS_RATE_LIMIT_PER_MIN", "15"))
        except ValueError:
            self.rate_limit_per_min = 15

        # Off by default only when no key exists, so the "runs fully local, no key
        # required" guarantee holds out of the box. A present key auto-enables the
        # feature; INSIGHTS_ENABLED can force it on or off explicitly.
        enabled_env = os.getenv("INSIGHTS_ENABLED")
        self.enabled = _as_bool(enabled_env) if enabled_env is not None else bool(self.api_key)

    @property
    def configured(self) -> bool:
        """True only when the feature is enabled *and* a provider key is available."""
        return self.enabled and bool(self.api_key)


settings = Settings()
