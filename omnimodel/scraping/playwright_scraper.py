"""Playwright-based scraper for company websites.

This module is intentionally thin: it wraps Playwright page navigation and
returns the raw HTML/text for the caller to extract signals from.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import config

logger = logging.getLogger("omnimodel")


async def fetch_page(
    url: str,
    *,
    headless: bool | None = None,
    timeout_ms: int | None = None,
    wait_for: str | None = None,
    **kwargs: Any,
) -> str:
    """Fetch a page and return its rendered text content.

    Parameters
    ----------
    url:
        Absolute URL to navigate to.
    headless:
        Override ``PLAYWRIGHT_HEADLESS`` for this call.
    timeout_ms:
        Override ``PLAYWRIGHT_TIMEOUT_MS`` for this call.
    wait_for:
        Optional Playwright selector to wait for before extracting text.

    Returns
    -------
    str
        The visible text content of the page.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Playwright is not installed. Run: pip install playwright && "
            "playwright install"
        ) from exc

    _headless = config.playwright_headless if headless is None else headless
    _timeout = config.playwright_timeout_ms if timeout_ms is None else timeout_ms

    logger.debug("Fetching %s (headless=%s, timeout=%dms)", url, _headless, _timeout)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=_headless)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=_timeout)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=_timeout)
            text = await page.inner_text("body")
            return text
        finally:
            await browser.close()


async def fetch_pages(
    urls: list[str],
    **kwargs: Any,
) -> dict[str, str]:
    """Fetch multiple pages concurrently and return a URL -> text mapping."""
    import asyncio

    results: dict[str, str] = {}
    tasks = [fetch_page(u, **kwargs) for u in urls]
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    for url, resp in zip(urls, responses):
        if isinstance(resp, Exception):
            logger.warning("Failed to fetch %s: %s", url, resp)
            results[url] = ""
        else:
            results[url] = resp
    return results
