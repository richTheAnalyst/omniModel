# omniModel Lead API: Frontend Developer Guide

Everything you need to build the frontend. Read sections 1-4 first (10 minutes), then build from section 5 onward.

> **Before sending:**
> Base URL: `https://omnimodel-api.onrender.com`  ·  The API key is sent separately and privately. It is not in this file.

---

## 1. What this app does

A **lead-finding and outreach tool** for a business that sells services to other businesses. A sales officer:

1. picks a **business profile** (who is selling, what they sell, where),
2. **searches** for companies by region, city and industry (Google Places),
3. sees each company **scored per offering** (e.g. "best fit: Manned Guarding, 77"),
4. optionally **analyzes a company's website** (scrapes it, an LLM extracts signals, scores improve),
5. **drafts outreach** (email, proposal letter, follow-up) for the best-fit offering,
6. **exports** the draft as PDF, Word or text.

The first customer is Simba Gate Security (Ghana). The API is **profile-driven**: all business-specific content (offerings, industries, regions, wording) comes from a profile file on the server. **Never hardcode "Simba Gate", industries, offerings or regions in the frontend.** Load them from `GET /profiles/{id}` so other businesses can be added without frontend changes.

## 2. Architecture

```
Browser / your frontend
        │  HTTPS + header X-API-Key
        ▼
FastAPI backend (Python, Docker, hosted on Render)
        ├── Google Places API ........ finds companies          (POST /search)
        ├── Playwright + Chromium .... reads a company website  (POST /analyze)
        ├── LLM via OpenRouter ....... extracts signals          (POST /analyze)
        └── Profile files (YAML) ..... offerings, sectors, templates, scoring weights
```

- **The backend is stateless.** It stores nothing between requests. The **frontend must keep the lead list, analysis results, do-not-contact flags and any status in its own state** (and, if you want, localStorage). A database is planned later.
- Scores are computed on the server. Do not recompute them in the frontend.

## 3. Access and setup

| Item | Value |
|---|---|
| Base URL | `https://omnimodel-api.onrender.com` |
| Interactive docs (try every endpoint) | `{BASE}/docs` |
| Machine-readable spec (OpenAPI) | `{BASE}/openapi.json` |
| Auth header (all endpoints except `/health`) | `X-API-Key: <key>` |
| Body format | JSON, `Content-Type: application/json` |

**Get the OpenAPI types for free (optional):**
```bash
npx openapi-typescript https://omnimodel-api.onrender.com/openapi.json -o src/api-types.d.ts
```
You can also import `/openapi.json` into Postman or Insomnia.

**CORS:** the server only accepts browser calls from origins on its allow-list. **Send the backend owner your dev and production origins** (e.g. `http://localhost:3000`, `https://app.example.com`) so they can add them. Until then the browser will block requests with a CORS error, even though the API works.

**Hosting behaviour to design for:** on a free Render plan the server sleeps when idle and the first request can take **50+ seconds**. Call `GET /health` when the app loads to wake it, and show a "starting up" message if it is slow. A paid plan removes the sleep.

**API key warning:** if you put the key in browser code, anyone can read it. For testing and internal use that is acceptable. For public use, keep the key on a server (a small Next.js/Express/Cloudflare proxy that adds the header) or ask for per-user login to be added to the backend.

## 4. Quick start (copy these to test)

```bash
BASE=https://omnimodel-api.onrender.com
KEY=your-api-key

curl $BASE/health
curl -H "X-API-Key: $KEY" $BASE/profiles
curl -H "X-API-Key: $KEY" $BASE/profiles/simba_gate

curl -X POST $BASE/search -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"profile":"simba_gate","region":"Western","city":"Tarkwa","sector":"mining","max_results":5}'
```

## 5. Typical screen flow

