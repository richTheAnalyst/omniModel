"""Claude-based signal extraction.

Sends scraped text to the Anthropic API and asks Claude to identify
structured signals (e.g. pricing, hiring, tech stack, growth markers).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import config
from ._utils import parse_json

logger = logging.getLogger("omnimodel")


def extract_signals(
    text: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    signal_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured signals from scraped text using Claude.

    Parameters
    ----------
    text:
        Raw text scraped from a company website.
    model:
        Override ``ANTHROPIC_MODEL`` for this call.
    max_tokens:
        Max tokens for the Claude response.
    signal_schema:
        Optional description of the signal fields to extract. When omitted,
        a default schema is used.

    Returns
    -------
    dict[str, Any]
        Parsed signal object returned by Claude.
    """
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env."
        )

    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "anthropic is not installed. Run: pip install anthropic"
        ) from exc

    _model = config.anthropic_model if model is None else model
    schema = signal_schema or _default_schema()

    system_prompt = (
        "You are a precise data extraction assistant. You will be given raw "
        "text scraped from a company website. Extract the requested signals "
        "and return ONLY valid JSON with no additional commentary."
    )
    user_prompt = (
        f"Signal schema:\n{json.dumps(schema)}\n\nScraped text:\n{text[:12000]}"
    )

    logger.debug("Calling Claude (%s) for signal extraction", _model)

    client = Anthropic(api_key=config.anthropic_api_key)
    message = client.messages.create(
        model=_model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text if message.content else "{}"
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
