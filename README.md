# omniModel

**Company signal extraction, lead discovery, scoring and outreach — from a single browser tab.**

omniModel scrapes company websites, extracts structured business signals with an LLM,
scores the opportunity with transparent weighted rules, discovers companies by location
through Google Places, and turns everything into ready-to-send proposals and emails you
can export as PDF, DOCX or TXT.

Repository: <https://github.com/richTheAnalyst/omniModel> · Version: `0.1.0` · Python: `>= 3.14`

---

## Table of contents

- [What it does](#what-it-does)
- [Feature tour](#feature-tour)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Streamlit app](#running-the-streamlit-app)
- [Running the REST API](#running-the-rest-api)
- [CLI usage](#cli-usage)
- [Scoring model](#scoring-model)
- [Outreach templates and export](#outreach-templates-and-export)
- [Testing](#testing)
- [Dev container / Codespaces](#dev-container--codespaces)
- [Extending omniModel](#extending-omnimodel)
- [Known gaps and caveats](#known-gaps-and-caveats)
- [Security notes](#security-notes)
- [License](#license)

---

## What it does

The project answers one question for a sales team: **"Is this company worth reaching out
to, and what do I say to them?"**

It does that with four composable capabilities:

| Capability | Description |
|---|---|
| **Web scraping** | Playwright renders a page (including JS-heavy sites) and returns visible text. |
| **Signal extraction** | An LLM turns raw page text into structured JSON: pricing, hiring, tech stack, growth signals. |
| **Lead discovery** | Google Places (New) text search finds companies by industry + country + region + city, with phone, website, address and ratings. |
| **Scoring** | Deterministic weighted rules turn signals into a `0.0–1.0` score plus a per-rule breakdown. |
| **Outreach** | Deterministic templates generate a proposal letter, an outreach email and a follow-up, exportable as PDF/DOCX/TXT. |

Everything runs locally. There is no database, no queue and no cloud service beyond the
LLM provider and Google Places.

---

## Feature tour

### Streamlit UI (`streamlit_app.py`)

The app is a two-tab workspace with a persistent sidebar.

#### Sidebar

- **My business** — business name, email, phone, title, services to market, value
  proposition. These are injected into every generated proposal/email.
- **LLM backend** — radio selector listing only the backends that are actually
  configured (Ollama is always listed; OpenRouter appears when its key is set; Claude
  appears when `ANTHROPIC_API_KEY` is set). A status banner warns you if Ollama is
  selected but the server may not be running.
- **Scoring rules** — live readout of every rule name and its weight.
- Footer notes: the tech stack, and a warning that **no authentication is enabled**.

#### Tab 1 — `WEB ANALYSER`

1. **Analyze a website** — paste one URL, press **Analyze**. A `st.status` panel shows
   progress through scrape → extract → score.
2. **Batch analysis** — paste one URL per line (up to the whole list at once); invalid
   URLs are reported before anything runs.
3. **Results table** — one row per URL: URL, Score, and the count of pricing / hiring /
   tech / growth signals found, plus an `Analyzed` or `Error` status.
4. **Score breakdown** — one expander per company containing:
   - an HTML **score gauge** (green ≥ 70, amber ≥ 40, red below),
   - a **bar chart** of each rule's contribution.
5. **Outreach** — one expander per company with two columns:
   - *Extracted signals* — the raw JSON the LLM returned,
   - *Ready-to-send* — nested tabs for **Proposal letter**, **Email** (editable in a
     text area before export) and **Follow-up**, each with PDF/DOCX/TXT download buttons.
6. **Download analysis results (JSON)** — the full run, ready to hand to another system.

**Clear results** empties the session state and reruns the app.

#### Tab 2 — `WIDE RANGE SEARCH`

1. **Location pickers** — Country → Area/region → City, each cascading from the previous:
   - 31 countries are listed (`_COUNTRIES`), and all 31 also have a city list.
   - Region lists exist for Ghana (all 16 regions), USA (9 divisions), UK (4 nations),
     Canada (8 provinces), Australia (6 states), Nigeria (8), South Africa (5), Kenya (6)
     (`_AREAS_BY_COUNTRY`). Other countries skip the region step.
   - City lists exist per country (`_CITIES_BY_COUNTRY`) and per Ghana region
     (`_CITIES_BY_AREA`, derived from `_GHANA_CITIES`, which lists 49 towns and also
     carries per-city area figures).
   - Where a city list exists you can either **Select** from it or **Type manually**.
2. **Industry / business type** — free text ("software company", "hotel", "dentist", …).
3. **Max results** — 1–20 (Google Places caps a text search at 20 per request).
4. **Search companies** — builds the location string `city, region, country` and runs a
   Places text search, then optionally fetches full details for each place.
5. **Ghana region metadata** — when Ghana is selected, an info banner shows the region's
   area in km² and the number of listed cities/towns, with the full town list as a caption.
6. **Results table** — Name, Phone, Website, Address, Rating, Reviews.
7. **Companies & outreach** — one expander per company with **Contact details**
   (name, phone, website, address, rating + review count, human-readable place types) and
   **Ready-to-send** proposal / email / follow-up with the same three export buttons.

---

## How it works

```
                 ┌────────────────────────────────────────────┐
  URL list ───►  │ Playwright scraper (omnimodel/scraping)    │ ──► page text
                 └────────────────────────────────────────────┘
                                        │
                                        ▼
                 ┌────────────────────────────────────────────┐
                 │ Extraction factory (omnimodel/extraction)  │
                 │  ├─ ollama      local, free, no key        │
                 │  ├─ openrouter  cheap, many models         │
                 │  └─ claude      paid, highest quality     │
                 └────────────────────────────────────────────┘
                                        │  signals JSON
                                        ▼
                 ┌────────────────────────────────────────────┐
                 │ Weighted rules (omnimodel/scoring)        │ ──► score + breakdown
                 └────────────────────────────────────────────┘
                                        │
                                        ▼
                 ┌────────────────────────────────────────────┐
                 │ Templates (omnimodel/templates) + export  │ ──► PDF / DOCX / TXT
                 └────────────────────────────────────────────┘

  Industry + location ──► Google Places (omnimodel/places) ──► companies + contacts ──┘
```

Design points worth knowing:

- **Lazy imports.** `get_extractor()` imports the backend module only when it is selected,
  so a missing `openai` or `anthropic` install cannot break the Ollama path.
- **Fail-soft per URL.** `fetch_pages()` uses `asyncio.gather(..., return_exceptions=True)`
  and stores an empty string for failures; `_run_pipeline()` catches per-URL exceptions and
  records them in an `error` key, so one bad URL never kills a batch.
- **Retry with backoff.** OpenRouter calls go through `call_with_retry()`, which retries
  HTTP 429/500/502/503/504 with 1s, 2s, 4s, 8s, 16s delays.
- **Tolerant JSON parsing.** `parse_json()` strips markdown fences and returns
  `{"_raw": ...}` rather than raising when a model returns prose.
- **Truncation.** Extractors send the first 12,000 characters of page text to the model.
- **Session state only.** Results live in `st.session_state` (`results`, `wide_results`,
  `last_urls`); nothing is persisted server-side.

---

## Tech stack

| Layer | Choice |
|---|---|
| UI | Streamlit 1.64 (wide layout, custom CSS) |
| Tables/charts | pandas 3.0, `st.dataframe`, `st.bar_chart` |
| Scraping | Playwright 1.63 (Chromium) |
| HTTP | requests 2.34 |
| LLM — local | Ollama (`/api/chat`) |
| LLM — hosted | OpenRouter via the OpenAI SDK, Anthropic SDK |
| Places | Google Places API (New) |
| Export | reportlab (PDF), python-docx (DOCX), plain text |
| Config | dataclass + python-dotenv |
| Packaging | hatchling, `uv.lock`, console script `omnimodel` |
| Quality | pytest 9, ruff config (line length 88, target py314) |

---

## Project structure

```
omniModel/
├── streamlit_app.py              # Streamlit UI: sidebar, both tabs, all rendering (~2.4k lines)
├── pages/
│   └── 1_Lead_Finder.py          # Profile-driven lead finder (Streamlit multipage page)
├── main.py                       # Legacy FastAPI worker for the Laravel integration
├── extract.py                    # Legacy Claude profile/pitch helper used by main.py
├── pyproject.toml                # Project metadata, deps, extras, pytest + ruff config
├── uv.lock                       # Locked dependency graph
├── .env / .env.example           # Local config (gitignored) and its template
├── .python-version               # 3.14
├── .devcontainer/
│   └── devcontainer.json         # Codespaces / dev container, auto-runs the app on :8501
├── omnimodel/
│   ├── __init__.py               # Package docstring + __version__ = "0.1.0"
│   ├── __main__.py               # `python -m omnimodel` → CLI
│   ├── cli.py                    # argparse CLI: scrape / places / place / score
│   ├── config.py                 # Config dataclass, .env loading, module-level `config`
│   ├── logging.py                # setup_logging(), configures the "omnimodel" logger on import
│   ├── export.py                 # export_pdf / export_docx / export_txt
│   ├── profile_loader.py         # Loads + validates business profiles from omnimodel/profiles/*.yaml
│   ├── profiles/                 # Business profiles (who sells what, to which sectors, where)
│   │   ├── simba_gate.yaml       # Security services in Ghana
│   │   └── example_it_services.yaml  # Second example: IT services in Nigeria
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app: /health /backends /profiles /search /analyze
│   │   │                         #   /outreach /export
│   │   └── service.py            # Plain-Python logic behind those endpoints
│   ├── scraping/
│   │   └── playwright_scraper.py # fetch_page(), fetch_pages() (concurrent)
│   ├── extraction/
│   │   ├── factory.py            # get_extractor(), extract_signals(), available_backends()
│   │   ├── ollama_extractor.py   # Local Ollama backend
│   │   ├── openrouter_extractor.py # OpenRouter (OpenAI-compatible) backend
│   │   ├── claude_extractor.py   # Anthropic backend
│   │   ├── contact_extractor.py  # Contact details via OpenRouter
│   │   └── _utils.py             # call_with_retry(), parse_json()
│   ├── places/
│   │   └── google_places.py      # search_places(), search_by_location(), get_place(),
│   │                            # get_place_contacts()
│   ├── scoring/
│   │   ├── weighted_rules.py     # ScoringRule, ScoreResult, score_signals(), default_rules()
│   │   └── profile_scoring.py    # Profile-driven lead scoring (score_lead, best_offering,
│   │                            #   lead_from_signals)
│   └── templates/
│       ├── __init__.py           # generate_proposal_letter / outreach_email / followup_email
│       └── profile_templates.py  # YAML-profile outreach rendering (render())
└── tests/
    ├── test_scoring.py           # 12 tests — weighted scoring edge cases
    ├── test_factory.py            # 7 tests — backend resolution and availability
    ├── test_json_parsing.py       # 6 tests — markdown-fenced / invalid JSON
    └── test_profiles.py           # 23 tests — profile loader, profile scoring, outreach render
```

---

## Requirements

- **Python 3.14 or newer** (`pyproject.toml`: `requires-python = ">=3.14"`; `.python-version` pins `3.14`).
- **[uv](https://docs.astral.sh/uv/)** (recommended, matches `uv.lock`) or `pip`.
- **A Chromium build for Playwright** — installed once via `playwright install chromium`.
- **At least one LLM path**: a local Ollama server (free), an OpenRouter key, or an
  Anthropic key.
- **A Google Places API key** for the `WIDE RANGE SEARCH` tab and the `places` CLI command.

---

## Installation

### Option A — uv (recommended)

```bash
uv sync --extra ui --extra scraping --extra api --extra dev
uv run playwright install chromium
```

### Option B — pip

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e ".[ui,scraping,api,dev]"
playwright install chromium
```

The extras map to:

| Extra | Packages | Needed for |
|---|---|---|
| `scraping` | `playwright` | Every website analysis |
| `ui` | `streamlit`, `pandas`, `pyyaml`, `reportlab`, `python-docx` | The Streamlit app and exports |
| `api` | `fastapi`, `uvicorn`, `pyyaml`, `reportlab`, `python-docx` | The REST API in `omnimodel/api/` |
| `dev` | `pytest`, `ruff` | Tests and linting |

`requests`, `python-dotenv`, `anthropic` and `openai` are core dependencies.

Then create your config file:

```bash
cp .env.example .env            # Windows: copy .env.example .env
```

---

## Configuration

All configuration is environment-based. `omnimodel/config.py` loads `.env` from the repo
root at import time and exposes a singleton `config` object; raw environment variables
also work, and `.env` wins only where it sets the same names.

| Variable | Default | Required for | Notes |
|---|---|---|---|
| `EXTRACTION_BACKEND` | `ollama` | — | `ollama` \| `openrouter` \| `claude`. Sets the pre-selected sidebar option. |
| `OPENROUTER_API_KEY` | — | OpenRouter backend | Key from <https://openrouter.ai/keys>. Presence enables the option in the UI. |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat` | OpenRouter backend | Any OpenRouter model slug. |
| `ANTHROPIC_API_KEY` | — | Claude backend | Presence enables the option in the UI. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude backend | Any model your key can access. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama backend | Point at a remote Ollama host if needed. |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama backend | Run `ollama pull qwen2.5:7b` first. |
| `OLLAMA_TIMEOUT_S` | `120.0` | Ollama backend | Raise for large local models on CPU. |
| `GOOGLE_PLACES_API_KEY` | — | `WIDE RANGE SEARCH`, `places`, `place` | Enables Places (New) with a text-search-capable key. |
| `PLAYWRIGHT_BROWSER` | `chromium` | Scraping | Currently `chromium` is what the code launches. |
| `PLAYWRIGHT_HEADLESS` | `true` | Scraping | Parsed as `1/true/yes/on`. Set `false` to watch the browser. |
| `PLAYWRIGHT_TIMEOUT_MS` | `30000` | Scraping | Navigation and `wait_for_selector` timeout. |
| `HTTP_TIMEOUT_S` | `30.0` | Places calls | Per-request timeout. |
| `HTTP_USER_AGENT` | `omniModel/0.1 (+https://omnimodel.example)` | — | Sent by `requests` callers that use it. |
| `LOG_LEVEL` | `INFO` | — | Standard logging level name. |
| `SERVICE_API_KEY` | — | `main.py` only | Legacy FastAPI worker shared secret; every endpoint returns 503 while it is unset. |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | `omnimodel/api` only | Comma-separated frontend origins allowed to call the REST API. |

**Minimum viable setups**

```bash
# Free and local
EXTRACTION_BACKEND=ollama

# Cheap and hosted
EXTRACTION_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-...

# Highest quality
EXTRACTION_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored, as are `.streamlit/secrets.toml`, `*.pem`, `*.key` and build
artifacts — see `.gitignore`.

---

## Running the Streamlit app

```bash
streamlit run streamlit_app.py
```

Open the printed URL, usually <http://localhost:8501>.

Handy variations:

```bash
# development mode with autoreload
streamlit run streamlit_app.py --server.runOnSave true

# run on a specific port / all interfaces
streamlit run streamlit_app.py --server.port 8502 --server.address 0.0.0.0

# point the app at a different .env location
streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false
```

The app expects a `.env` at the repository root, because it resolves that path relative
to the `omnimodel` package. Run it from the repo root.

### Pages

`pages/` sits next to the entrypoint, which is what makes it a Streamlit multipage app: the
sidebar gains a page switcher with the main app and **Lead Finder**. A file added to `pages/`
appears automatically; Streamlit orders pages by the numeric prefix in the filename.

**Lead Finder** (`pages/1_Lead_Finder.py`) is the profile-driven path. It reads
`omnimodel/profiles/*.yaml`, so the business you are selling, your offerings, the sectors you
target, the regions you cover and your outreach wording all come from that file. Pick a
profile in the sidebar, choose region → city → industry, press **Search**, then score and
draft from the lead detail panel. Website analysis adds LLM signals on top of the Places data,
and the **Do not contact** checkbox hides drafts for a company for the rest of the session.

### First run checklist

1. Sidebar → **LLM backend**: pick a backend. If you pick Ollama, confirm `ollama serve`
   is running and the model is pulled, or you will see a connection error.
2. **WEB ANALYSER** → enter `https://example.com` → **Analyze**. Expect a score, a gauge,
   a breakdown chart and three outreach tabs.
3. **WIDE RANGE SEARCH** → choose Ghana → Greater Accra → Accra, type an industry, press
   **Search companies**. Expect a table of businesses.
4. **Lead Finder** page → pick a business profile → region → city → industry → **Search**.

---

## Running the REST API

```bash
uvicorn omnimodel.api.main:app --reload --port 8000
```

Then open <http://127.0.0.1:8000/docs> for interactive docs.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check. |
| `GET` | `/backends` | Extraction backends that are configured. |
| `GET` | `/profiles` | Available profile ids. |
| `GET` | `/profiles/{name}` | Dropdowns a frontend needs (offerings, sectors, geography). |
| `POST` | `/search` | Places search for a profile/region/city/sector, scored per offering. |
| `POST` | `/analyze` | Scrape one URL, extract signals with the profile schema, score it. |
| `POST` | `/outreach` | Render one email / proposal / follow-up for a lead. |
| `POST` | `/export` | Turn text into PDF / DOCX / TXT bytes. |

Errors are mapped to status codes by `omnimodel/api/service.py`: unknown profile → `404`,
bad region/sector/offering/URL → `422`, Google/website/LLM failure → `502`. `POST /analyze`
refuses non-http(s) URLs and internal addresses. There is no authentication; see Known gaps.

```bash
curl http://127.0.0.1:8000/profiles
curl -X POST http://127.0.0.1:8000/outreach -H "Content-Type: application/json" \
  -d '{"profile":"simba_gate","kind":"email","offering":"guarding",
       "lead":{"name":"Kumasi Gold Ltd","region":"Ashanti","city":"Kumasi","sector":"mining"}}'
```

---

## CLI usage

The console script `omnimodel` is declared in `pyproject.toml` and becomes available once
the project is installed (`uv sync` / `pip install -e .`). Without installing, invoke the
same CLI with `python -m omnimodel`.

```bash
omnimodel --help
omnimodel --version
python -m omnimodel --help
```

### `scrape` — scrape, extract and score in one pass

```bash
# Scrape only, print raw text per URL
omnimodel scrape https://example.com

# Scrape + LLM extraction
omnimodel scrape https://example.com --extract --backend openrouter

# Scrape + extraction + weighted score
omnimodel scrape https://example.com --extract --score

# Batch (concurrent) and write results to disk
omnimodel scrape https://a.com https://b.com --extract --score --output results.json

# Wait for a specific element before reading text
omnimodel scrape https://example.com --wait-for ".pricing-table" --extract
```

| Flag | Default | Meaning |
|---|---|---|
| `urls` (positional, 1+) | — | One URL scrapes; multiple URLs are fetched concurrently. |
| `--wait-for` | `None` | CSS selector to await before extracting text. |
| `--extract` | off | Send page text to the selected LLM backend. |
| `--score` | off | Compute a weighted score (requires `--extract`). |
| `--backend` | `EXTRACTION_BACKEND` | `ollama` \| `openrouter` \| `claude`. |
| `--output`, `-o` | stdout | Write JSON to this file instead of printing. |

### `places` — text search for companies

```bash
omnimodel places "coffee shop Seattle"
omnimodel places "software company" --max-results 10 --output places.json
omnimodel places "dentist" --lat 47.6062 --lng -122.3321 --radius 25000
```

`--lat`/`--lng` must be supplied together; they create a circular `locationBias`.

### `place` — details for a known place ID

```bash
omnimodel place ChIJryqIewBrkFQRkWfQIS8mzpc
```

### `score` — score a previously extracted signals file

```bash
omnimodel scrape https://example.com --extract -o signals.json
omnimodel score --signals signals.json --output score.json
```

---

## Scoring model

`omnimodel/scoring/weighted_rules.py` defines rules as `(name, weight, evaluate)`. Each
rule reads one key from the extracted signals, maps it to `0.0–1.0`, and the final score is
the weighted average of the rules that actually matched:

```
score = Σ(weight × contribution) / Σ(weight)     # over rules with a non-None signal
```

Default rules, tuned for B2B SaaS:

| Rule | Weight | Evaluation |
|---|---|---|
| `pricing` | 1.0 | `1.0` if any pricing info was found, else `0.0` |
| `hiring` | 1.5 | `len(hiring) / 10`, capped at `1.0` |
| `tech_stack` | 0.5 | `len(tech_stack) / 8`, capped at `1.0` |
| `growth_signals` | 2.0 | `len(growth_signals) / 5`, capped at `1.0` |

Guarantees enforced by `score_signals()`:

- missing or `None` signals are skipped (they do not drag the score down),
- contributions are clamped to `[0.0, 1.0]`,
- a rule whose `evaluate` raises contributes `0.0` instead of breaking the run,
- no matching rules yields `0.0`, never a division error.

`omnimodel/scoring/profile_scoring.py` holds a second, profile-driven model used by the
legacy path: it scores each *offering* for a lead from sector priority, size, footprint,
cluster density and buying signals, with relative weights
(`offering_fit 30, sector_priority 20, size 12.5, footprint 12.5, cluster 15,
buying_signals 10`) that a profile can override.

---

## Outreach templates and export

`omnimodel/templates/__init__.py` renders three artefacts from a signals dict plus your
sidebar business details:

| Generator | Output |
|---|---|
| `generate_proposal_letter()` | Full letter: intro, fit rationale, deliverables, 15-minute call CTA, signature block. |
| `generate_outreach_email()` | Subject + short body; editable in the UI before export. |
| `generate_followup_email()` | Subject + gentle "circling back" body. |

Placeholders degrade gracefully: a missing company name becomes "the company", missing
types become "your industry", and empty phone numbers collapse to nothing instead of
printing `None`.

`omnimodel/export.py` converts any of that text to bytes:

- `export_pdf(text)` — reportlab canvas, US Letter, 50pt margins, 14pt line leading, with
  automatic page breaks.
- `export_docx(text, title)` — python-docx document with a level-0 heading; blank lines are
  preserved as empty paragraphs.
- `export_txt(text)` — UTF-8 bytes.

In the UI, filenames are built as `{type}_{safe_company_name}.{ext}`, where the company
name is sanitised to `\w`/`-` characters by `_safe_filename()`.

---

## Testing

```bash
.venv\Scripts\python -m pytest
```

```
tests/test_scoring.py     12 passed   # weighting, clamping, exception safety, defaults
tests/test_factory.py      7 passed   # backend resolution, override, unknown backend, availability
tests/test_json_parsing.py 6 passed   # plain, fenced, unfenced, invalid, empty, nested JSON
tests/test_profiles.py    23 passed   # profile loading, path traversal, scoring, outreach render
============================ 48 passed
```

The suite is pure-logic and network-free: extraction backends, Playwright and Google Places are
never actually called. `test_factory.py` swaps the module-level `config` and restores it in a
`finally` block.

Lint config lives in `pyproject.toml` (ruff, `E/F/W/I`, line length 88). If ruff is
installed:

```bash
.venv\Scripts\python -m ruff check .
```

---

## Dev container / Codespaces

`.devcontainer/devcontainer.json` provisions a Python container, forwards port **8501**
(auto-opens the preview) and runs on attach:

```bash
streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false
```

`updateContentCommand` installs the project itself with every extra
(`pip3 install --user -e '.[ui,scraping,api,dev]'`) and then the Chromium build Playwright
needs. The image is `mcr.microsoft.com/devcontainers/python:1-3.14-bookworm`, which matches the
`requires-python = ">=3.14"` constraint.

---

## Extending omniModel

**Add an extraction backend**

1. Create `omnimodel/extraction/<name>_extractor.py` exposing
   `extract_signals(text, *, model=None, max_tokens=2048, signal_schema=None) -> dict`.
2. Register it in `omnimodel/extraction/factory.py`: add a branch in `get_extractor()`, a
   `choices` entry in `omnimodel/cli.py`, and an append in `available_backends()` guarded
   by the presence of your key.
3. Add the key/model fields to `Config.from_env()` and `.env.example`.

**Change the scoring model**

Edit `default_rules()` in `omnimodel/scoring/weighted_rules.py`, or pass your own
`list[ScoringRule]` to `score_signals()` — weights are relative, so you can scale them
freely. The sidebar prints rule names and weights automatically.

**Add a country or region to Wide Range Search**

Append to `_COUNTRIES`, then add regions to `_AREAS_BY_COUNTRY` and cities to
`_CITIES_BY_COUNTRY` (plus `_GHANA_CITIES`-style per-region data if you want the metadata
banner). `_CITIES_BY_AREA` is derived from `_GHANA_CITIES` at import time.

**Add an outreach template**

For the main app, add a `str.format` template plus a `generate_*` function in
`omnimodel/templates/__init__.py`, then add a nested `st.tabs(...)` block in
`streamlit_app.py` next to the existing Proposal/Email/Follow-up tabs.

For the profile path, add a key under `outreach:` in the profile YAML. It is rendered by
`omnimodel/templates/profile_templates.py::render` with `str.format_map`, so leave unknown
placeholders alone — anything the profile does not define is stripped rather than printed.

**Sell a different business**

Copy `omnimodel/profiles/simba_gate.yaml` to a new `.yaml` in the same folder and edit it.
`name`, `country`, `business`, `offerings`, `sectors`, `geography`, `signal_schema` and
`outreach` are required; `weights`, `buying_signal_keywords` and `context_notes` are optional.
`omnimodel/profile_loader.py` validates the file on load — a sector that scores an offering
you did not declare, or a missing `outreach` template, is rejected with a named error. The
new profile shows up in the sidebar and at `GET /profiles` with no code change. Remember to
replace the starter `context_notes` with verified local context.

**Wire in a new signal field**

Update the three `_default_schema()` dicts (Ollama, OpenRouter, Claude) so every backend
asks for the same shape, then add or reweight a rule in `default_rules()`.

---

## Known gaps and caveats

Read this section before deploying anything.

- **No authentication on the Streamlit app or the REST API.** The sidebar says so explicitly.
  Anyone who can reach the port can spend your API credits. `omnimodel/api/main.py` restricts
  CORS but has no auth of its own; put auth in front of it before exposing it publicly.
- **Two API surfaces.** `omnimodel/api/` (`uvicorn omnimodel.api.main:app`) is the maintained
  one. Root `main.py` (`uvicorn main:app --port 8001`) is the older Laravel-facing worker; it
  shares the four endpoints and now imports its scoring from the package instead of a
  root-level `scoring.py` that no longer exists. Migrate Laravel to `omnimodel/api` and delete
  `main.py` when convenient.
- **Root `extract.py` is legacy.** It is only imported by `main.py`. The maintained Claude path
  is `omnimodel/extraction/claude_extractor.py`, which honours `ANTHROPIC_MODEL`.
- **`omnimodel/logging.py` configures logging as an import side effect** (`logger =
  setup_logging()` at module scope). Importing it from a library context will reset the
  caller's root handlers. It is not currently imported by the app or CLI.
- **`PLAYWRIGHT_BROWSER` is read but ignored.** `fetch_page()` always launches
  `p.chromium.launch(...)`. Use `PLAYWRIGHT_HEADLESS=false` to watch it work.
- **Google Places caps text search at 20 results** per request, which is why `max_results`
  in the UI is limited to 20 and the request body is clamped to `min(max_results, 20)`.
  Each result with contacts enabled triggers an extra Places detail call, so a 20-result
  search makes up to 21 requests — mind your quota.
- **`_check_url()` cannot see through DNS.** It rejects literal private, loopback, link-local
  and reserved addresses plus `.local`/`.localhost`/`.internal`/`.home.arpa` hostnames, but a
  public name that resolves to a private address is still reachable.
- **Extraction quality is only as good as the page text.** Scrapers return `inner_text`
  of `<body>`; client-rendered content needs a real browser and a sensible
  `PLAYWRIGHT_TIMEOUT_MS`, and login-walled or bot-protected sites will yield nothing.
- **Scores are relative, not absolute.** The weighted rules are a heuristic over four signal
  counts, and the profile model is a heuristic over six parts. Calibrate against real outcomes
  before treating a number as a priority queue.
- **Drafts are drafts.** Both outreach generators are deterministic templates. Every message
  needs a human read before it is sent, and `context_notes` in the shipped profiles are
  placeholders your team must replace with verified local context.
- **No licence file is present** in the repository.

---

## Security notes

- `.env`, `.streamlit/secrets.toml`, `*.pem`, `*.key`, `*.p12`, `*.pfx` are gitignored —
  keep it that way and never commit real keys.
- Keys are read from the environment only; nothing is written to disk by the app.
- The app makes outbound requests to the target website, the configured LLM provider, and
  `places.googleapis.com`. Page text is sent to the LLM provider — treat scraped content as
  data, not instructions, and be aware of what your provider retains.
- `main.py` compares `X-API-Key` with `!=` (not a constant-time compare) and returns a
  generic `401 bad key`; that is acceptable for an internal service but not a hardened
  public API.
- The dev container disables CORS and XSRF protection so the Streamlit preview works. Do
  not copy those flags into a real deployment.

---

## License

No licence file has been added to this repository yet. Until one is, treat the code as
all rights reserved and clarify usage terms with the maintainers.