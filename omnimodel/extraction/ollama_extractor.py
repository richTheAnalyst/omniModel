"""Ollama-based signal extraction.

Sends scraped text to a local Ollama server and asks the model to
identify structured signals. Ollama is free, private, and runs locally.

Prerequisites:
    1. Install Ollama: https://ollama.com
    2. Pull a model:  ollama pull qwen2.5:7b
    3. Start the server:  ollama serve
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

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
    """Extract structured signals from scraped text using a local Ollama model.

    Parameters
    ----------
    text:
        Raw text scraped from a company website.
    model:
        Override ``OLLAMA_MODEL`` for this call.
    max_tokens:
        Max tokens for the Ollama response.
    signal_schema:
        Optional description of the signal fields to extract.

    Returns
    -------
    dict[str, Any]
        Parsed signal object.
    """
    _model = config.ollama_model if model is None else model
    schema = signal_schema or _default_schema()

    system_prompt = (
        "You are a precise data extraction assistant. You will be given raw "
        "text scraped from a company website. Extract the requested signals "
        "and return ONLY valid JSON with no additional commentary."
    )
    user_prompt = (
        f"Signal schema:\n{json.dumps(schema)}\n\nScraped text:\n{text[:12000]}"
    )

    logger.debug("Calling Ollama (%s) for signal extraction", _model)

    resp = requests.post(
        f"{config.ollama_base_url}/api/chat",
        json={
            "model": _model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.0,
            },
        },
        timeout=config.ollama_timeout_s,
    )
    resp.raise_for_status()

    raw = resp.json().get("message", {}).get("content", "{}")
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