1. **App load:** `GET /health` (wake the server) → `GET /profiles` → pick one (show a dropdown if more than one) → `GET /profiles/{id}`.
2. **Search screen:** Region dropdown (keys of `geography`) → City dropdown (`geography[region]`, or free text) → Industry dropdown (`sectors`) → "Search" → `POST /search`.
3. **Results table**, sorted by best score (the server already sorts): company, best-fit offering label, score (0-100), phone, website, rating. Row click opens the lead detail.
4. **Lead detail:**
   - One score card per offering (`scores[offering].label` and `.score × 100`), with the best fit highlighted.
   - A bar chart of `breakdown` for the selected offering.
   - **"Analyze website"** button (only if the lead has a `website`) → `POST /analyze` → **replace the lead's `scores` and `best_offering` with the response**, show `signals`, and show `signals.existing_provider` if present.
   - Offering selector (default `best_offering`) and tabs **Email / Proposal / Follow-up** → `POST /outreach` → show in an **editable** text area, with Copy and Download buttons (`POST /export`).
   - **"Do not contact"** toggle (frontend-only for now; when on, hide the draft tabs).
5. **Settings (sidebar):** the user's business details, pre-filled from `profile.business` (`our_name`, `our_title`, `our_email`, `our_phone`). Send edited values as `business` in `/outreach` so users can override the profile defaults.

## 6. Endpoints

All endpoints except `/health` require `X-API-Key`. Scores are **0 to 1**; display as 0-100.

### GET `/health`
No key needed. → `{"status": "ok"}`

### GET `/backends`
Which LLM backends are configured on the server. → `{"backends": ["openrouter"]}`. Optional; you can ignore it. `/analyze` uses the server default if you do not send `backend`.

### GET `/profiles`
→ `{"profiles": ["simba_gate", "example_it_services"]}`

### GET `/profiles/{id}`
Everything needed to build the dropdowns.
```json
{
  "id": "simba_gate",
  "name": "Simba Gate Security",
  "country": "Ghana",
  "business": {"our_name": "Simba Gate Security Ltd", "our_title": "Business Development",
               "our_email": "info@simbatgate.com", "our_phone": "+233 053 377 1014"},
  "offerings": {"guarding": "Manned Guarding", "event_vip": "Event VIP Protection",
                "k9": "Canine K9 Security", "technical": "Technical Security"},
  "sectors": {"mining": "Mining", "bank": "Banks", "...": "..."},
  "geography": {"Greater Accra": ["Accra", "Tema", "Madina", "Spintex"],
                "Western": ["Sekondi-Takoradi", "Tarkwa"], "...": []}
}
```
Unknown id → `404`.

### POST `/search`
Find companies and score them (fast, a few seconds).

Request:
```json
{"profile": "simba_gate", "region": "Western", "city": "Tarkwa", "sector": "mining", "max_results": 10}
```
| Field | Rules |
|---|---|
| `profile` | a profile id |
| `region` | must be a key of that profile's `geography` |
| `city` | any non-empty text (normally from `geography[region]`) |
| `sector` | must be a key of that profile's `sectors` |
| `max_results` | integer 1-20, default 10 |

Response:
```json
{
  "profile": "simba_gate",
  "count": 2,
  "leads": [{
    "id": "ChIJ...",              
    "name": "Example Gold Mine Ltd",
    "address": "Tarkwa, Ghana",
    "phone": "0302 000 000",       
    "website": "https://example.com.gh",
    "rating": 4.1,                 
    "review_count": 52,            
    "region": "Western", "city": "Tarkwa", "sector": "mining",
    "best_offering": "guarding",
    "scores": {
      "guarding": {"label": "Manned Guarding", "score": 0.713,
                   "breakdown": {"offering_fit": 30.0, "sector_priority": 20.0, "size": 3.8,
                                 "footprint": 1.2, "cluster": 3.0, "buying_signals": 0.0}},
      "k9": {"label": "Canine K9 Security", "score": 0.69, "breakdown": {"...": 0}}
    }
  }]
}
```
- `phone`, `website`, `rating`, `review_count` can be `null`. Handle missing values.
- `id` is the Google place id. Use it as the React key and to identify a lead.
- Results are sorted best-first. At most 20 per search; there is no pagination.
- `breakdown` values are **points** (the weighted contribution of each factor), not 0-1. Use them for a bar chart, not as percentages.
- Scores before analysis are estimates (industry, how many companies were found nearby, review counts).
- Repeat searches with the same inputs are cached on the server, so they are fast.

