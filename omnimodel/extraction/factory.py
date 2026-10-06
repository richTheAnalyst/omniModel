"""Extraction backend factory.

Selects between Ollama (default, free), OpenRouter (cheap, many models),
and Claude (paid, high quality). Can be overridden per-call via the
``backend`` parameter.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..config import config

logger = logging.getLogger("omnimodel")

# Type alias for an extraction function.
Extractor = Callable[..., dict[str, Any]]


def get_extractor(backend: str | None = None) -> Extractor:
    """Return the extraction function for the requested backend.

    Parameters
    ----------
    backend:
        ``"ollama"``, ``"openrouter"``, or ``"claude"``.
        Defaults to ``EXTRACTION_BACKEND`` from config.

    Returns
    -------
    callable
        The extraction function for that backend.
    """
    name = (backend or config.extraction_backend).lower()

    if name == "claude":
        from .claude_extractor import extract_signals as _extract
        return _extract
    if name == "openrouter":
        from .openrouter_extractor import extract_signals as _extract
        return _extract
    if name == "ollama":
        from .ollama_extractor import extract_signals as _extract
        return _extract
    raise ValueError(
        f"Unknown extraction backend: {name!r}. "
        "Use 'ollama', 'openrouter', or 'claude'."
    )


def extract_signals(
    text: str,
    *,
    backend: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Extract signals using the configured backend.

    This is a convenience wrapper around ``get_extractor`` so callers can
    use a single import path regardless of backend.
    """
    extractor = get_extractor(backend)
    return extractor(text, **kwargs)


def available_backends() -> list[str]:
    """Return the list of backend names that are configured."""
    backends = ["ollama"]
    if config.openrouter_api_key:
        backends.append("openrouter")
    if config.anthropic_api_key:
        backends.append("claude")
    return backends
