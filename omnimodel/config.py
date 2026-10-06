"""Environment-based configuration for omniModel.

Reads from a `.env` file (if present) and the process environment.
All values are validated at import time so failures surface early.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    # python-dotenv is optional; fall back to raw env vars.
    pass


@dataclass
class Config:
    # --- Anthropic / Claude ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # --- Google Places ---
    google_places_api_key: str = ""

    # --- Ollama (local LLM) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_s: float = 120.0

    # --- OpenRouter (model aggregator, OpenAI-compatible) ---
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-chat"

    # --- Extraction backend selection ---
    # "ollama" (default, free) | "openrouter" (cheap, many models)
    # | "claude" (paid, high quality)
    extraction_backend: str = "ollama"

    # --- Playwright ---
    playwright_browser: str = "chromium"
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30_000

    # --- HTTP / requests ---
    http_timeout_s: float = 30.0
    http_user_agent: str = "omniModel/0.1 (+https://omnimodel.example)"

    # --- Misc ---
    log_level: str = "INFO"
    log_format: str = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", ""),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_timeout_s=float(os.getenv("OLLAMA_TIMEOUT_S", "120.0")),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat"),
            extraction_backend=os.getenv("EXTRACTION_BACKEND", "ollama"),
            playwright_browser=os.getenv("PLAYWRIGHT_BROWSER", "chromium"),
            playwright_headless=_env_bool("PLAYWRIGHT_HEADLESS", True),
            playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000")),
            http_timeout_s=float(os.getenv("HTTP_TIMEOUT_S", "30.0")),
            http_user_agent=os.getenv(
                "HTTP_USER_AGENT", "omniModel/0.1 (+https://omnimodel.example)"
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Singleton accessor.
config = Config.from_env()
