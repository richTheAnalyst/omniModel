"""Contact details extraction via OpenRouter.

Sends scraped text to OpenRouter and asks the model to identify contact
details (email, phone, address, social links, key people).
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import config
from ._utils import call_with_retry, parse_json

logger = logging.getLogger("omnimodel")


def extract_contact_details(
    text: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Extract contact details from scraped text via OpenRouter."""
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

    system_prompt = (
        "You are a precise data extraction assistant. Extract contact "
        "details from the text and return ONLY valid JSON."
    )
    user_prompt = (
        "Extract the following from the text below:\n"
        "- email: first email address found, or null\n"
        "- phone: first phone number found, or null\n"
        "- address: physical address, or null\n"
        "- website: company website URL, or null\n"
        "- linkedin: LinkedIn profile URL, or null\n"
        "- twitter: Twitter/X handle or URL, or null\n"
        "- key_people: list of {name, title} for founders/leaders, or null\n"
        "- contact_form: URL of a contact/quote form, or null\n\n"
        f"Text:\n{text[:12000]}"
    )

    logger.debug("Extracting contact details via OpenRouter (%s)", _model)

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
