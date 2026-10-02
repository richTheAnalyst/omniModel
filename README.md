# omniModel

Company signal extraction and scoring. Scrape a website, extract structured
signals with an LLM, and compute a weighted score — all from a browser tab.

## Features

- **Playwright scraping** — fetches rendered page text from any URL
- **Signal extraction** — three backends:
  - **OpenRouter** (default) — cheap, many models, uses your API key
  - **Ollama** — free, local, no key needed
  - **Claude** — paid, highest quality
- **Weighted scoring** — 4 rules (pricing, hiring, tech_stack, growth_signals)
- **Streamlit UI** — no login, anyone with browser access can use it
- **Batch mode** — paste multiple URLs, analyze all at once
- **Export** — download results as JSON

## Quick start

```bash
# 1. Activate the venv
.venv\Scripts\activate

# 2. Run the UI
streamlit run app.py
```

Open the URL it prints (usually `http://localhost:8501`).

## Configuration

Copy `.env.example` to `.env` and fill in keys:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `EXTRACTION_BACKEND` | `openrouter` | Which LLM to use |
| `OPENROUTER_API_KEY` | — | Your OpenRouter key |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat` | Model to use |
| `ANTHROPIC_API_KEY` | — | For Claude backend |
| `OLLAMA_MODEL` | `qwen2.5:7b` | For Ollama backend |
| `GOOGLE_PLACES_API_KEY` | — | For places search |

## CLI usage

The Streamlit app is the primary interface, but you can also use the CLI:

```bash
# Scrape + extract + score
python -m omnimodel scrape https://example.com --extract --score

# Google Places search
python -m omnimodel places "coffee shop Seattle"

# Place details
python -m omnimodel place ChIJryqIewBrkFQRkWfQIS8mzpc

# Switch backends
python -m omnimodel scrape https://example.com --extract --backend claude
```

## Testing

```bash
pytest
```

31 tests covering scoring, backend factory, and JSON parsing.

## Project structure

```
app.py                    # Streamlit UI
omnimodel/
  scraping/               # Playwright scraper
  extraction/             # LLM backends (OpenRouter, Ollama, Claude)
  places/                 # Google Places API
  scoring/                # Weighted rules
tests/                    # Unit tests
```