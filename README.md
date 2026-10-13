# omniModel

**Company signal extraction, lead discovery, scoring, outreach — by industry, location and ownership.**

omniModel discovers companies (by industry and location), scrapes their websites, extracts
structured business signals with an LLM, classifies each lead as **government or private**,
scores the opportunity with transparent weighted rules, and turns everything into
ready-to-send proposals and emails you can export as PDF, DOCX or TXT.

Repository: <https://github.com/richTheAnalyst/omniModel> · Version: `0.1.0` · Python: `>= 3.14`

---

## Table of contents

- [Three ways to run it](#three-ways-to-run-it)
- [What you get](#what-you-get)
- [The government / private lead filter](#the-government--private-lead-filter)
- [How it works](#how-it-works)
- [Scoring models](#scoring-models)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Streamlit UI](#running-the-streamlit-ui)
- [Running the FastAPI backend](#running-the-fastapi-backend)
- [Docker](#docker)
- [CLI usage](#cli-usage)
- [Business profiles](#business-profiles)
- [Outreach templates and export](#outreach-templates-and-export)
- [Testing](#testing)
- [Dev container / Codespaces](#dev-container--codespaces)
- [Extending omniModel](#extending-omnimodel)
- [Known gaps and caveats](#known-gaps-and-caveats)
- [Security notes](#security-notes)
- [License](#license)

---

## Three ways to run it

| Interface | Entrypoint | Best for |
|---|---|---|
| Streamlit app | `streamlit run streamlit_app.py` | Quick, self-contained analysis of one URL or a batch, plus a wide Google-Places search. |
| Streamlit **Lead Finder** page | `streamlit run streamlit_app.py` (page appears in the Streamlit nav sidebar) | Profile-driven search + scoring + outreach drafts, driven by `profiles/*.yaml`. |
| FastAPI backend | `uvicorn omnimodel.api.main:app --port 8000` | Headless integration from a frontend or another service. Full reference in `docs/API.md`. |

The original `streamlit_app.py` and the newer `pages/1_Lead_Finder.py` coexist: Streamlit
auto-discovers `pages/` as extra navigation entries, so a single
`streamlit run streamlit_app.py` gives you both.

---

## What you get

- **Scraping** — Playwright renders any URL (including JS) and returns visible page text.
  Headless by default; toggle `PLAYWRIGHT_HEADLESS=false` to watch it.
- **Signal extraction** — three LLM backends, selectable per-run:
  - **Ollama** (local, free, no key),
  - **OpenRouter** (cheap, many models),
  - **Claude** (paid, highest quality).
- **Lead discovery** — Google Places (New) text search by industry + country + region +
  city, returning name, phone, website, address, rating and review count.
- **Ownership classification** *(new)* — each lead is deterministically labelled
  `government` or `non_government`, with a confidence and a reason. See
  [the dedicated section](#the-government--private-lead-filter).
- **AI service fit** — an optional LLM pass rates how well *each* of your services suits a
  specific company, and blends that into the score (70% AI fit / 30% industry table).
- **Scoring** — deterministic weighted rules → `0.0–1.0` per offering, with a per-rule
  breakdown.
- **Outreach** — deterministic templates generate an email, a proposal letter and a
  follow-up, each with PDF/DOCX/TXT download buttons and an editable email draft.
- **Export** — per-document PDF/DOCX/TXT and full run exports as JSON.
- **No database, no queue, no auth (yet).** Everything the app holds lives in
  `st.session_state` for the Streamlit apps, or is stateless per request for the API.

---

## The government / private lead filter

This is the lead-separation feature. It lives in `omnimodel/ownership.py` and is applied
inside `omnimodel/api/service.py` for both discovery and analysis:

```python
from omnimodel.ownership import classify, refine

# classify: fast, deterministic, no LLM calls
own = classify(name, website, google_types)
# -> {"ownership": "government"|"non_government",
#     "ownership_confidence": "high"|"assumed",
#     "ownership_source": "places_type"|"website_domain"|"name"|"none",
#     "ownership_reason": "..."}

# refine: let the AI overturn an "assumed" result, but never a "high" one
final = refine(base, ai_owner)
```

### How a company is judged to be government

Strongest signal first, stop-at-first-hit:

1. **Google place type** — any of
   `local_government_office, government_office, city_hall, courthouse, embassy, police,
   fire_station` → `government`, confidence `high`, source `places_type`.
2. **Website domain** — a hostname containing `gov`/`govt`/`gob`/`gouv`/`mil`, or a
   `.go.<country>` two-letter second-level (`parts[-2] == "go"` and TLD length 2) → `high`,
   `website_domain`.
3. **Name phrase** — the company name matches a curated phrase list
   (`_NAME_RX`), e.g. `ministry of …`, `municipal assembly`, `city council`,
   `parliament of`, `revenue authority`, `public service`, plus Ghana-specific ones
   (`ghana health service`, `ghana revenue authority`, …).
4. **Fallback** → `non_government`, confidence **`assumed`**, source `none`, with the
   reason *"No government indicators found. Not verified; run Analyze to check."*

The key consequence: a government lead must either be strongly indicated *or* be
explicitly confirmed by the AI. An `"unclear"` AI answer is treated as **no evidence**, so
the deterministic rule stays authoritative and the lead is not mis-filed as private.

### Where it runs

- **`POST /search`** — every lead returned by `search_leads` is enriched with
  `classify(lead["name"], lead["website"], lead["types"])` and the field rides along in the
  JSON response, so a frontend can filter `lead["ownership"] == "government"` immediately,
  with no extra calls.
- **`POST /analyze`** — `classify(name, url, types)` runs first; if `use_ai_fit` is on and
  the model returns an ownership value, `refine(...)` upgrades an `assumed` result. A
  government lead discovered from a `.gov` domain is therefore never downgraded by a
  hedging model.

### What ships in the response

```jsonc
{
  "name": "Kumasi Metropolitan Assembly",
  "website": "https://kumasi.gov.gh",
  "ownership": "government",
  "ownership_confidence": "high",
  "ownership_source": "website_domain",
  "ownership_reason": "The website address (kumasi.gov.gh) is a government domain.",
  "scores": { /* … */ },
  "best_offering": "guarding"
}
```

---

## How it works

```
                 ┌─────────────────────────────────────────────────────────────┐
   URLs     ───► │ Playwright scraper  (omnimodel/scraping/playwright_scraper) │ ──► page text
                 └─────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                 ┌─────────────────────────────────────────────────────────────┐
                 │ Extraction factory (omnimodel/extraction/factory)          │
                 │   ollama / openrouter / claude  (plus contact_extractor via   │
                 │   OpenRouter)                                               │
                 └─────────────────────────────────────────────────────────────┘
               + ai_fit.suggest_company_fit(...)  ──► per-service fit + ownership opinion
                                            │  signals JSON (+ optional ai_fit)
                                            ▼
                 ┌─────────────────────────────────────────────────────────────┐
                 │ Scoring                                                     │
                 │   weighted_rules.score_signals        (streamlit_app)       │
                 │   profile_scoring.score_lead           (API + Lead Finder) │
                 └─────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                 ┌─────────────────────────────────────────────────────────────┐
                 │ templates/__init__.py  +  templates/profile_templates.py    │
                 │   → proposal letter / email / follow-up                      │
                 │   export.py → PDF / DOCX / TXT                               │
                 └─────────────────────────────────────────────────────────────┘

  industry + location ──► Google Places (omnimodel/places/google_places) ──► companies
                                                                                   │
                                                          classify() adds ownership ─┘
```

Design points worth knowing:

- **Lazy imports.** `get_extractor()` imports the backend module only when it is selected,
  so a missing `anthropic` or `openai` install cannot break the Ollama path.
- **Per-URL resilience.** `fetch_pages()` uses `asyncio.gather(..., return_exceptions=True)`;
  a failed URL yields empty text, and `_run_pipeline()` records an `error` key per URL.
- **Retry with backoff.** OpenRouter/OpenAI calls go through `call_with_retry()`, which
  retries HTTP 429/500/502/503/504 on 1s, 2s, 4s, 8s, 16s.
- **Tolerant JSON.** `parse_json()` strips markdown fences and returns `{"_raw": ...}`
  rather than raising when a model returns prose.
- **Profile-aware extraction.** The API sends `P["signal_schema"]` to the extractor, so a
  profile can ask for exactly the fields it needs (e.g. `site_count`, `existing_provider`).
- **Windows-safe scraping.** `service._scrape()` uses `asyncio.ProactorEventLoop()` on
  Windows, where Playwright requires it.
- **Session state only.** The Streamlit apps keep `results`, `wide_results`,
  `leads`, `analyzed` and a `dnc` (do-not-contact) set in `st.session_state`.

---

## Scoring models

There are two, intentionally:

### 1. Signal-based rules — `omnimodel/scoring/weighted_rules.py`

Used by `streamlit_app.py`'s **WEB ANALYSER** tab. Scores a URL from the LLM-extracted
signal counts (`pricing`, `hiring`, `tech_stack`, `growth_signals`).

```
score = Σ(weight · contribution) / Σ(weight)      # over rules that matched a signal
```

| Rule | Weight | Contribution |
|---|---|---|
| `pricing` | 1.0 | 1.0 if pricing was found, else 0.0 |
| `hiring` | 1.5 | `len(hiring) / 10`, capped at 1.0 |
| `tech_stack` | 0.5 | `len(tech_stack) / 8`, capped at 1.0 |
| `growth_signals` | 2.0 | `len(growth_signals) / 5`, capped at 1.0 |

Guarantees: missing signals are **skipped** (they never drag the score down), contributions
are clamped to `[0,1]`, and a rule whose `evaluate` raises contributes `0.0` instead of
failing the run.

### 2. Profile-driven per-offering scoring — `omnimodel/scoring/profile_scoring.py`

Used by `pages/1_Lead_Finder.py` and the FastAPI `service._scored()`. Scores every
**service** for a lead from: sector fit, sector priority, company size, footprint (sites
+ review-count proxy), regional cluster density and buying signals (job-post keyword hits).
Weights are relative (default `offering_fit 30, sector_priority 20, size 12.5,
footprint 12.5, cluster 15, buying_signals 10`) and a profile may override any of them.

```
score = Σ(weight · value) / Σ(weight)     # 0..1 per offering
```

**AI blend.** When a company-specific AI fit exists (from
`suggest_company_fit` → `/analyze`), it overrides the industry table:

```python
fit = (1 - AI_WEIGHT) * base + AI_WEIGHT * ai_fit       # AI_WEIGHT = 0.7 → 70% AI / 30% table
```

`best_offering(scores)` picks the highest-scoring service; `best_offering({})` is `None`.

> Scores are **relative**, not absolute. The docs warn that `/search` scores with no
> signals (so `size`, `buying_signals` and `offering_fit` sit at defaults), and that 3 of
> the 6 components are identical across all offerings for a given lead — so pre-analysis
> scores should be treated as a **priority order**, not a verdict.

---

## Tech stack

| Layer | Choice |
|---|---|
| Web UI | Streamlit 1.64 (wide layout, custom CSS, `pages/` multipage) |
| API | FastAPI 0.142 + Uvicorn, CORS middleware, `X-API-Key` auth (constant-time compare) |
| Scraping | Playwright 1.63 (Chromium), with a Windows `ProactorEventLoop` workaround |
| Places | Google Places API (New) via `requests` |
| LLM | Ollama HTTP, OpenRouter (OpenAI SDK), Anthropic SDK |
| Tables/charts | pandas 3.0, `st.dataframe`, `st.bar_chart`, HTML gauge |
| Export | reportlab (PDF), python-docx (DOCX) |
| Config | `Config` dataclass + python-dotenv, module-level singleton |
| Packaging | hatchling, `uv.lock`, console script `omnimodel` |
| Quality | pytest 9, ruff 0.16 (`E/F/W/I`, line length 88, target py314) |

---

## Project structure

```
omniModel/
├── streamlit_app.py              # Standalone Streamlit app: "WEB ANALYSER" + "WIDE RANGE SEARCH" tabs
├── main.py                       # Legacy FastAPI worker — broken, DO NOT USE (see Known gaps)
├── extract.py                    # Legacy Claude profile/pitch helper used by main.py
├── pages/
│   └── 1_Lead_Finder.py          # Profile-driven Streamlit page (newer UI)
├── profiles/
│   ├── simba_gate.yaml           # Shipped business profile (Simba Gate Security, Ghana)
│   └── example_it_services.yaml  # Example profile (Example IT Ltd, Nigeria)
├── Dockerfile                    # Container image for the FastAPI backend
├── dockerignore
├── docs/
│   └── API.md                    # Full REST API reference
├── FRONTEND_API_GUIDE.md         # Frontend developer's guide to the API
├── pyproject.toml                # Metadata, extras (scraping/ui/api/dev), pytest + ruff config
├── uv.lock                       # Locked dependency graph
├── .python-version               # 3.14
├── omnimodel/
│   ├── __init__.py               # __version__ = "0.1.0"
│   ├── __main__.py               # `python -m omnimodel` → CLI
│   ├── cli.py                    # argparse CLI: scrape / places / place / score
│   ├── config.py                 # Config dataclass, .env loading, module-level `config`
│   ├── logging.py                # setup_logging(); configures logging as an import side effect
│   ├── export.py                 # export_pdf / export_docx / export_txt
│   ├── ownership.py              # Government / private lead classification (classify, refine)
│   ├── profile_loader.py         # Loads + validates business profiles from ./profiles
│   ├── scraping/
│   │   └── playwright_scraper.py # fetch_page(), fetch_pages() (concurrent, return_exceptions)
│   ├── extraction/
│   │   ├── factory.py            # get_extractor(), extract_signals(), available_backends()
│   │   ├── ollama_extractor.py   # Local Ollama backend
│   │   ├── openrouter_extractor.py # OpenRouter (OpenAI-compatible) backend
│   │   ├── claude_extractor.py   # Anthropic backend
│   │   ├── contact_extractor.py  # OpenRouter contact-detail extraction
│   │   └── _utils.py             # call_with_retry(), parse_json()
│   ├── places/
│   │   └── google_places.py      # search_places, search_by_location, get_place, get_place_contacts
│   ├── scoring/
│   │   ├── weighted_rules.py     # ScoringRule, ScoreResult, score_signals(), default_rules()
│   │   ├── profile_scoring.py    # score_lead, lead_from_signals, best_offering (AI blend)
│   │   └── ai_fit.py             # suggest_profile_fit, suggest_company_fit (fit + ownership)
│   ├── api/
│   │   └── main.py               # FastAPI: /health, /backends, /profiles, /search, /analyze,
│   │       └── service.py        #   /suggest-fit, /outreach, /export  (logic separated from HTTP)
│   └── templates/
│       ├── __init__.py           # generate_proposal_letter / outreach_email / followup_email (generic)
│       └── profile_templates.py  # render() for profile-based outreach (safe placeholder substitution)
└── tests/
    ├── test_scoring.py             # 12 — weighted-rule scoring
    ├── test_factory.py             #  7 — backend resolution and availability
    ├── test_json_parsing.py        #  6 — markdown-fenced / invalid JSON
    └── test_profiles.py            # NEW (currently fails to import — see Testing)
```

---

## Requirements

- **Python 3.14+** (`.python-version` pins `3.14`).
- **uv** (recommended) or pip.
- **Chromium for Playwright** (large download): `playwright install chromium`
  (`playwright install --with-deps chromium` in the Docker image to also grab system libs).
- A browser cache is already present at the default
  `%USERPROFILE%\AppData\Local\ms-playwright` location on this machine.
- **At least one LLM path:** local Ollama, an OpenRouter key, or an Anthropic key. OpenRouter
  is the default for the API flow; Ollama is the default for the standalone app.
- **A Google Places API key** for discovery (`/search`, `places`, and both UI search tabs).

---

## Installation

### Option A — uv (matches `uv.lock`)

```bash
uv sync --extra ui --extra api --extra scraping --extra dev
uv run playwright install --with-deps chromium
```

### Option B — pip

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e ".[ui,api,scraping,dev]"
playwright install --with-deps chromium
```

The extras:

| Extra | Packages | Enables |
|---|---|---|
| `scraping` | `playwright` | Website analysis |
| `ui` | `streamlit`, `pandas`, `pyyaml`, `reportlab`, `python-docx` | The Streamlit app + Lead Finder |
| `api` | `fastapi`, `uvicorn`, `pyyaml`, `reportlab`, `python-docx` | The REST API + exports |
| `dev` | `pytest`, `ruff` | Tests + linting |

Core (always installed): `requests`, `python-dotenv`, `anthropic`, `openai`.

> `omnimodel` and `openai` 3.22 are installed in this checkout; `httpx` is not
> (it is only referenced by the legacy `main.py`).

---

## Configuration

All runtime config is environment-based. `omnimodel/config.py` loads `.env` from the repo
root at import time and exposes a module-level `config` singleton; raw env vars also work.

```bash
cp .env.example .env
```

| Variable | Default | Required for | Notes |
|---|---|---|---|
| `EXTRACTION_BACKEND` | `ollama` | App default | `ollama` \| `openrouter` \| `claude`. |
| `OPENROUTER_API_KEY` | — | OpenRouter backend; contact extraction | Key from <https://openrouter.ai/keys>. Presence enables the backend in the UI. |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat` | OpenRouter backend | Any model slug. |
| `ANTHROPIC_API_KEY` | — | Claude backend | Presence enables the backend in the UI. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude backend | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama backend | Point at a remote Ollama host. |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama backend | `ollama pull qwen2.5:7b` first. |
| `OLLAMA_TIMEOUT_S` | `120.0` | Ollama backend | Raise for CPU inference on big models. |
| `GOOGLE_PLACES_API_KEY` | — | `/search`, `/places`, search tabs | Grants access to the Places (New) text search + details. |
| `API_KEY` | — | FastAPI only | Value that clients send as `X-API-Key`. If unset, the API returns `503`. |
| `CORS_ORIGINS` | — | FastAPI only | Comma-separated allowed origins. Localhost is always permitted. |
| `PLAYWRIGHT_BROWSER` | `chromium` | Scraping | Read but effectively ignored — the scraper always launches Chromium. |
| `PLAYWRIGHT_HEADLESS` | `true` | Scraping | `1/true/yes/on`. Set `false` to watch the browser. |
| `PLAYWRIGHT_TIMEOUT_MS` | `30000` | Scraping | Navigation + selector timeout. |
| `HTTP_TIMEOUT_S` | `30.0` | Places calls | Per-request timeout. |
| `LOG_LEVEL` | `INFO` | — | Standard logging level name. |

### Minimum viable setups

```bash
# Free and local
EXTRACTION_BACKEND=ollama
# needs: GOOGLE_PLACES_API_KEY for discovery, ollama running for extraction

# Cheap and hosted
EXTRACTION_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-...
GOOGLE_PLACES_API_KEY=xxx

# Highest quality
EXTRACTION_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...
```

For the API, add:

```bash
API_KEY=replace-me-with-a-long-random-string
CORS_ORIGINS=https://myapp.com,https://preview.example.dev
```

`.env`, `.streamlit/secrets.toml`, `*.pem`, `*.key`, and build artifacts are gitignored — see
[`.gitignore`](#project-structure).

---

## Running the Streamlit UI

```bash
streamlit run streamlit_app.py
```

Open the printed URL (usually <http://localhost:8501>). The **Lead Finder** page
(`pages/1_Lead_Finder.py`) appears automatically as a second entry in the Streamlit
navigation sidebar.

| Page | What it uses |
|---|---|
| Main page (2 tabs) | `weighted_rules` scoring, the generic templates in `omnimodel/templates/__init__.py`, built-in location data in `streamlit_app.py`. |
| **Lead Finder** page | a `profiles/*.yaml` file, `profile_scoring.score_lead`, `profile_templates.render`, the ownership-aware pipeline (via `pages` it calls `classify` only indirectly; ownership enrichment is in the API). |

Useful flags:

```bash
streamlit run streamlit_app.py --server.port 8502 --server.address 0.0.0.0
streamlit run streamlit_app.py --server.runOnSave true     # autoreload on save
```

The app resolves `.env` relative to the package root, so run it from the repo root.

### First-run checklist

1. Sidebar → **LLM backend**: pick a backend. For Ollama confirm `ollama serve` is running
   and the model is pulled.
2. **WEB ANALYSER** → enter `https://example.com` → **Analyze**. Expect a score, a gauge, a
   breakdown chart and three outreach tabs.
3. **WIDE RANGE SEARCH** → Ghana → Greater Accra → Accra, type an industry, press
   **Search companies**. Expect a table of businesses.
4. **Lead Finder** page → pick the `simba_gate` profile → select Region/City/Industry →
   **Search** → open a lead → **Analyze website** → read the per-offering metrics and
   download drafts.

---

## Running the FastAPI backend

```bash
API_KEY=replace-me GOOGLE_PLACES_API_KEY=xxx OPENROUTER_API_KEY=sk-or-... \
  uvicorn omnimodel.api.main:app --host 0.0.0.0 --port 8000
```

Then open <http://127.0.0.1:8000/docs> for the interactive Swagger UI, which exercises every
endpoint. A full integration reference — including the **governance response fields**
emitted by `/search` and `/analyze` (`ownership`, `ownership_confidence`,
`ownership_source`, `ownership_reason`) — is in [`docs/API.md`](docs/API.md).

Quick smoke test:

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}

curl -s -H "X-API-Key: replace-me" \
  http://localhost:8000/backends
# {"backends": ["ollama","openrouter","claude"]}

curl -s -H "X-API-Key: replace-me" \
  "http://localhost:8000/profiles/simba_gate"   # builds your frontend dropdowns
```

Endpoints (all except `/health` require `X-API-Key`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check, no key required. |
| `GET` | `/backends` | Which extraction backends are configured right now. |
| `GET` | `/profiles` | List of profile ids on the server. |
| `GET` | `/profiles/{name}` | Public profile shape for building dropdowns/sector→offering fit. |
| `POST` | `/search` | Find companies by industry + location, score every offering, classify ownership. |
| `POST` | `/analyze` | Scrape + extract + AI-fit one URL; returns scores, best offering and ownership. |
| `POST` | `/suggest-fit` | Ask the LLM to rate every offering across every sector (batch, 10 at a time). |
| `POST` | `/outreach` | Render a profile template for one lead/offering. |
| `POST` | `/export` | Turn text into PDF/DOCX/TXT bytes, returned as a download (`Content-Disposition`). |

`/search` and `/analyze` both enrich results with the ownership fields described in
[The government / private lead filter](#the-government--private-lead-filter), so a frontend
can split leads into government vs private immediately.

---

## Docker

The project ships a minimal image that runs the API:

```bash
docker build -t omnimodel .
docker run -p 8000:8000 \
  -e API_KEY=replace-me \
  -e GOOGLE_PLACES_API_KEY=xxx \
  -e OPENROUTER_API_KEY=sk-or-... \
  -e CORS_ORIGINS=https://myapp.com \
  omnimodel
```

`Dockerfile`:

```dockerfile
FROM python:3.14-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY omnimodel ./omnimodel
COPY profiles ./profiles
RUN uv sync --frozen --extra api --extra scraping
RUN playwright install --with-deps chromium   # the big download
EXPOSE 8000
CMD ["sh", "-c", "uvicorn omnimodel.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`dockerignore` deliberately excludes `.venv`, `.env`, `.git`, `tests`, `pages`,
`streamlit_app.py`, `tmp_*`, etc., so the API image stays small. (The Streamlit UI is not
containerized by this Dockerfile — run it locally or add a second stage.)

---

## CLI usage

```bash
omnimodel --help
omnimodel --version
python -m omnimodel scrape --help      # equivalent
```

### `scrape` — scrape, extract signals, score

```bash
# text only
omnimodel scrape https://example.com

# scrape + signal extraction (profile schema only via the API; CLI uses the generic schema)
omnimodel scrape https://example.com --extract --backend openrouter

# scrape + extract + weighted score
omnimodel scrape https://example.com --extract --score

# batch, concurrent, write JSON
omnimodel scrape https://a.com https://b.com --extract --score -o results.json

# wait for a selector before reading text
omnimodel scrape https://example.com --wait-for ".pricing-table" --extract
```

| Flag | Default | Meaning |
|---|---|---|
| `urls` (positional, ≥1) | — | One URL scrapes; multiple are fetched concurrently. |
| `--wait-for` | `None` | CSS selector to await before extracting text. |
| `--extract` | off | Send page text to the selected LLM backend. |
| `--score` | off | Weighted score (requires `--extract`). |
| `--backend` | `EXTRACTION_BACKEND` | `ollama` \| `openrouter` \| `claude`. |
| `--output`, `-o` | stdout | Write JSON to a file. |

### `places` / `place` — Google Places

```bash
omnimodel places "coffee shop Seattle"
omnimodel places "software company Lagos" --max-results 15 --output places.json
omnimodel places "dentist" --lat 47.6062 --lng -122.3321 --radius 25000   # lat/lng together
omnimodel place ChIJryqIewBrkFQRkWfQIS8mzpc
```

`--lat`/`--lng` must be supplied together; they set a circular `locationBias`.

### `score` — score a previously extracted signals file

```bash
omnimodel scrape https://example.com --extract -o signals.json
omnimodel score --signals signals.json --output score.json
```

---

## Business profiles

A **profile** is a single YAML file in `profiles/` describing who is selling, what they
sell, where they sell, and how to score and write to each customer. `simba_gate.yaml` ships
ready to use; `example_it_services.yaml` shows a completely different business on the same
engine.

A profile has:

- `name`, `country`, `business` (your contact details)
- `offerings` — `{key: {label, description}}`
- `sectors` — `{key: {label, query, priority, fit:{offering:0..1}}}`; `query` is the Google
  Places search text, `priority` is sector attractiveness, `fit` is how well each offering
  suits the sector
- `geography` — `{region: [city, …]}` (drives the Lead Finder dropdowns and the cluster score)
- `weights` — override the default scoring weights (relative, need not sum to 100)
- `buying_signal_keywords` — lowercase substrings, each job-post match counts double
- `signal_schema` — passed to the LLM so it extracts exactly the fields you need
  (`site_count`, `size_estimate`, `existing_provider`, …)
- `context_notes` — region/sector/offering-specific local notes interpolated into outreach
- `outreach.{email,proposal,followup}` — `str.format`-style templates over
  `{company} {city} {offering_label} {offering_desc} {local_context} {our_name} …`

Validate and list profiles:

```bash
python -c "from omnimodel.profile_loader import list_profiles, load_profile; \
print(list_profiles()); load_profile('simba_gate'); print('ok')"
```

The loader enforces: required keys present, 1–30 offerings, every `fit`/`sectors` offering key
resolves to a real offering, a 300 000-char profile cap and 5 000-char-per-template cap, and
that all three outreach templates are non-empty.

---

## Outreach templates and export

`omnimodel/templates/__init__.py` renders three artefacts from a signals dict plus your
sidebar business details (used by the standalone app):

- `generate_proposal_letter()` — intro, fit rationale, deliverables, 15-minute CTA, signature
- `generate_outreach_email()` — subject + short body (editable before export)
- `generate_followup_email()` — gentle "circling back" note

`omnimodel/templates/profile_templates.py`'s `render()` is the profile path: a safe regex
substitution that replaces `{placeholder}` tokens from `lead`, `offering` and `business`,
leaving unknown tokens untouched so a template can never reach into Python objects.

`omnimodel/export.py`:

- `export_pdf(text)` — reportlab, US Letter, 85-char-wrapped lines, auto page breaks
- `export_docx(text, title)` — python-docx with a level-0 heading, blank lines preserved
- `export_txt(text)` — UTF-8 bytes

In every UI, download buttons are rendered as three adjacent columns (PDF/DOCX/TXT) with
sanitised filenames: `{type}_{safe_company_name}.{ext}` via `_safe_filename()`.

---

## Testing

```bash
.venv\Scripts\python -m pytest            # or: uv run pytest
.venv\Scripts\python -m ruff check .
```

Current state:

| File | Tests | Covers |
|---|---|---|
| `tests/test_scoring.py` | 12 | Weighted-rule scoring, clamping, exception safety, defaults |
| `tests/test_factory.py` | 7 | Backend resolution, override, unknown backend, availability |
| `tests/test_json_parsing.py` | 6 | Plain / markdown-fenced / invalid / empty / nested JSON |
| **`tests/test_profiles.py`** | — | Loader, profile scoring, outreach renderer — **currently fails to collect** |

The 25 baseline tests above pass. The new `tests/test_profiles.py` **fails at import time**:

```
ImportError: cannot import name 'profile_path' from 'omnimodel.profile_loader'
```

`profile_loader.py` does not expose a `profile_path` helper, which the tests expect
(it is intended to reject path-traversal stems like `../secrets` with a `ValueError`, and
`load_profile` itself would happily read outside `profiles/`). Until `profile_path` is
implemented (or the test import is corrected), run the passing three with:

```bash
.venv\Scripts\python -m pytest tests/test_scoring.py tests/test_factory.py tests/test_json_parsing.py
```

All suite tests are pure logic: no network, no LLM, no Playwright.

---

## Dev container / Codespaces

`.devcontainer/devcontainer.json` provisions a Python container, forwards port **8501** (with
`onAutoForward: openPreview`) and runs on attach:

```bash
streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false
```

It installs `streamlit` via `updateContentCommand` from `requirements.txt` if present, or
`pip3 install --user streamlit`. **Note:** the image is
`mcr.microsoft.com/devcontainers/python:1-3.11-bookworm`, but the project targets Python
3.14 — bump the image tag (or install 3.14) for a fully consistent environment.

---

## Extending omniModel

**Add an extraction backend**

1. Create `omnimodel/extraction/<name>_extractor.py` exposing
   `extract_signals(text, *, model=None, max_tokens=2048, signal_schema=None) -> dict`.
2. Register it in `omnimodel/extraction/factory.py` (`get_extractor`) and
   `omnimodel/cli.py` (`--backend` choices).
3. Add the key/model fields to `Config.from_env()` and `.env.example`; append to
   `available_backends()` guarded by the presence of the key.

**Add a scoring rule** — extend `default_rules()` (signal path) or edit a profile's
`weights` / per-sector `fit` (profile path).

**Add a country or region** — extend `_COUNTRIES`, `_AREAS_BY_COUNTRY` and
`_CITIES_BY_COUNTRY` (and `_GHANA_CITIES`-style data if you want Ghana-style metadata) at the
top of `streamlit_app.py`.

**Add outreach templates** — add a `str.format` generator in
`omnimodel/templates/__init__.py`, or a new `outreach.<kind>` block in a profile YAML.

**Add a government indicator** — extend `GOV_TYPES` or `NAME_PHRASES` in
`omnimodel/ownership.py`.

---

## Known gaps and caveats

- **No authentication on the Streamlit apps.** The sidebar shows a banner about it. Anyone
  who can reach the port can spend your API credits. The FastAPI backend *does* require
  `X-API-Key` (compared with `hmac.compare_digest`, though the server-side `API_KEY` is
  itself read once at startup via `os.getenv`).
- **`tests/test_profiles.py` cannot be collected** — see [Testing](#testing). The
  `profiles/` directory and the profile-scoring pipeline exist and are correct, but one
  missing helper (`profile_path`) breaks the test file on import.
- **`streamlit_app.py` does not surface ownership.** The government/private classification
  runs in the API and is emitted by `/search` and `/analyze`; the standalone **Lead Finder**
  page does not call `classify`. If you want the filter in the Streamlit UI, wire
  `omnimodel.ownership.classify` onto each lead.
- **`main.py` and `extract.py` are legacy and `main.py` does not start.** `main.py` imports
  `from scoring import score_lead` and `from extract import …`, but there is no root
  `scoring` module (it lives in `omnimodel/scoring/profile_scoring.py`), `fastapi` and
  `httpx` are not declared in `pyproject.toml`, and `extract.py` hardcodes
  `MODEL = "claude-sonnet-5-5"` which will not resolve. The maintained equivalent is the
  FastAPI backend in `omnimodel/api/`. Both files should be deleted or archived once the
  Laravel side talks to the API.
- **`PLAYWRIGHT_BROWSER` is read but unused** — the scraper always launches Chromium.
- **`omnimodel/logging.py` reconfigures root logging at import time**; importing it from a
  library context resets the caller's handlers.
- **Extraction truncates page text to 12 000 chars** and `ai_fit` to ~7 500 chars.
- **Scores are relative**, especially before any website is analysed — see the warning in
  `docs/API.md` §5 and the `score` docs above.
- **Google Places caps a text search at 20 results**; `/search`, `places`, and the UI
  search all clamp `max_results` to 20, and each contact enrichment is an extra detail
  request (up to 21 requests per search).
- **LLM extraction quality depends on page text.** JS-heavy or login-walled sites yield
  little; bump `PLAYWRIGHT_TIMEOUT_MS` and consider `wait_for` selectors.
- **`requires-python = ">=3.14"`** — the dev container image ships 3.11.

---

## Security notes

- `.env`, `.streamlit/secrets.toml`, `*.pem`, `*.key`, `*.p12`/`*.pfx`, build artifacts and
  caches are gitignored — keep it that way; never commit real keys.
- Keys are read from the environment only; nothing is written to disk by the app.
- `/analyze` calls `_check_url()` which rejects `localhost`, `.local`/`.internal`, and all
  private/loopback/link-local/reserved IPs — mitigating SSRF from the scraper.
- `/profiles/{name}` resolves the id from the `profiles/` listing rather than from user
  input, blocking `../` path traversal at the lookup (the profile loader still has a gap —
  see Known gaps).
- The dev container disables CORS and XSRF so the Streamlit preview works; do not copy
  those flags to a real deployment.
- `omnimodel/logging.py` writes to stderr; ensure log levels (`LOG_LEVEL`) do not surface
  secrets in shared logs.

---

## License

No licence file is present in this repository. Until one is added, treat the code as
all rights reserved and clarify usage terms with the maintainers.