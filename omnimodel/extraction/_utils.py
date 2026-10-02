"""Shared helpers for LLM API calls."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("omnimodel")


def call_with_retry(
    client: Any,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    *,
    max_retries: int = 5,
    temperature: float = 0.0,
) -> Any:
    """Call chat completions with exponential backoff on rate limits.

    Retries on 429/500/502/503/504 with delays of 1s, 2s, 4s, 8s, 16s.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            if status is not None and status in {429, 500, 502, 503, 504}:
                wait = 2 ** attempt
                logger.warning(
                    "LLM returned %s, retrying in %ds (attempt %d/%d)",
                    status, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            raise
    raise last_exc  # pragma: no cover


def parse_json(raw: str) -> dict[str, Any]:
    """Parse JSON from a model response, tolerating markdown fences."""
    import json

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("\n", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON: %s", raw[:200])
        return {"_raw": raw}