### POST `/analyze`
Scrapes the company's website, extracts signals with an LLM, and returns **updated scores**. **Slow: 10-40 seconds.** Show a spinner, set a client timeout of at least 90 seconds.

Request:
```json
{"profile": "simba_gate", "url": "https://example.com.gh", "sector": "mining",
 "region": "Western", "city": "Tarkwa", "name": "Example Gold Mine Ltd", "review_count": 52}
```
Required: `profile`, `url`, `sector`, `region`, `city`. Optional: `name`, `review_count` (send them from the lead so scoring matches), `backend` (`"openrouter"`, `"ollama"` or `"claude"`; leave out to use the server default).

Response:
```json
{
  "url": "https://example.com.gh",
  "signals": {"company_name": "Example Gold Mine Ltd", "hiring": ["Security Guard"],
              "growth_signals": ["New pit opening"], "site_count": 4,
              "size_estimate": null, "existing_provider": null},
  "best_offering": "guarding",
  "scores": { "...same shape as in /search..." },
  "warning": "optional: the model did not return valid JSON, so no signals were used."
}
```
- `signals` keys depend on the profile and any value can be `null`, a string, a number or a list. Render defensively; show the object generically if needed.
- After success, **overwrite that lead's `scores` and `best_offering`** with these.
- Do not fire many `/analyze` calls in parallel (each runs a browser on the server). **Queue them, one or two at a time.**
- The server refuses URLs that point to localhost or private networks (`422`).
- Some websites block scrapers or load content with heavy JavaScript. Expect `502` for those. Let the user continue without analysis.

### POST `/outreach`
Generates a draft message from the profile's template. Fast.

Request:
```json
{"profile": "simba_gate", "kind": "email", "offering": "k9",
 "lead": {"name": "Example Gold Mine Ltd", "city": "Tarkwa", "region": "Western", "sector": "mining"},
 "business": {"our_name": "Simba Gate Security Ltd", "our_title": "Business Development",
              "our_email": "info@simbatgate.com", "our_phone": "+233 053 377 1014"}}
```
- `kind`: `"email"`, `"proposal"` or `"followup"`.
- `offering`: a key of the profile's `offerings` (usually the lead's `best_offering`).
- `lead.name` is required; `city`, `region`, `sector` are optional but give better text.
- `business` is optional; any keys you send override the profile defaults.

Response: `{"kind": "email", "text": "Subject: ...\n\nDear ... team,\n\n..."}`

`text` is plain text with `\n` line breaks. Email and follow-up start with a `Subject:` line. Display it in a `<textarea>` or an element with `white-space: pre-wrap`, never as HTML.

### POST `/export`
Turns text into a downloadable file.

Request:
```json
{"text": "the (possibly edited) draft", "format": "pdf", "title": "Proposal", "filename": "proposal_example_mine"}
```
`format`: `"pdf"` (default), `"docx"` or `"txt"`. `text` must be 1-50,000 characters. Response is the **file itself** (binary).

```ts
const res = await fetch(`${BASE}/export`, { method: "POST", headers, body: JSON.stringify(payload) });
const blob = await res.blob();
const a = document.createElement("a");
a.href = URL.createObjectURL(blob);
a.download = `${payload.filename}.${payload.format}`;   // build the name yourself, see note
a.click();
URL.revokeObjectURL(a.href);
```
> The server sets a `Content-Disposition` header, but browsers cannot read it on cross-origin calls. Build the filename in your code as shown.

## 7. Errors

| Status | Meaning | Body | What to do |
|---|---|---|---|
| 401 | Missing or wrong `X-API-Key` | `{"detail": "..."}` | Check the key |
| 404 | Unknown profile | `{"detail": "..."}` | Reload the profile list |
| 422 (string) | Bad input we checked (unknown region, sector, URL not allowed, etc.) | `{"detail": "message"}` | Show `detail` to the user |
| 422 (array) | Request shape wrong (missing field, wrong type) | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` | A bug in your request; log it |
| 502 | Google, the website or the LLM failed | `{"detail": "message"}` | Show message, allow retry |
| 503 | Server has no `API_KEY` configured | `{"detail": "..."}` | Tell the backend owner |

`detail` is a string for most errors but an **array** for request-shape errors, so check its type before displaying it.

## 8. TypeScript types and a starter client

```ts
export type Scores = Record<string, { label: string; score: number; breakdown: Record<string, number> }>;

