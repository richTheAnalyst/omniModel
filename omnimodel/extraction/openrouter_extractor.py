"""OpenRouter-based signal extraction.

OpenRouter aggregates many model providers behind a single OpenAI-compatible
API. This lets you use models like DeepSeek, Qwen, Llama, and Claude without
installing Ollama or paying Anthropic directly.

Get a key at: https://openrouter.ai/keys
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import config
from ._utils import call_with_retry, parse_json

logger = logging.getLogger("omnimodel")


def extract_signals(
    text: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    signal_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured signals from scraped text via OpenRouter.

    Parameters
    ----------
    text:
        Raw text scraped from a company website.
    model:
        Override ``OPENROUTER_MODEL`` for this call.
    max_tokens:
        Max tokens for the model response.
    signal_schema:
        Optional description of the signal fields to extract.

    Returns
    -------
    dict[str, Any]
        Parsed signal object.
    """
    if not config.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your environment or .env."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "openai is not installed. Run: pip install openai"
        ) from exc

    _model = config.openrouter_model if model is None else model
    schema = signal_schema or _default_schema()

    system_prompt = (
        "You are a precise data extraction assistant. You will be given raw "
        "text scraped from a company website. Extract the requested signals "
        "and return ONLY valid JSON with no additional commentary."
    )
    user_prompt = (
        f"Signal schema:\n{json.dumps(schema)}\n\nScraped text:\n{text[:12000]}"
    )

    logger.debug("Calling OpenRouter (%s) for signal extraction", _model)

    client = OpenAI(
        api_key=config.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    message = call_with_retry(
        client, _model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens,
    )

    raw = message.choices[0].message.content if message.choices else "{}"
    return parse_json(raw)


def _default_schema() -> dict[str, Any]:
    return {
        "company_name": "string or null",
        "pricing": "list of {plan, price, billing_period} or null",
        "hiring": "list of open roles or null",
        "tech_stack": "list of technologies mentioned or null",
        "growth_signals": "list of any growth indicators (funding, awards, "
        "partnerships, press) or null",
    }