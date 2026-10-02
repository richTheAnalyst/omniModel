"""Command-line interface for omniModel.

Examples
--------
    # Scrape a site and extract signals
    python -m omnimodel.scrape https://example.com

    # Search Google Places
    python -m omnimodel.places "coffee shop near Seattle"

    # Score extracted signals
    python -m omnimodel.score --signals signals.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import config
from .extraction.factory import extract_signals
from .places.google_places import get_place, search_places
from .scraping.playwright_scraper import fetch_page, fetch_pages
from .scoring.weighted_rules import default_rules, score_signals

logger = logging.getLogger("omnimodel")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omnimodel",
        description="omniModel: company signal extraction and scoring.",
    )
    parser.add_argument(
        "--version", action="version", version=f"omnimodel {__version__}"
    )
    parser.add_argument(
        "--log-level",
        default=config.log_level,
        help="Logging level (default: %(default)s)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # --- scrape ---
    p_scrape = sub.add_parser("scrape", help="Scrape one or more URLs.")
    p_scrape.add_argument("urls", nargs="+", help="URLs to fetch.")
    p_scrape.add_argument(
        "--wait-for",
        default=None,
        help="CSS selector to wait for before extracting text.",
    )
    p_scrape.add_argument(
        "--extract",
        action="store_true",
        help="Also send scraped text to an LLM for signal extraction.",
    )
    p_scrape.add_argument(
        "--score",
        action="store_true",
        help="Also compute a weighted score from extracted signals "
        "(requires --extract).",
    )
    p_scrape.add_argument(
        "--backend",
        default=config.extraction_backend,
        choices=["ollama", "openrouter", "claude"],
        help="Extraction backend (default: %(default)s).",
    )
    p_scrape.add_argument(
        "--output", "-o", default=None, help="Write results to a JSON file."
    )

    # --- places ---
    p_places = sub.add_parser("places", help="Search Google Places.")
    p_places.add_argument("query", help="Search query.")
    p_places.add_argument(
        "--max-results", type=int, default=20, help="Max results (default: 20)."
    )
    p_places.add_argument(
        "--lat",
        type=float,
        default=None,
        help="Latitude for location bias.",
    )
    p_places.add_argument(
        "--lng",
        type=float,
        default=None,
        help="Longitude for location bias.",
    )
    p_places.add_argument(
        "--radius",
        type=int,
        default=50_000,
        help="Search radius in meters (default: 50000).",
    )
    p_places.add_argument(
        "--output", "-o", default=None, help="Write results to a JSON file."
    )

    # --- place ---
    p_place = sub.add_parser("place", help="Get details for a place ID.")
    p_place.add_argument("place_id", help="Google Place ID.")
    p_place.add_argument(
        "--output", "-o", default=None, help="Write results to a JSON file."
    )

    # --- score ---
    p_score = sub.add_parser("score", help="Score extracted signals.")
    p_score.add_argument(
        "--signals",
        required=True,
        help="Path to a JSON file of extracted signals.",
    )
    p_score.add_argument(
        "--output", "-o", default=None, help="Write score result to a JSON file."
    )

    return parser


def _write_output(data: dict[str, Any], path: str | None) -> None:
    if path:
        Path(path).write_text(json.dumps(data, indent=2, default=str))
        logger.info("Wrote results to %s", path)
    else:
        print(json.dumps(data, indent=2, default=str))


def cmd_scrape(args: argparse.Namespace) -> int:
    if len(args.urls) == 1:
        text = asyncio.run(
            fetch_page(args.urls[0], wait_for=args.wait_for)
        )
        pages = {args.urls[0]: text}
    else:
        pages = asyncio.run(
            fetch_pages(args.urls, wait_for=args.wait_for)
        )

    if args.extract:
        logger.info("Extracting signals via %s...", args.backend)
        extracted: dict[str, Any] = {}
        for url, page_text in pages.items():
            extracted[url] = extract_signals(page_text, backend=args.backend)

        if args.score:
            from .scoring.weighted_rules import default_rules, score_signals

            scored: dict[str, Any] = {}
            for url, signals in extracted.items():
                result = score_signals(signals, default_rules())
                scored[url] = {
                    "signals": signals,
                    "score": result.score,
                    "breakdown": result.breakdown,
                }
            _write_output(scored, args.output)
        else:
            _write_output(extracted, args.output)
    else:
        _write_output(pages, args.output)
    return 0


def cmd_places(args: argparse.Namespace) -> int:
    bias = None
    if args.lat is not None and args.lng is not None:
        bias = (args.lat, args.lng)
    results = search_places(
        args.query,
        max_results=args.max_results,
        location_bias=bias,
        radius_m=args.radius,
    )
    _write_output({"query": args.query, "results": results}, args.output)
    return 0


def cmd_place(args: argparse.Namespace) -> int:
    result = get_place(args.place_id)
    _write_output(result, args.output)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    raw = Path(args.signals).read_text()
    signals = json.loads(raw)
    result = score_signals(signals, default_rules())
    _write_output(
        {"score": result.score, "breakdown": result.breakdown},
        args.output,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level)

    handlers: dict[str, Any] = {
        "scrape": cmd_scrape,
        "places": cmd_places,
        "place": cmd_place,
        "score": cmd_score,
    }
    handler = handlers[args.command]
    try:
        return handler(args)
    except Exception as exc:  # pragma: no cover
        logger.error("%s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())