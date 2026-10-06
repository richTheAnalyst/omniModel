"""omniModel Streamlit UI."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pandas as pd
import streamlit as st

from omnimodel.config import config
from omnimodel.export import export_docx, export_pdf, export_txt
from omnimodel.extraction.factory import available_backends, get_extractor
from omnimodel.places.google_places import (
    get_place_contacts,
    search_by_location,
)
from omnimodel.scoring.weighted_rules import (
    default_rules,
    score_signals,
)
from omnimodel.scraping.playwright_scraper import fetch_pages
from omnimodel.templates import (
    generate_followup_email,
    generate_outreach_email,
    generate_proposal_letter,
)

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="omniModel",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# CSS
# =============================================================================

st.markdown(
    """
    <style>
        /* Main application container */
        .block-container {
            max-width: 100% !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }

        /* Metric cards */
        div[data-testid="stMetric"] {
            background: linear-gradient(
                135deg,
                #667eea 0%,
                #764ba2 100%
            );
            border-radius: 12px;
            padding: 1rem;
            color: white;
        }

        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] p {
            color: white !important;
        }

        /* Expanders */
        div[data-testid="stExpander"] {
            border-radius: 12px;
            border: 1px solid rgba(128, 128, 128, 0.20);
            overflow: hidden;
        }

        /* Markdown spacing */
        .stMarkdown,
        .stMarkdown p {
            line-height: 1.6;
        }

        /* Columns */
        div[data-testid="stColumn"] {
            padding: 0 0.4rem;
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: transparent;
        }

        ::-webkit-scrollbar-thumb {
            background: rgba(128, 128, 128, 0.45);
            border-radius: 6px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: rgba(128, 128, 128, 0.65);
        }

        /* Tabs */
        [role="tab"] {
            font-weight: 600 !important;
            padding-left: 1.25rem !important;
            padding-right: 1.25rem !important;
        }

        [role="tab"]:hover {
            background-color: rgba(128, 128, 128, 0.08) !important;
            border-radius: 8px 8px 0 0;
        }

        [role="tab"][aria-selected="true"] {
            background-color: rgba(128, 128, 128, 0.12) !important;
            border-radius: 8px 8px 0 0;
        }

        /* Buttons */
        .stButton > button {
            border-radius: 8px;
        }

        .stDownloadButton > button {
            border-radius: 8px;
            width: 100%;
        }

        /* Dataframes */
        div[data-testid="stDataFrame"] {
            border-radius: 10px;
            overflow: hidden;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# HELPERS
# =============================================================================


def _score_breakdown_df(
    breakdown: dict[str, Any] | None,
) -> pd.DataFrame:
    """Convert score breakdown dictionary into a DataFrame."""

    if not breakdown:
        return pd.DataFrame(
            {
                "rule": [],
                "score": [],
            }
        )

    return pd.DataFrame(
        [
            {
                "rule": rule,
                "score": score,
            }
            for rule, score in breakdown.items()
        ]
    ).set_index("rule")


def _score_gauge(score: float | int | None) -> str:
    """Render a simple HTML score gauge."""

    try:
        numeric_score = float(score or 0)
    except (TypeError, ValueError):
        numeric_score = 0.0

    pct = max(
        0,
        min(
            100,
            int(numeric_score * 100),
        ),
    )

    if pct >= 70:
        color = "#22c55e"
    elif pct >= 40:
        color = "#f59e0b"
    else:
        color = "#ef4444"

    return (
        '<div style="text-align:center;padding:10px;">'
        f'<div style="font-size:48px;font-weight:800;color:{color};">'
        f"{pct}"
        "</div>"
        '<div style="font-size:12px;color:#6b7280;">'
        "SCORE"
        "</div>"
        '<div style="margin:8px auto 0;'
        "width:100%;"
        "height:8px;"
        "background:#e5e7eb;"
        'border-radius:4px;">'
        f'<div style="width:{pct}%;'
        "height:100%;"
        f"background:{color};"
        'border-radius:4px;"></div>'
        "</div>"
        "</div>"
    )


def _safe_filename(value: str) -> str:
    """Convert arbitrary text into a safe filename component."""

    value = str(value).strip()

    value = re.sub(
        r"[^\w\-]+",
        "_",
        value,
        flags=re.UNICODE,
    )

    value = re.sub(
        r"_+",
        "_",
        value,
    )

    value = value.strip("_")

    return value or "company"


def _template_context(
    *,
    our_name: str,
    our_title: str,
    our_email: str,
    our_phone: str,
    our_services: str,
    our_value_prop: str,
) -> dict[str, str]:
    """Build common context passed to outreach templates."""

    return {
        "our_name": our_name,
        "our_title": our_title,
        "our_email": our_email,
        "our_phone": our_phone,
        "deliverables": our_services,
        "value_prop": our_value_prop,
    }


def _render_download_buttons(
    *,
    text: str,
    title: str,
    filename_prefix: str,
    filename_name: str,
    key_prefix: str,
) -> None:
    """Render PDF, DOCX and TXT export buttons."""

    safe_name = _safe_filename(filename_name)

    col_pdf, col_docx, col_txt = st.columns(3)

    with col_pdf:
        st.download_button(
            label="PDF",
            data=export_pdf(text),
            file_name=f"{filename_prefix}_{safe_name}.pdf",
            mime="application/pdf",
            key=f"{key_prefix}_pdf",
            width="stretch",
        )

    with col_docx:
        st.download_button(
            label="DOCX",
            data=export_docx(
                text,
                title,
            ),
            file_name=f"{filename_prefix}_{safe_name}.docx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            key=f"{key_prefix}_docx",
            width="stretch",
        )

    with col_txt:
        st.download_button(
            label="TXT",
            data=export_txt(text),
            file_name=f"{filename_prefix}_{safe_name}.txt",
            mime="text/plain",
            key=f"{key_prefix}_txt",
            width="stretch",
        )


def _run_pipeline(
    urls: list[str],
    backend: str,
) -> dict[str, Any]:
    """Scrape URLs, extract signals and score them."""

    pages = asyncio.run(
        fetch_pages(urls)
    )

    extractor = get_extractor(
        backend
    )

    rules = default_rules()

    results: dict[str, Any] = {}

    for url, page_text in pages.items():
        if not page_text:
            results[url] = {
                "signals": {},
                "score": 0,
                "breakdown": {},
                "error": "No page content was returned.",
            }
            continue

        try:
            signals = extractor(
                page_text
            )

            if signals is None:
                signals = {}

            scored = score_signals(
                signals,
                rules,
            )

            results[url] = {
                "signals": signals,
                "score": scored.score,
                "breakdown": scored.breakdown,
            }

        except Exception as exc:
            results[url] = {
                "signals": {},
                "score": 0,
                "breakdown": {},
                "error": str(exc),
            }

    return results


def _run_wide_search(
    query: str,
    location: str,
    *,
    max_results: int = 20,
    fetch_contacts: bool = True,
) -> list[dict[str, Any]]:
    """Search Google Places and normalize company results."""

    places = search_by_location(
        query,
        location,
        max_results=max_results,
    )

    results: list[dict[str, Any]] = []

    for place in places:
        display_name = (
            place.get("displayName")
            or {}
        )

        entry = {
            "id": place.get("id"),
            "name": display_name.get("text"),
            "address": place.get(
                "formattedAddress"
            ),
            "phone": place.get(
                "nationalPhoneNumber"
            ),
            "website": place.get(
                "websiteUri"
            ),
            "types": place.get(
                "types"
            )
            or [],
            "rating": place.get(
                "rating"
            ),
            "review_count": place.get(
                "userRatingCount"
            )
            or 0,
            "contacts": None,
        }

        if (
            fetch_contacts
            and place.get("id")
        ):
            try:
                entry["contacts"] = (
                    get_place_contacts(
                        place["id"]
                    )
                )
            except Exception:
                entry["contacts"] = None

        results.append(
            entry
        )

    return results


def _render_contacts(
    place: dict[str, Any],
) -> None:
    """Render company contact information."""

    contacts = (
        place.get("contacts")
        or {}
    )

    name = (
        contacts.get("name")
        or place.get("name")
        or "-"
    )

    phone = (
        contacts.get("phone")
        or place.get("phone")
        or "-"
    )

    website = (
        contacts.get("website")
        or place.get("website")
        or "-"
    )

    address = (
        contacts.get("address")
        or place.get("address")
        or "-"
    )

    rating = (
        contacts.get("rating")
        or place.get("rating")
    )

    reviews = (
        contacts.get("review_count")
        or place.get("review_count")
        or 0
    )

    types = (
        contacts.get("types")
        or place.get("types")
        or []
    )

    st.markdown(
        f"**{name}**"
    )

    st.markdown(
        f"**Phone:** {phone}"
    )

    if website != "-":
        st.markdown(
            f"**Website:** {website}"
        )
    else:
        st.markdown(
            "**Website:** Not available"
        )

    st.markdown(
        f"**Address:** {address}"
    )

    if rating is not None:
        st.markdown(
            f"**Rating:** {rating} "
            f"({reviews} reviews)"
        )

    if types:
        readable_types = [
            str(item).replace(
                "_",
                " ",
            ).title()
            for item in types[:4]
        ]

        st.markdown(
            "**Type:** "
            + ", ".join(
                readable_types
            )
        )


# =============================================================================
# LOCATION DATA
# =============================================================================


_COUNTRIES = [
    "United States",
    "Canada",
    "United Kingdom",
    "Australia",
    "Germany",
    "France",
    "Spain",
    "Italy",
    "Netherlands",
    "Sweden",
    "Norway",
    "Denmark",
    "Finland",
    "Belgium",
    "Switzerland",
    "Austria",
    "Ireland",
    "New Zealand",
    "Japan",
    "South Korea",
    "India",
    "Brazil",
    "Mexico",
    "Argentina",
    "Singapore",
    "Hong Kong",
    "United Arab Emirates",
    "Ghana",
    "Nigeria",
    "South Africa",
    "Kenya",
]


_CITIES_BY_COUNTRY = {
    "United States": [
        "New York",
        "Los Angeles",
        "Chicago",
        "Houston",
        "Phoenix",
        "Philadelphia",
        "San Antonio",
        "San Diego",
        "Dallas",
        "San Jose",
        "Austin",
        "Seattle",
        "Denver",
        "Boston",
        "Miami",
    ],
    "Canada": [
        "Toronto",
        "Montreal",
        "Vancouver",
        "Calgary",
        "Ottawa",
    ],
    "United Kingdom": [
        "London",
        "Manchester",
        "Birmingham",
        "Edinburgh",
        "Liverpool",
    ],
    "Australia": [
        "Sydney",
        "Melbourne",
        "Brisbane",
        "Perth",
        "Adelaide",
    ],
    "Germany": [
        "Berlin",
        "Munich",
        "Hamburg",
        "Frankfurt",
        "Cologne",
    ],
    "France": [
        "Paris",
        "Marseille",
        "Lyon",
        "Toulouse",
        "Nice",
    ],
    "Spain": [
        "Madrid",
        "Barcelona",
        "Valencia",
        "Seville",
        "Malaga",
    ],
    "Italy": [
        "Rome",
        "Milan",
        "Naples",
        "Florence",
        "Venice",
    ],
    "Netherlands": [
        "Amsterdam",
        "Rotterdam",
        "The Hague",
        "Utrecht",
    ],
    "Sweden": [
        "Stockholm",
        "Gothenburg",
        "Malmo",
        "Uppsala",
    ],
    "Norway": [
        "Oslo",
        "Bergen",
        "Trondheim",
        "Stavanger",
    ],
    "Denmark": [
        "Copenhagen",
        "Aarhus",
        "Odense",
        "Aalborg",
    ],
    "Finland": [
        "Helsinki",
        "Espoo",
        "Tampere",
        "Turku",
    ],
    "Belgium": [
        "Brussels",
        "Antwerp",
        "Ghent",
        "Bruges",
    ],
    "Switzerland": [
        "Zurich",
        "Geneva",
        "Basel",
        "Bern",
    ],
    "Austria": [
        "Vienna",
        "Graz",
        "Linz",
        "Salzburg",
    ],
    "Ireland": [
        "Dublin",
        "Cork",
        "Galway",
        "Limerick",
    ],
    "New Zealand": [
        "Auckland",
        "Wellington",
        "Christchurch",
        "Hamilton",
    ],
    "Japan": [
        "Tokyo",
        "Osaka",
        "Kyoto",
        "Yokohama",
        "Nagoya",
    ],
    "South Korea": [
        "Seoul",
        "Busan",
        "Incheon",
        "Daegu",
        "Daejeon",
    ],
    "India": [
        "Mumbai",
        "Delhi",
        "Bangalore",
        "Hyderabad",
        "Chennai",
    ],
    "Brazil": [
        "Sao Paulo",
        "Rio de Janeiro",
        "Brasilia",
        "Salvador",
    ],
    "Mexico": [
        "Mexico City",
        "Guadalajara",
        "Monterrey",
        "Puebla",
    ],
    "Argentina": [
        "Buenos Aires",
        "Cordoba",
        "Rosario",
        "Mendoza",
    ],
    "Singapore": [
        "Singapore",
    ],
    "Hong Kong": [
        "Hong Kong",
    ],
    "United Arab Emirates": [
        "Dubai",
        "Abu Dhabi",
        "Sharjah",
    ],
    "Ghana": [
        "Accra",
        "Kumasi",
        "Tamale",
        "Cape Coast",
        "Takoradi",
    ],
    "Nigeria": [
        "Lagos",
        "Kano",
        "Ibadan",
        "Abuja",
        "Port Harcourt",
    ],
    "South Africa": [
        "Johannesburg",
        "Cape Town",
        "Durban",
        "Pretoria",
        "Port Elizabeth",
    ],
    "Kenya": [
        "Nairobi",
        "Mombasa",
        "Kisumu",
        "Nakuru",
        "Eldoret",
    ],
}


_GHANA_REGIONS = [
    "Greater Accra",
    "Ashanti",
    "Northern",
    "Western",
    "Eastern",
    "Central",
    "Volta",
    "Bono",
    "Upper East",
    "Upper West",
    "Bono East",
    "Oti",
    "Western North",
    "Savannah",
    "Ahafo",
    "North East",
]


_GHANA_CITIES = {
    "Greater Accra": [
        (
            "Accra",
            "20.4 (Metro) / 199.4 (urban)",
        ),
        (
            "Tema",
            "87.8 (Metro District)",
        ),
        ("Madina", None),
        ("Teshie", None),
        ("Nungua", None),
        ("Ashaiman", None),
        ("Dodowa", None),
    ],
    "Ashanti": [
        (
            "Kumasi",
            "299 (city) / 214.3 (Metro District)",
        ),
        ("Obuasi", None),
        ("Ejisu", None),
        ("Nkawie", None),
        ("Mampong", None),
    ],
    "Northern": [
        (
            "Tamale",
            "750 (city) / 647 (Metro District)",
        ),
        ("Savelugu", None),
        ("Yendi", None),
    ],
    "Western": [
        ("Sekondi-Takoradi", None),
        ("Tarkwa", None),
    ],
    "Eastern": [
        ("Koforidua", None),
        ("Akim Oda", None),
        ("Suhum", None),
        ("Nsawam", None),
    ],
    "Central": [
        ("Cape Coast", None),
        ("Elmina", None),
        ("Winneba", None),
        ("Swedru", None),
    ],
    "Volta": [
        ("Ho", None),
        ("Keta", None),
        ("Aflao", None),
        ("Hohoe", None),
    ],
    "Bono": [
        ("Sunyani", None),
        ("Berekum", None),
    ],
    "Upper East": [
        ("Bolgatanga", None),
        ("Bawku", None),
        ("Navrongo", None),
        ("Zuarungu", None),
    ],
    "Upper West": [
        ("Wa", None),
        ("Lawra", None),
        ("Tumu", None),
        ("Nadowli", None),
    ],
    "Bono East": [
        ("Techiman", None),
        ("Atebubu", None),
    ],
    "Oti": [
        ("Dambai", None),
    ],
    "Western North": [
        ("Sefwi-Wiawso", None),
        ("Bibiani", None),
    ],
    "Savannah": [
        ("Damongo", None),
    ],
    "Ahafo": [
        ("Goaso", None),
    ],
    "North East": [
        ("Nalerigu", None),
        ("Gambaga", None),
        ("Walewale", None),
    ],
}


_GHANA_REGION_AREAS = {
    "Northern": "70,384",
    "Savannah": "34,790",
    "Bono East": "23,248",
    "Ashanti": "24,389",
    "Western": "23,921",
    "Volta": "20,570",
    "Eastern": "19,323",
    "Upper West": "18,476",
    "Bono": "11,113",
    "Oti": "11,066",
    "Western North": "10,079",
    "Central": "9,826",
    "Upper East": "8,842",
    "Ahafo": "5,196",
    "Greater Accra": "3,245",
}


_AREAS_BY_COUNTRY = {
    "Ghana": _GHANA_REGIONS,
    "United States": [
        "Northeast",
        "Southeast",
        "Midwest",
        "Southwest",
        "West",
        "New England",
        "Pacific",
        "Mountain",
        "Atlantic",
    ],
    "United Kingdom": [
        "England",
        "Scotland",
        "Wales",
        "Northern Ireland",
    ],
    "Canada": [
        "Ontario",
        "Quebec",
        "British Columbia",
        "Alberta",
        "Manitoba",
        "Saskatchewan",
        "Nova Scotia",
        "New Brunswick",
    ],
    "Australia": [
        "New South Wales",
        "Victoria",
        "Queensland",
        "Western Australia",
        "South Australia",
        "Tasmania",
    ],
    "Nigeria": [
        "Lagos",
        "FCT",
        "Kano",
        "Rivers",
        "Oyo",
        "Delta",
        "Kaduna",
        "Enugu",
    ],
    "South Africa": [
        "Gauteng",
        "Western Cape",
        "KwaZulu-Natal",
        "Eastern Cape",
        "Mpumalanga",
    ],
    "Kenya": [
        "Nairobi",
        "Coast",
        "Rift Valley",
        "Eastern",
        "Central",
        "Western",
    ],
}


_CITIES_BY_AREA: dict[str, list[str]] = {}

for region_name, cities in _GHANA_CITIES.items():
    _CITIES_BY_AREA[
        f"Ghana|{region_name}"
    ] = [
        city_name
        for city_name, _ in cities
    ]


# =============================================================================
# SESSION STATE
# =============================================================================


SESSION_DEFAULTS = {
    "results": None,
    "wide_results": None,
    "last_urls": [],
}


for state_key, default_value in SESSION_DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[
            state_key
        ] = default_value


# =============================================================================
# SIDEBAR
# =============================================================================


with st.sidebar:
    st.markdown(
        "# omniModel"
    )

    st.caption(
        "Company signal extraction, "
        "lead scoring and outreach."
    )

    st.divider()

    st.markdown(
        "### My business"
    )

    st.caption(
        "These details are used when generating "
        "proposal letters and outreach emails."
    )

    our_name = st.text_input(
        "Business name",
        value="Your Company",
        key="business_name",
    )

    our_email = st.text_input(
        "Email",
        value="hello@yourcompany.com",
        key="business_email",
    )

    our_phone = st.text_input(
        "Phone",
        value="",
        key="business_phone",
    )

    our_title = st.text_input(
        "Title",
        value="Business Development",
        key="business_title",
    )

    our_services = st.text_area(
        "Services to market",
        value=(
            "- Faster, more reliable operations\n"
            "- Cost savings through automation\n"
            "- Better customer experience"
        ),
        height=110,
        key="business_services",
    )

    our_value_prop = st.text_input(
        "Value proposition",
        value="optimize operations and grow revenue",
        key="business_value_prop",
    )

    st.divider()

    st.markdown(
        "### LLM backend"
    )

    backends = available_backends()

    if not backends:
        st.error(
            "No extraction backends are available."
        )
        st.stop()

    default_backend_index = 0

    if (
        config.extraction_backend
        in backends
    ):
        default_backend_index = (
            backends.index(
                config.extraction_backend
            )
        )

    backend = st.radio(
        "Backend",
        options=backends,
        index=default_backend_index,
        key="llm_backend",
        help=(
            "Choose the model backend used "
            "for signal extraction."
        ),
    )

    backend_name = str(
        backend
    ).lower()

    if backend_name == "openrouter":
        st.success(
            "OpenRouter active"
        )

    elif backend_name == "ollama":
        st.warning(
            "Ollama selected. Make sure "
            "`ollama serve` is running."
        )

    elif backend_name == "claude":
        st.info(
            "Claude selected. "
            "ANTHROPIC_API_KEY is required."
        )

    else:
        st.info(
            f"{backend} selected."
        )

    st.divider()

    st.markdown(
        "### Scoring rules"
    )

    for rule in default_rules():
        st.markdown(
            f"**{rule.name}**  \n"
            f"Weight: `{rule.weight}`"
        )

    st.divider()

    st.caption(
        "Playwright · LLM extraction · "
        "Google Places · Streamlit"
    )

    st.caption(
        "No authentication is currently enabled."
    )


# =============================================================================
# MAIN APPLICATION
# =============================================================================


st.markdown(
    "# omniModel"
)

st.caption(
    "Discover companies, analyze their websites, "
    "score business signals and generate outreach."
)

tab_analyze, tab_wide = st.tabs(
    [
        "WEB ANALYSER",
        "WIDE RANGE SEARCH",
    ]
)


# =============================================================================
# TAB 1
# WEB ANALYSER
# =============================================================================


with tab_analyze:
    st.markdown(
        "## Web Analyser"
    )

    st.caption(
        "Scrape a company website, extract business signals, "
        "score the opportunity and generate outreach."
    )

    st.write("")

    # -------------------------------------------------------------------------
    # Single URL analysis
    # -------------------------------------------------------------------------

    st.markdown(
        "### Analyze a website"
    )

    url = st.text_input(
        "Website URL",
        placeholder="https://example.com",
        help=(
            "Enter a company website using "
            "http:// or https://."
        ),
        key="analyzer_url",
    )

    col_analyze, col_clear = st.columns(
        [1, 4]
    )

    with col_analyze:
        analyze = st.button(
            "Analyze",
            type="primary",
            width="stretch",
            key="analyze_single_url",
        )

    with col_clear:
        clear_results = st.button(
            "Clear results",
            key="clear_analysis_results",
        )

        if clear_results:
            st.session_state.results = None
            st.session_state.last_urls = []
            st.rerun()

    if analyze:
        cleaned_url = url.strip()

        if not cleaned_url:
            st.warning(
                "Enter a website URL."
            )

        elif not cleaned_url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            st.error(
                "URL must start with "
                "http:// or https://"
            )

        else:
            with st.status(
                "Running analysis...",
                expanded=True,
            ) as status:
                st.write(
                    "Scraping page with Playwright..."
                )

                try:
                    analysis_results = (
                        _run_pipeline(
                            [cleaned_url],
                            backend,
                        )
                    )

                    st.session_state.results = (
                        analysis_results
                    )

                    st.session_state.last_urls = [
                        cleaned_url
                    ]

                    status.update(
                        label="Analysis complete",
                        state="complete",
                        expanded=False,
                    )

                except Exception as exc:
                    status.update(
                        label="Analysis failed",
                        state="error",
                        expanded=True,
                    )

                    st.error(
                        f"Pipeline failed: {exc}"
                    )

    # -------------------------------------------------------------------------
    # Batch analysis
    # -------------------------------------------------------------------------

    st.write("")
    st.markdown(
        "### Batch analysis"
    )

    batch_text = st.text_area(
        "URLs",
        placeholder=(
            "https://example.com\n"
            "https://another.com"
        ),
        height=120,
        help="Enter one URL per line.",
        key="batch_analysis_urls",
    )

    col_batch, _ = st.columns(
        [1, 4]
    )

    with col_batch:
        batch_run = st.button(
            "Run batch",
            width="stretch",
            key="run_batch_analysis",
        )

    if batch_run:
        urls = [
            value.strip()
            for value
            in batch_text.splitlines()
            if value.strip()
        ]

        if not urls:
            st.warning(
                "Enter at least one URL."
            )

        else:
            invalid_urls = [
                value
                for value in urls
                if not value.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ]

            if invalid_urls:
                st.error(
                    "The following URLs are invalid:\n\n"
                    + "\n".join(
                        f"- {value}"
                        for value in invalid_urls
                    )
                )

            else:
                with st.status(
                    f"Processing {len(urls)} URLs...",
                    expanded=True,
                ) as status:
                    try:
                        batch_results = (
                            _run_pipeline(
                                urls,
                                backend,
                            )
                        )

                        st.session_state.results = (
                            batch_results
                        )

                        st.session_state.last_urls = (
                            urls
                        )

                        status.update(
                            label=(
                                f"Processed "
                                f"{len(urls)} URLs"
                            ),
                            state="complete",
                            expanded=False,
                        )

                    except Exception as exc:
                        status.update(
                            label="Batch failed",
                            state="error",
                            expanded=True,
                        )

                        st.error(
                            f"Batch analysis failed: {exc}"
                        )

    # -------------------------------------------------------------------------
    # Analysis results
    # -------------------------------------------------------------------------

    results = (
        st.session_state.results
    )

    if results:
        st.divider()

        st.markdown(
            "## Results"
        )

        rows = []

        for result_url, data in results.items():
            signals = (
                data.get("signals")
                or {}
            )

            rows.append(
                {
                    "URL": result_url,
                    "Score": round(
                        float(
                            data.get(
                                "score",
                                0,
                            )
                            or 0
                        ),
                        3,
                    ),
                    "Pricing": len(
                        signals.get(
                            "pricing"
                        )
                        or []
                    ),
                    "Hiring": len(
                        signals.get(
                            "hiring"
                        )
                        or []
                    ),
                    "Tech": len(
                        signals.get(
                            "tech_stack"
                        )
                        or []
                    ),
                    "Growth": len(
                        signals.get(
                            "growth_signals"
                        )
                        or []
                    ),
                    "Status": (
                        "Error"
                        if data.get("error")
                        else "Analyzed"
                    ),
                }
            )

        results_df = pd.DataFrame(
            rows
        )

        st.dataframe(
            results_df,
            width="stretch",
            hide_index=True,
        )

        # ---------------------------------------------------------------------
        # Score breakdown
        # ---------------------------------------------------------------------

        st.write("")
        st.markdown(
            "### Score breakdown"
        )

        for result_url, data in results.items():
            signals = (
                data.get("signals")
                or {}
            )

            company_name = (
                signals.get(
                    "company_name"
                )
                or result_url
            )

            score = float(
                data.get(
                    "score",
                    0,
                )
                or 0
            )

            with st.expander(
                (
                    f"{company_name} · "
                    f"Score {round(score, 3)}"
                ),
                expanded=False,
            ):
                if data.get("error"):
                    st.warning(
                        data["error"]
                    )

                col_gauge, col_breakdown = (
                    st.columns(
                        [1, 2]
                    )
                )

                with col_gauge:
                    st.markdown(
                        _score_gauge(
                            score
                        ),
                        unsafe_allow_html=True,
                    )

                with col_breakdown:
                    chart_df = (
                        _score_breakdown_df(
                            data.get(
                                "breakdown"
                            )
                        )
                    )

                    if not chart_df.empty:
                        st.bar_chart(
                            chart_df
                        )

                    else:
                        st.caption(
                            "No scoring rules matched."
                        )

        # ---------------------------------------------------------------------
        # Outreach
        # ---------------------------------------------------------------------

        st.write("")
        st.markdown(
            "### Outreach"
        )

        st.caption(
            "Generate proposal letters, outreach emails "
            "and follow-up messages from extracted signals."
        )

        context = _template_context(
            our_name=our_name,
            our_title=our_title,
            our_email=our_email,
            our_phone=our_phone,
            our_services=our_services,
            our_value_prop=our_value_prop,
        )

        for index, (
            result_url,
            data,
        ) in enumerate(
            results.items()
        ):
            signals_data = (
                data.get("signals")
                or {}
            )

            company_name = (
                signals_data.get(
                    "company_name"
                )
                or result_url
            )

            with st.expander(
                (
                    f"{company_name} · "
                    f"{result_url}"
                ),
                expanded=False,
            ):
                col_signals, col_outreach = (
                    st.columns(
                        [1, 2]
                    )
                )

                with col_signals:
                    st.markdown(
                        "#### Extracted signals"
                    )

                    if signals_data:
                        st.json(
                            signals_data
                        )
                    else:
                        st.info(
                            "No signals were extracted."
                        )

                with col_outreach:
                    st.markdown(
                        "#### Ready-to-send"
                    )

                    outreach_signals = {
                        "company_name": (
                            company_name
                        ),
                        "types": (
                            signals_data.get(
                                "tech_stack"
                            )
                            or []
                        ),
                        "website": (
                            result_url
                        ),
                    }

                    proposal_tab, email_tab, followup_tab = (
                        st.tabs(
                            [
                                "Proposal letter",
                                "Email",
                                "Follow-up",
                            ]
                        )
                    )

                    with proposal_tab:
                        try:
                            proposal_text = (
                                generate_proposal_letter(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            st.markdown(
                                proposal_text
                            )

                            _render_download_buttons(
                                text=proposal_text,
                                title=(
                                    f"Proposal for "
                                    f"{company_name}"
                                ),
                                filename_prefix="proposal",
                                filename_name=company_name,
                                key_prefix=(
                                    f"analysis_"
                                    f"proposal_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Proposal generation "
                                f"failed: {exc}"
                            )

                    with email_tab:
                        try:
                            generated_email = (
                                generate_outreach_email(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            email_text = st.text_area(
                                "Edit email",
                                value=generated_email,
                                height=220,
                                key=(
                                    f"analysis_email_"
                                    f"edit_{index}"
                                ),
                            )

                            _render_download_buttons(
                                text=email_text,
                                title=(
                                    f"Email for "
                                    f"{company_name}"
                                ),
                                filename_prefix="email",
                                filename_name=company_name,
                                key_prefix=(
                                    f"analysis_"
                                    f"email_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Email generation "
                                f"failed: {exc}"
                            )

                    with followup_tab:
                        try:
                            followup_text = (
                                generate_followup_email(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            st.markdown(
                                followup_text
                            )

                            _render_download_buttons(
                                text=followup_text,
                                title=(
                                    f"Follow-up for "
                                    f"{company_name}"
                                ),
                                filename_prefix="followup",
                                filename_name=company_name,
                                key_prefix=(
                                    f"analysis_"
                                    f"followup_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Follow-up generation "
                                f"failed: {exc}"
                            )

        st.write("")

        st.download_button(
            "Download analysis results (JSON)",
            data=json.dumps(
                results,
                indent=2,
                default=str,
            ),
            file_name="omnimodel_results.json",
            mime="application/json",
            key="download_analysis_json",
        )

    else:
        st.info(
            "Enter a website URL above or paste "
            "multiple URLs to begin analysis."
        )


# =============================================================================
# TAB 2
# WIDE RANGE SEARCH
# =============================================================================


with tab_wide:
    st.markdown(
        "## Wide Range Search"
    )

    st.caption(
        "Discover companies by industry and location, "
        "review their contact details and generate outreach."
    )

    st.write("")

    col_country, col_area, col_city, col_query = (
        st.columns(
            [
                1.5,
                2,
                2.5,
                3,
            ]
        )
    )

    # -------------------------------------------------------------------------
    # Country
    # -------------------------------------------------------------------------

    with col_country:
        default_country = (
            _COUNTRIES.index(
                "Ghana"
            )
            if "Ghana"
            in _COUNTRIES
            else 0
        )

        country = st.selectbox(
            "Country",
            options=_COUNTRIES,
            index=default_country,
            key="wide_country",
        )

    # -------------------------------------------------------------------------
    # Area / region
    # -------------------------------------------------------------------------

    with col_area:
        available_areas = (
            _AREAS_BY_COUNTRY.get(
                country,
                [],
            )
        )

        if available_areas:
            area = st.selectbox(
                "Area / region",
                options=available_areas,
                key=(
                    f"wide_area_"
                    f"{country}"
                ),
            )

        else:
            area = ""

            st.text_input(
                "Area / region",
                value="",
                placeholder="Optional",
                disabled=True,
                key=(
                    f"wide_area_disabled_"
                    f"{country}"
                ),
            )

    # -------------------------------------------------------------------------
    # City
    # -------------------------------------------------------------------------

    with col_city:
        area_key = (
            f"{country}|{area}"
        )

        known_cities = (
            _CITIES_BY_AREA.get(
                area_key
            )
        )

        if not known_cities:
            known_cities = (
                _CITIES_BY_COUNTRY.get(
                    country,
                    [],
                )
            )

        if known_cities:
            city_mode = st.radio(
                "City source",
                options=[
                    "Select",
                    "Type manually",
                ],
                horizontal=True,
                key=(
                    f"city_mode_"
                    f"{country}_"
                    f"{area}"
                ),
            )

            if city_mode == "Select":
                city = st.selectbox(
                    "City / town",
                    options=known_cities,
                    key=(
                        f"city_select_"
                        f"{country}_"
                        f"{area}"
                    ),
                )

            else:
                city = st.text_input(
                    "City / town",
                    placeholder=(
                        "Enter a city or town"
                    ),
                    key=(
                        f"city_manual_"
                        f"{country}_"
                        f"{area}"
                    ),
                )

        else:
            city = st.text_input(
                "City / town",
                placeholder=(
                    "Enter a city or town"
                ),
                key=(
                    f"city_generic_"
                    f"{country}_"
                    f"{area}"
                ),
            )

    # -------------------------------------------------------------------------
    # Industry
    # -------------------------------------------------------------------------

    with col_query:
        query = st.text_input(
            "Industry / business type",
            placeholder=(
                "e.g. software company, hotel, "
                "dentist, restaurant"
            ),
            key="wide_query",
        )

    # -------------------------------------------------------------------------
    # Ghana region metadata
    # -------------------------------------------------------------------------

    if (
        country == "Ghana"
        and area in _GHANA_CITIES
    ):
        city_info = (
            _GHANA_CITIES.get(
                area,
                [],
            )
        )

        region_area = (
            _GHANA_REGION_AREAS.get(
                area
            )
        )

        if region_area:
            st.info(
                f"**{area} Region** · "
                f"{region_area} km² · "
                f"{len(city_info)} listed "
                "cities/towns"
            )

        else:
            st.info(
                f"**{area} Region** · "
                f"{len(city_info)} listed "
                "cities/towns"
            )

        city_descriptions = []

        for city_name, city_area in city_info:
            if city_area:
                city_descriptions.append(
                    f"{city_name} "
                    f"({city_area} km²)"
                )
            else:
                city_descriptions.append(
                    city_name
                )

        if city_descriptions:
            st.caption(
                "Locations: "
                + ", ".join(
                    city_descriptions
                )
            )

    # -------------------------------------------------------------------------
    # Search controls
    # -------------------------------------------------------------------------

    st.write("")

    col_max, col_search = (
        st.columns(
            [1, 3]
        )
    )

    with col_max:
        max_results = st.number_input(
            "Max results",
            min_value=1,
            max_value=20,
            value=10,
            step=1,
            key="wide_max_results",
        )

    with col_search:
        st.write("")

        wide_run = st.button(
            "Search companies",
            type="primary",
            width="stretch",
            key="wide_search_button",
        )

    # -------------------------------------------------------------------------
    # Search execution
    # -------------------------------------------------------------------------

    if wide_run:
        cleaned_query = (
            query.strip()
        )

        cleaned_city = (
            city.strip()
            if isinstance(
                city,
                str,
            )
            else str(city).strip()
        )

        if not cleaned_query:
            st.warning(
                "Enter an industry or business type."
            )

        elif not cleaned_city:
            st.warning(
                "Select or enter a city."
            )

        else:
            location_parts = [
                cleaned_city,
            ]

            if area:
                location_parts.append(
                    area
                )

            location_parts.append(
                country
            )

            location = ", ".join(
                location_parts
            )

            with st.status(
                (
                    f"Searching for "
                    f"'{cleaned_query}' in "
                    f"'{location}'..."
                ),
                expanded=True,
            ) as status:
                try:
                    discovered_companies = (
                        _run_wide_search(
                            cleaned_query,
                            location,
                            max_results=int(
                                max_results
                            ),
                            fetch_contacts=True,
                        )
                    )

                    st.session_state.wide_results = (
                        discovered_companies
                    )

                    status.update(
                        label=(
                            f"Found "
                            f"{len(discovered_companies)} "
                            "companies"
                        ),
                        state="complete",
                        expanded=False,
                    )

                except Exception as exc:
                    status.update(
                        label="Search failed",
                        state="error",
                        expanded=True,
                    )

                    st.error(
                        f"Search failed: {exc}"
                    )

    # -------------------------------------------------------------------------
    # Wide results
    # -------------------------------------------------------------------------

    wide_results = (
        st.session_state.wide_results
    )

    if wide_results:
        st.divider()

        st.markdown(
            f"## Results ({len(wide_results)} companies)"
        )

        rows = []

        for result in wide_results:
            rows.append(
                {
                    "Name": (
                        result.get(
                            "name"
                        )
                        or ""
                    ),
                    "Phone": (
                        result.get(
                            "phone"
                        )
                        or ""
                    ),
                    "Website": (
                        result.get(
                            "website"
                        )
                        or ""
                    ),
                    "Address": (
                        result.get(
                            "address"
                        )
                        or ""
                    ),
                    "Rating": (
                        result.get(
                            "rating"
                        )
                        or ""
                    ),
                    "Reviews": (
                        result.get(
                            "review_count"
                        )
                        or 0
                    ),
                }
            )

        wide_df = pd.DataFrame(
            rows
        )

        st.dataframe(
            wide_df,
            width="stretch",
            hide_index=True,
        )

        # ---------------------------------------------------------------------
        # Wide-result outreach
        # ---------------------------------------------------------------------

        st.write("")
        st.markdown(
            "### Companies & outreach"
        )

        st.caption(
            "Open a company to view its contact details "
            "and generate proposal material."
        )

        context = _template_context(
            our_name=our_name,
            our_title=our_title,
            our_email=our_email,
            our_phone=our_phone,
            our_services=our_services,
            our_value_prop=our_value_prop,
        )

        for index, result in enumerate(
            wide_results
        ):
            company_name = (
                result.get(
                    "name"
                )
                or "Unknown company"
            )

            company_address = (
                result.get(
                    "address"
                )
                or "Address unavailable"
            )

            with st.expander(
                (
                    f"{company_name} · "
                    f"{company_address}"
                ),
                expanded=False,
            ):
                col_details, col_outreach = (
                    st.columns(
                        [1, 2]
                    )
                )

                with col_details:
                    st.markdown(
                        "#### Contact details"
                    )

                    _render_contacts(
                        result
                    )

                with col_outreach:
                    st.markdown(
                        "#### Ready-to-send"
                    )

                    outreach_signals = {
                        "company_name": (
                            company_name
                        ),
                        "types": (
                            result.get(
                                "types"
                            )
                            or []
                        ),
                        "website": (
                            result.get(
                                "website"
                            )
                            or ""
                        ),
                    }

                    proposal_tab, email_tab, followup_tab = (
                        st.tabs(
                            [
                                "Proposal letter",
                                "Email",
                                "Follow-up",
                            ]
                        )
                    )

                    with proposal_tab:
                        try:
                            proposal_text = (
                                generate_proposal_letter(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            st.markdown(
                                proposal_text
                            )

                            _render_download_buttons(
                                text=proposal_text,
                                title=(
                                    f"Proposal for "
                                    f"{company_name}"
                                ),
                                filename_prefix="proposal",
                                filename_name=company_name,
                                key_prefix=(
                                    f"wide_"
                                    f"proposal_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Proposal generation "
                                f"failed: {exc}"
                            )

                    with email_tab:
                        try:
                            generated_email = (
                                generate_outreach_email(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            email_text = st.text_area(
                                "Edit email",
                                value=generated_email,
                                height=220,
                                key=(
                                    f"wide_email_"
                                    f"edit_{index}"
                                ),
                            )

                            _render_download_buttons(
                                text=email_text,
                                title=(
                                    f"Email for "
                                    f"{company_name}"
                                ),
                                filename_prefix="email",
                                filename_name=company_name,
                                key_prefix=(
                                    f"wide_"
                                    f"email_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Email generation "
                                f"failed: {exc}"
                            )

                    with followup_tab:
                        try:
                            followup_text = (
                                generate_followup_email(
                                    outreach_signals,
                                    **context,
                                )
                            )

                            st.markdown(
                                followup_text
                            )

                            _render_download_buttons(
                                text=followup_text,
                                title=(
                                    f"Follow-up for "
                                    f"{company_name}"
                                ),
                                filename_prefix="followup",
                                filename_name=company_name,
                                key_prefix=(
                                    f"wide_"
                                    f"followup_{index}"
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Follow-up generation "
                                f"failed: {exc}"
                            )

        st.write("")

        st.download_button(
            "Download all search results (JSON)",
            data=json.dumps(
                wide_results,
                indent=2,
                default=str,
            ),
            file_name="omnimodel_wide_results.json",
            mime="application/json",
            key="download_wide_json",
        )

    else:
        st.info(
            "Select a location, enter an industry "
            "or business type, then click Search companies."
        )