export interface Profile {
  id: string; name: string; country: string;
  business: { our_name: string; our_title: string; our_email: string; our_phone: string };
  offerings: Record<string, string>;
  sectors: Record<string, string>;
  geography: Record<string, string[]>;
}

export interface Lead {
  id: string; name: string | null; address: string | null; phone: string | null; website: string | null;
  rating: number | null; review_count: number | null;
  region: string; city: string; sector: string;
  best_offering: string; scores: Scores;
}

export interface SearchResponse { profile: string; count: number; leads: Lead[] }
export interface AnalyzeResponse { url: string; signals: Record<string, unknown>; best_offering: string; scores: Scores; warning?: string }
export interface OutreachResponse { kind: "email" | "proposal" | "followup"; text: string }
```

```ts
const BASE = import.meta.env.VITE_API_URL;        // or process.env.NEXT_PUBLIC_API_URL
const KEY = import.meta.env.VITE_API_KEY;         // see the API key warning in section 3

async function api<T>(path: string, body?: unknown, timeoutMs = 30_000): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: body ? "POST" : "GET",
    headers: { "X-API-Key": KEY, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const d = err.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join("; ") : `Request failed (${res.status})`);
  }
  return res.json();
}

// usage
const profile = await api<Profile>("/profiles/simba_gate");
const found   = await api<SearchResponse>("/search", { profile: "simba_gate", region: "Western", city: "Tarkwa", sector: "mining", max_results: 10 });
const checked = await api<AnalyzeResponse>("/analyze", { profile: "simba_gate", url: lead.website, sector: lead.sector, region: lead.region, city: lead.city, name: lead.name, review_count: lead.review_count }, 90_000);
const draft   = await api<OutreachResponse>("/outreach", { profile: "simba_gate", kind: "email", offering: lead.best_offering, lead: { name: lead.name, city: lead.city, region: lead.region, sector: lead.sector } });
```

## 9. UI and business rules (please follow)

- **Colour the score:** green at 70 or above, amber 40-69, red below 40 (score × 100).
- **Drafts are drafts.** Always show the message in an editable box with a note: "Review before sending." The API never sends email.
- **Do not contact:** keep a per-lead flag in frontend state. When set, hide outreach drafts for that lead. The server does not enforce it.
- **Unsubscribe line:** email and follow-up templates already include one. Do not strip it when the user edits.
- **Offering names, industry names, region names:** always from the profile response. Never hardcode.
- **Before and after analysis:** make it visible which scores are estimates (not analyzed) and which include website signals.
- **Debounce / disable buttons** while a request is running. Search calls Google Places, and every analyze call uses a paid LLM, so avoid accidental repeats.
- **Empty and error states:** no results, no website on the lead, analysis failed (502), server waking up (slow first call).
- **Export filenames:** strip spaces and special characters yourself.

## 10. Known limits and what is coming

- No user accounts: one shared API key. Per-user login is planned.
- No database: nothing persists on the server. Keep state in the frontend; saving leads, status (new / contacted / won) and do-not-contact lists is planned.
- Max 20 companies per search, no pagination.
- Analysis quality depends on how much useful text the company's website has.
- No rate limiting yet: be considerate with call volume.

## 11. Checklist for the developer

- [ ] Get base URL and API key from the backend owner (privately)
- [ ] Send the backend owner your dev and production origins for CORS
- [ ] Open `{BASE}/docs` and run one search and one analyze by hand
- [ ] Build: profile load → search → results → lead detail → analyze → outreach → export
- [ ] Handle slow first request, 502 errors and `null` fields
- [ ] Keep the API key out of public code (proxy it) before real users

Questions about the backend: contact the backend owner.
