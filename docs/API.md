# omniModel REST API — integration reference

Base URL (local): `http://127.0.0.1:8000`
Interactive docs: `http://127.0.0.1:8000/docs` · schema at `/openapi.json`

```bash
uvicorn omnimodel.api.main:app --reload --port 8000
```

Everything business-specific — offerings, sectors, regions, outreach wording — comes from the
YAML profile you pass as `profile`. Always fetch `/profiles/{name}` first and build your
dropdowns from it rather than hardcoding keys.

## Contents

1. [Authentication](#1-authentication)
2. [Error model](#2-error-model)
3. [Endpoints](#3-endpoints)
4. [Enums available today](#4-enums-available-today)
5. [Understanding scores](#5-understanding-scores)
6. [Integration workflow](#6-integration-workflow)
7. [Limits, timeouts and cost](#7-limits-timeouts-and-cost)
8. [Client examples](#8-client-examples)
9. [Legacy Laravel API](#9-legacy-laravel-api)

---

## 1. Authentication

**There is none.** Every endpoint is open to anyone who can reach the port. Do not expose this
service publicly as-is — put auth in front of it (nginx, an API gateway, or a reverse proxy
that terminates a key). Anyone who reaches it can spend your Google Places and LLM credits.

CORS is restricted by `CORS_ORIGINS` (default `http://localhost:3000,http://localhost:5173`).
Set it in `.env` to your frontend origin:

```bash
CORS_ORIGINS=https://app.yourcompany.com
```

## 2. Error model

Every error body is `{"detail": ...}`. Two different shapes exist — handle both.

**Our errors** (`detail` is a string, human-readable, safe to show a user):

| Status | Meaning | Example |
|---|---|---|
| `404` | Unknown profile | `{"detail":"Unknown profile 'ghost'. Available: example_it_services, simba_gate"}` |
| `422` | Bad region / sector / city / offering / kind / url | `{"detail":"Unknown region 'X' for this profile. Known: Greater Accra, Ashanti, ..."}` |
| `502` | Google, the target website, or the LLM failed | `{"detail":"GOOGLE_PLACES_API_KEY is not set. Add it to your environment or .env."}` |

**Schema validation errors** (`detail` is an *array* of objects — do not render it raw):

```json
{"detail":[{"type":"less_than_equal","loc":["body","max_results"],
            "msg":"Input should be less than or equal to 20","input":99,"ctx":{"le":20}}]}
```

```ts
// Safe detail extraction — handles both shapes
function errorMessage(body: unknown): string {
  const d = (body as { detail?: unknown }).detail
  if (typeof d === "string") return d
  if (Array.isArray(d)) return d.map((e) => (e as { msg: string }).msg).join("; ")
  return "Request failed"
}
```

> The OpenAPI schema only declares `200` and `422`. It does **not** document `404` or `502`
> because they are raised at runtime — code against this table, not the generated schema.

## 3. Endpoints

### `GET /health`

```json
{ "status": "ok" }
```

Liveness only. Does not verify that API keys are present or that Playwright is installed.

### `GET /backends`

```json
{ "backends": ["ollama", "openrouter"] }
```

Extraction backends that are actually configured. `ollama` is always listed even if no Ollama
server is running, so its presence does not guarantee availability. `claude` only appears when
`ANTHROPIC_API_KEY` is set.

### `GET /profiles`

```json
{ "profiles": ["example_it_services", "simba_gate"] }
```

### `GET /profiles/{name}`

Everything a frontend needs to build its dropdowns. **Outreach templates are never returned.**

```json
{
  "id": "simba_gate",
  "name": "Simba Gate Security",
  "country": "Ghana",
  "business": {
    "our_name": "Simba Gate Security Ltd",
    "our_title": "Business Development",
    "our_email": "info@simbatgate.com",
    "our_phone": "+233 53 377 1014"
  },
  "offerings": { "guarding": "Manned Guarding", "event_vip": "Event VIP Protection",
                 "k9": "Canine K9 Security", "technical": "Technical Security" },
  "sectors":   { "mining": "Mining", "bank": "Banks", "industrial": "Industrial / factories",
                 "logistics": "Logistics / warehouses", "hospital": "Hospitals",
                 "school": "Schools / universities", "retail": "Retail / malls",
                 "hospitality": "Hotels / venues", "events": "Event organisers",
                 "office": "Offices" },
  "geography": { "Greater Accra": ["Accra", "Tema", "Madina", "Spintex"],
                 "Ashanti": ["Kumasi", "Obuasi"],
                 "Western": ["Sekondi-Takoradi", "Tarkwa"],
                 "Eastern": ["Koforidua", "Nsawam"],
                 "Northern": ["Tamale"],
                 "Central": ["Cape Coast"] }
}
```

Note the keys are machine values (use as request params) and the values are display labels.
`region` and `sector` for `GET /profiles/{name}` map to `geography` keys and `sectors` keys.

### `POST /search`

Finds companies with Google Places, then scores every offering.

```json
{ "profile": "simba_gate", "region": "Ashanti", "city": "Kumasi",
  "sector": "mining", "max_results": 10 }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `profile` | string | yes | from `/profiles` |
| `region` | string | yes | must be a key of that profile's `geography` |
| `city` | string | yes | must be non-blank; not validated against the city list |
| `sector` | string | yes | must be a key of that profile's `sectors` |
| `max_results` | int | no | default `10`, **1–20**, `>20` → 422 |

Response — `leads` is sorted best score first:

```json
{
  "profile": "simba_gate",
  "count": 1,
  "leads": [{
    "id": "ChIJq7_RRe6B3A8RNuky7HBR87o",
    "name": "Goldline Mining Ghana Limited",
    "address": "Manso Wahaso, Kumasi, Ghana",
    "phone": "053 698 5999",
    "website": "http://www.goldlinemininggroup.com/",
    "rating": 4.1,
    "review_count": 19,
    "region": "Ashanti", "city": "Kumasi", "sector": "mining",
    "scores": {
      "guarding": {
        "label": "Manned Guarding",
        "score": 0.557,
        "breakdown": { "offering_fit": 30, "sector_priority": 20.0, "size": 3.8,
                       "footprint": 1.2, "cluster": 0.8, "buying_signals": 0.0 }
      }
    },
    "best_offering": "guarding"
  }]
}
```

`phone`, `website`, `rating` and `review_count` are frequently `null` — render defensively.
Repeat identical searches are cached in-process, so a second call is free and does not bill
Google. The cache clears on restart.

### `POST /analyze`

Scrapes one URL, extracts signals with the profile's `signal_schema`, scores them.

```json
{ "profile": "simba_gate", "url": "https://example.com",
  "sector": "mining", "region": "Ashanti", "city": "Kumasi",
  "name": "Optional company name", "review_count": 19, "backend": null }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `profile` | string | yes | |
| `url` | string | yes | must be `http(s)`; see SSRF blocklist below |
| `sector` | string | yes | |
| `region`, `city` | string | yes | used for outreach context, not validated |
| `name` | string \| null | no | passed through to scoring |
| `review_count` | int \| null | no | feeds the footprint score |
| `backend` | string \| null | no | `ollama` \| `openrouter` \| `claude`; null = server default. Not in `/backends` → 422 |

```json
{
  "url": "https://example.com",
  "signals": {
    "company_name": null, "hiring": null, "growth_signals": null,
    "site_count": null, "size_estimate": null, "existing_provider": null
  },
  "scores": { "guarding": { "label": "Manned Guarding", "score": 0.55, "breakdown": {} } },
  "best_offering": "guarding"
}
```

The `signals` keys are whatever that profile's `signal_schema` defines — they differ per
profile, so read them dynamically. If the LLM returned prose instead of JSON you also get
`"warning": "The model did not return valid JSON, so no signals were used."`

**`url` is blocked** (422) when it is not `http(s)`, or resolves to loopback, private,
link-local or reserved IP, or ends in `.local`, `.localhost`, `.internal`, `.home.arpa`. This
cannot see through DNS, so a public hostname pointing at a private address still passes.

### `POST /outreach`

Renders one message. Deterministic — the same inputs always give the same text.

```json
{ "profile": "simba_gate", "kind": "email", "offering": "guarding",
  "lead": { "name": "Ashanti Cement", "region": "Ashanti",
            "city": "Kumasi", "sector": "mining" },
  "business": null }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `profile` | string | yes | |
| `kind` | enum | yes | `email` \| `proposal` \| `followup` |
| `offering` | string | yes | key from that profile's `offerings` |
| `lead.name` | string | yes | |
| `lead.region` / `lead.city` / `lead.sector` | string | no | default `""`; drive local context notes |
| `business` | object \| null | no | overrides `our_name`, `our_title`, `our_email`, `our_phone` |

```json
{ "kind": "email",
  "text": "Subject: Manned Guarding for Ashanti Cement\n\nDear Ashanti Cement team,..." }
```

`business` merges over the profile's own details, so you can send as a specific person. All
three kinds honour it:

```json
{ "business": { "our_title": "Ama Mensah, Head of Business Development" } }
```

Region-specific `context_notes` are injected when the lead's region/sector/offering matches one
in the profile. Unknown placeholders are stripped, so the text is always send-ready.

### `POST /export`

Text in, file bytes out. Used for the PDF/DOCX/TXT download buttons.

```json
{ "text": "Subject: ...", "format": "pdf",
  "title": "Proposal", "filename": "proposal" }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | yes | 1–50,000 chars |
| `format` | enum | no | `pdf` (default) \| `docx` \| `txt` |
| `title` | string | no | default `Proposal`; DOCX heading only |
| `filename` | string | no | default `document`; sanitised to `[A-Za-z0-9_-]` |

Returns raw bytes, not JSON:

| `format` | `Content-Type` | Body |
|---|---|---|
| `pdf` | `application/pdf` | `%PDF-` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `PK` zip |
| `txt` | `text/plain; charset=utf-8` | UTF-8 text |

Always carries `Content-Disposition: attachment; filename="<safe>.<format>"`.

## 4. Enums available today

Regenerate from `GET /profiles/{name}` — this is a snapshot.

**`simba_gate`** — Ghana, Simba Gate Security Ltd

- offerings: `guarding`, `event_vip`, `k9`, `technical`
- sectors: `mining`, `bank`, `industrial`, `logistics`, `hospital`, `school`, `retail`, `hospitality`, `events`, `office`
- regions: `Greater Accra`, `Ashanti`, `Western`, `Eastern`, `Northern`, `Central`

**`example_it_services`** — Nigeria, Example IT Ltd

- offerings: `managed_it`, `cyber`
- sectors: `bank`, `school`, `office`
- regions: `Lagos`, `FCT`

Region keys contain spaces (`Greater Accra`) — URL-encode them in path segments.

## 5. Understanding scores

`score` is `0.0–1.0`. `breakdown` is **points**, not fractions; `score = Σbreakdown / 100`.

| Part | Max points | Meaning |
|---|---|---|
| `offering_fit` | 30 | How well that offering suits the sector (from the profile) |
| `sector_priority` | 20 | How attractive the sector is overall (from the profile) |
| `size` | 12.5 | Staff headcount if the site states it, else a 0.3 default |
| `footprint` | 12.5 | Site count, floored by review count as a busyness proxy |
| `cluster` | 15 | Density of matches in that area |
| `buying_signals` | 10 | Hiring roles matching the profile's buying keywords, plus growth signals |

### ⚠️ Scores do not discriminate before you analyse websites

`/search` scores with **no signals**, so `sector_priority`, `size`, `buying_signals` and
`site_count` are identical for every lead in the response. That leaves two variables, and
neither is per-lead in a useful way:

- `review_count` is the only per-lead input, and its effect is gated. It changes nothing at all
  below 100 reviews and saturates at 500.
- `cluster` is `len(results) - 1`, so it is **identical for every lead** and changes with
  `max_results`. Asking for 20 results instead of 3 shifts every score in the response.

Measured `guarding` score for `simba_gate` / `mining`, by reviews and cluster size:

| cluster (= results−1) | 0 rev | 50 | 100 | 250 | 500 | 5000 |
|---|---|---|---|---|---|---|
| 0 | 0.550 | 0.550 | 0.550 | 0.569 | 0.600 | 0.600 |
| 4 | 0.580 | 0.580 | 0.580 | 0.599 | 0.630 | 0.630 |
| 9 | 0.618 | 0.618 | 0.618 | 0.636 | 0.667 | 0.667 |
| 20 | 0.700 | 0.700 | 0.700 | 0.719 | 0.750 | 0.750 |

Read down any column and every value is identical. In practice **all leads in one `/search`
response carry the same score**, so `best_offering` ranks nothing until you call `/analyze`.
Treat `/search` as a contact list and `/analyze` as the ranking step — do not present
pre-analysis scores as a priority order, and do not compare scores across two different
`max_results` values.

`breakdown` values are rounded to 1 decimal place, so components need not sum exactly.

## 6. Integration workflow

```
GET /profiles                     → pick profile id
GET /profiles/{name}              → build region / city / sector / offering dropdowns
GET /backends                     → offer only the backends that come back
POST /search                      → contact list (send review_count through to /analyze)
POST /analyze (per lead, lazily)  → real signals → meaningful scores
POST /outreach                    → draft per lead, optionally override `business`
POST /export                      → download PDF / DOCX / TXT
```

Call `/analyze` on demand, not for every lead in a batch: each call launches a Chromium browser
and one LLM request (~19s measured).

## 7. Limits, timeouts and cost

| Limit | Value |
|---|---|
| `max_results` | 20 (Google Places text-search cap; hard 422 above 20) |
| `export` text | 50,000 characters |
| Places HTTP timeout | 30s |
| Playwright navigation | 30s |
| Ollama timeout | 120s |
| **OpenRouter / Claude timeout** | **none set — inherits a 600s SDK default, retried 5×** |

Set generous client-side timeouts: `/search` ~2s, `/analyze` **60s+**.

Cost drivers: `/search` bills Google per uncached call (cache is in-process only, so it does
not survive a restart or a multi-worker deployment — with `--workers N` each worker keeps its
own cache). `/analyze` bills one Chromium launch plus one LLM call.

## 8. Client examples

```bash
curl http://127.0.0.1:8000/profiles

curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"profile":"simba_gate","region":"Ashanti","city":"Kumasi","sector":"mining","max_results":5}'

curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"profile":"simba_gate","url":"https://example.com","sector":"mining","region":"Ashanti","city":"Kumasi"}'

curl -X POST http://127.0.0.1:8000/outreach \
  -H "Content-Type: application/json" \
  -d '{"profile":"simba_gate","kind":"email","offering":"guarding",
       "lead":{"name":"Ashanti Cement","region":"Ashanti","city":"Kumasi","sector":"mining"}}'

curl -X POST http://127.0.0.1:8000/export \
  -H "Content-Type: application/json" \
  -d '{"text":"Subject: Proposal","format":"pdf","filename":"proposal"}' \
  -o proposal.pdf
```

```ts
const API = "http://127.0.0.1:8000"

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  if (!res.ok) throw new Error(errorMessage(await res.json()))
  return res.json() as Promise<T>
}

const profile = await call<ProfileDetail>("/profiles/simba_gate")
const found = await call<SearchResponse>("/search", {
  method: "POST",
  body: JSON.stringify({
    profile: "simba_gate", region: "Ashanti",
    city: "Kumasi", sector: "mining", max_results: 10,
  }),
})
```

```python
import httpx

API = "http://127.0.0.1:8000"

def post(path, payload):
    r = httpx.post(f"{API}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

leads = post("/search", {
    "profile": "simba_gate", "region": "Ashanti",
    "city": "Kumasi", "sector": "mining", "max_results": 10,
})

for lead in leads["leads"][:5]:
    if not lead["website"]:
        continue
    detail = post("/analyze", {
        "profile": "simba_gate", "url": lead["website"],
        "sector": lead["sector"], "region": lead["region"], "city": lead["city"],
        "name": lead["name"], "review_count": lead["review_count"],
    })
    best = detail["best_offering"]
    print(f"{detail['scores'][best]['score']:.3f}  {best}  {lead['name']}")
```

## 9. Legacy Laravel API

`main.py` at the repo root is the older four-endpoint worker your Laravel app calls. It is
separate from everything above and is **not** superseded automatically.

```bash
uvicorn main:app --port 8001
```

| Method | Path | Header |
|---|---|---|
| `POST` | `/discover` | `X-API-Key` |
| `POST` | `/profile` | `X-API-Key` |
| `POST` | `/pitch` | `X-API-Key` |
| `POST` | `/score` | `X-API-Key` + optional `?profile=` |

Set `SERVICE_API_KEY` or every endpoint returns `503`; a wrong or missing header returns `401`.
Key comparison is `!=`, not constant-time, and the error message is a generic `bad key` —
acceptable internally, not for a public API. `/discover` returns `503` without
`GOOGLE_PLACES_API_KEY`. `/profile` and `/pitch` call Claude and bill tokens; `/pitch` will
`500` on an unknown `service` name.

Prefer migrating Laravel to `omnimodel/api`; then `main.py` and `extract.py` can be deleted.