"""omniModel Streamlit UI."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import streamlit as st

# Full-screen, responsive layout with Streamlit's native theme
st.set_page_config(
    page_title="omniModel",
    page_icon="\U0001f4ca",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Streamlit theme customization via CSS
st.markdown(
    """
    <style>
    /* Full-width app container */
    .block-container {
        max-width: 100% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1rem !important;
    }

    /* Remove default Streamlit centering */
    .stApp {
        background-color: var(--background-color);
    }

    /* Custom metric cards */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 1rem;
        color: white;
    }

    /* Rounded expanders */
    div[data-testid="stExpander"] {
        border-radius: 12px;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }

    /* Better spacing for markdown */
    .stMarkdown, .stMarkdown p {
        line-height: 1.6;
    }

    /* Responsive columns */
    div[data-testid="stColumn"] {
        padding: 0 0.5rem;
    }

    /* Custom scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: var(--background-color);
    }
    ::-webkit-scrollbar-thumb {
        background: var(--secondary-background-color);
        border-radius: 4px;
    }

    /* Force tab labels visible in all themes */
    div[data-testid="stTab"] {
        color: var(--text-color) !important;
    }
    div[data-testid="stTab"] p {
        color: var(--text-color) !important;
    }
    [role="tab"] {
        color: var(--text-color) !important;
    }
    [role="tab"][aria-selected="true"] {
        color: var(--text-color) !important;
        border-bottom-color: var(--primary-color) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

from omnimodel.config import config
from omnimodel.extraction.factory import available_backends, get_extractor
from omnimodel.places.google_places import get_place_contacts, search_by_location
from omnimodel.scraping.playwright_scraper import fetch_page, fetch_pages
from omnimodel.scoring.weighted_rules import default_rules, score_signals
from omnimodel.templates import (
    generate_followup_email,
    generate_outreach_email,
    generate_proposal_letter,
)
from omnimodel.export import export_docx, export_pdf, export_txt

# Helpers
import pandas as pd


def _score_breakdown_df(breakdown):
    if not breakdown:
        return pd.DataFrame({"rule": [], "score": []})
    return pd.DataFrame(
        [{"rule": k, "score": v} for k, v in breakdown.items()]
    ).set_index("rule")


def _score_gauge(score):
    pct = int(score * 100)
    color = "#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444"
    return (
        '<div style="text-align:center;padding:10px;">'
        f'<div style="font-size:48px;font-weight:800;color:{color};">{pct}</div>'
        '<div style="font-size:12px;color:#6b7280;">SCORE</div>'
        '<div style="margin:8px auto 0;width:100%;height:8px;background:#e5e7eb;border-radius:4px;">'
        f'<div style="width:{pct}%;height:100%;background:{color};border-radius:4px;"></div>'
        "</div></div>"
    )


def _run_pipeline(urls, backend):
    pages = asyncio.run(fetch_pages(urls))
    extractor = get_extractor(backend)
    rules = default_rules()
    results = {}
    for url, page_text in pages.items():
        signals = extractor(page_text)
        scored = score_signals(signals, rules)
        results[url] = {
            "signals": signals,
            "score": scored.score,
            "breakdown": scored.breakdown,
        }
    return results


def _run_wide_search(query, location, *, max_results=20, fetch_contacts=True):
    places = search_by_location(query, location, max_results=max_results)
    results = []
    for place in places:
        entry = {
            "id": place.get("id"),
            "name": (place.get("displayName") or {}).get("text"),
            "address": place.get("formattedAddress"),
            "phone": place.get("nationalPhoneNumber"),
            "website": place.get("websiteUri"),
            "types": place.get("types"),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
        }
        if fetch_contacts and place.get("id"):
            try:
                entry["contacts"] = get_place_contacts(place["id"])
            except Exception:
                entry["contacts"] = None
        results.append(entry)
    return results


def _render_contacts(place):
    contacts = place.get("contacts") or {}
    name = contacts.get("name") or place.get("name") or "-"
    phone = contacts.get("phone") or place.get("phone") or "-"
    website = contacts.get("website") or place.get("website") or "-"
    address = contacts.get("address") or place.get("address") or "-"
    rating = contacts.get("rating") or place.get("rating") or "-"
    reviews = contacts.get("review_count") or place.get("review_count") or 0
    types = contacts.get("types") or place.get("types") or []
    st.markdown("**" + str(name) + "**")
    st.markdown("Phone: " + str(phone))
    st.markdown("Website: " + str(website))
    st.markdown("Address: " + str(address))
    if rating != "-":
        st.markdown("Rating: " + str(rating) + " (" + str(reviews) + " reviews)")
    if types:
        st.markdown("Type: " + ", ".join(str(t) for t in types[:4]))


# ---------------------------------------------------------------------------
# Country / city data
# ---------------------------------------------------------------------------
_COUNTRIES = [
    "United States", "Canada", "United Kingdom", "Australia", "Germany",
    "France", "Spain", "Italy", "Netherlands", "Sweden", "Norway", "Denmark",
    "Finland", "Belgium", "Switzerland", "Austria", "Ireland", "New Zealand",
    "Japan", "South Korea", "India", "Brazil", "Mexico", "Argentina",
    "Singapore", "Hong Kong", "United Arab Emirates", "Ghana", "Nigeria",
    "South Africa", "Kenya",
]

_CITIES_BY_COUNTRY = {
    "United States": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
        "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
        "Austin", "Seattle", "Denver", "Boston", "Miami"],
    "Canada": ["Toronto", "Montreal", "Vancouver", "Calgary", "Ottawa"],
    "United Kingdom": ["London", "Manchester", "Birmingham", "Edinburgh", "Liverpool"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"],
    "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"],
    "France": ["Paris", "Marseille", "Lyon", "Toulouse", "Nice"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Seville", "Malaga"],
    "Italy": ["Rome", "Milan", "Naples", "Florence", "Venice"],
    "Netherlands": ["Amsterdam", "Rotterdam", "The Hague", "Utrecht"],
    "Sweden": ["Stockholm", "Gothenburg", "Malmo", "Uppsala"],
    "Norway": ["Oslo", "Bergen", "Trondheim", "Stavanger"],
    "Denmark": ["Copenhagen", "Aarhus", "Odense", "Aalborg"],
    "Finland": ["Helsinki", "Espoo", "Tampere", "Turku"],
    "Belgium": ["Brussels", "Antwerp", "Ghent", "Bruges"],
    "Switzerland": ["Zurich", "Geneva", "Basel", "Bern"],
    "Austria": ["Vienna", "Graz", "Linz", "Salzburg"],
    "Ireland": ["Dublin", "Cork", "Galway", "Limerick"],
    "New Zealand": ["Auckland", "Wellington", "Christchurch", "Hamilton"],
    "Japan": ["Tokyo", "Osaka", "Kyoto", "Yokohama", "Nagoya"],
    "South Korea": ["Seoul", "Busan", "Incheon", "Daegu", "Daejeon"],
    "India": ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai"],
    "Brazil": ["Sao Paulo", "Rio de Janeiro", "Brasilia", "Salvador"],
    "Mexico": ["Mexico City", "Guadalajara", "Monterrey", "Puebla"],
    "Argentina": ["Buenos Aires", "Cordoba", "Rosario", "Mendoza"],
    "Singapore": ["Singapore"],
    "Hong Kong": ["Hong Kong"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah"],
    "Ghana": ["Accra", "Kumasi", "Tamale", "Cape Coast", "Takoradi"],
    "Nigeria": ["Lagos", "Kano", "Ibadan", "Abuja", "Port Harcourt"],
    "South Africa": ["Johannesburg", "Cape Town", "Durban", "Pretoria", "Port Elizabeth"],
    "Kenya": ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret"],
}

# Areas / regions within countries (used for granular filtering)
_Ghana = [
    "Greater Accra", "Ashanti", "Northern", "Western", "Eastern", "Central",
    "Volta", "Bono", "Upper East", "Upper West", "Bono East", "Oti",
    "Western North", "Savannah", "Ahafo",
]

# Major cities with land area info (km²)
_Ghana_CITIES = {
    "Greater Accra": [
        ("Accra", "20.4 (Metro) / 199.4 (urban)"),
        ("Tema", "87.8 (Metro District)"),
        ("Madina", None),
        ("Teshie", None),
        ("Nungua", None),
        ("Ashiaman", None),
        ("Mampong", None),
        ("Dodowa", None),
    ],
    "Ashanti": [
        ("Kumasi", "299 (city) / 214.3 (Metro District)"),
        ("Obuasi", None),
        ("Ejisu", None),
        ("Nkawie", None),
        ("Fumso", None),
    ],
    "Northern": [
        ("Tamale", "750 (city) / 647 (Metro District)"),
        ("Savelugu", None),
        ("Yendi", None),
        ("Bawku", None),
    ],
    "Western": [
        ("Sekondi-Takoradi", None),
        ("Tarkwa", None),
        ("Bibiani", None),
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
    ],
    "Savannah": [
        ("Damongo", None),
    ],
    "Ahafo": [
        ("Goaso", None),
    ],
}

# Region total areas (km²)
_Ghana_REGION_AREAS = {
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

# Build _AREAS_BY_COUNTRY and _CITIES_BY_AREA from the Ghana data
_AREAS_BY_COUNTRY = {
    "Ghana": _Ghana,
    "United States": ["Northeast", "Southeast", "Midwest", "Southwest", "West", "New England", "Pacific", "Mountain", "Atlantic"],
    "United Kingdom": ["England", "Scotland", "Wales", "Northern Ireland"],
    "Canada": ["Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba", "Saskatchewan", "Nova Scotia", "New Brunswick"],
    "Australia": ["New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia", "Tasmania"],
    "Nigeria": ["Lagos", "FCT", "Kano", "Rivers", "Oyo", "Delta", "Kaduna", "Enugu"],
    "South Africa": ["Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape", "Mpumalanga"],
    "Kenya": ["Nairobi", "Coast", "Rift Valley", "Eastern", "Central", "Western"],
}

_CITIES_BY_AREA = {}
for region, cities in _Ghana_CITIES.items():
    _CITIES_BY_AREA["Ghana|" + region] = [c[0] for c in cities]

# Session state
for key, default in [("results", None), ("wide_results", None), ("last_urls", [])]:
    if key not in st.session_state:
        setattr(st.session_state, key, default)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("# omniModel")
    st.markdown("<span style='color:var(--text-color-dim);'>Company signal extraction & scoring</span>", unsafe_allow_html=True)
    st.write("")

    # Theme toggle - use radio instead of segmented_control for reliability
    st.markdown("### Theme")
    theme = st.radio(
        "Theme", options=["Light", "Dark", "System"], index=2,
        help="Switch between light, dark, or system theme.",
    )

    st.write("")
    st.markdown("### My business")
    st.markdown("_Used in all outreach templates._")
    our_name = st.text_input("Business name", value="Your Company")
    our_email = st.text_input("Email", value="hello@yourcompany.com")
    our_phone = st.text_input("Phone", value="")
    our_title = st.text_input("Title", value="Business Development")
    our_services = st.text_area(
        "Services to market",
        value="- Faster, more reliable operations\n- Cost savings through automation\n- Better customer experience",
        height=68,
    )
    our_value_prop = st.text_input(
        "Value proposition", value="optimize operations and grow revenue"
    )

    st.write("")
    st.markdown("### LLM backend")
    backends = available_backends()
    backend = st.radio(
        "Backend", options=backends,
        index=backends.index(config.extraction_backend) if config.extraction_backend in backends else 0,
        help="OpenRouter (default), Ollama (local), or Claude (paid).",
    )
    if backend == "openrouter":
        st.success("OpenRouter active")
    elif backend == "ollama":
        st.warning("Ollama - make sure ollama serve is running")
    else:
        st.info("Claude - requires ANTHROPIC_API_KEY")

    st.write("")
    st.markdown("### Scoring rules")
    for r in default_rules():
        st.write("**" + r.name + "** - weight " + str(r.weight))

    st.write("")
    st.markdown("---")
    st.markdown("Playwright | OpenRouter | Google Places | Streamlit")
    st.markdown("No login. Anyone with browser access can use it.")

# ---------------------------------------------------------------------------
# Tab 1: Analyze website
# ---------------------------------------------------------------------------
tab_analyze, tab_wide = st.tabs(["Analyze website", "Wide scraping"])

with tab_analyze:
    st.markdown("# Analyze a website")
    st.markdown("<span style='color:#6b7280;'>Scrape, extract signals, score, and generate outreach in one click.</span>", unsafe_allow_html=True)
    st.write("")

    url = st.text_input(
        "Website URL", placeholder="https://example.com",
        help="Enter a company website to scrape and analyze.",
    )

    col_analyze, col_clear = st.columns([1, 4])
    with col_analyze:
        analyze = st.button("Analyze", type="primary", use_container_width=True)
    with col_clear:
        if st.button("Clear results", use_container_width=False):
            st.session_state.results = None
            st.rerun()

    if analyze and url:
        if not url.startswith(("http://", "https://")):
            st.error("URL must start with http:// or https://")
        else:
            with st.status("Running pipeline...", expanded=True) as status:
                st.write("Scraping page with Playwright...")
                try:
                    results = _run_pipeline([url], backend)
                    st.session_state.results = results
                    st.session_state.last_urls = [url]
                    status.update(label="Done!", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="Failed", state="error", expanded=True)
                    st.error("Pipeline failed: " + str(exc))
                    st.stop()

    st.write("")
    st.markdown("### Batch analysis")
    batch_text = st.text_area(
        "URLs (one per line)", placeholder="https://example.com\nhttps://another.com",
        height=100,
    )
    col_batch, _ = st.columns([1, 4])
    with col_batch:
        batch_run = st.button("Run batch", use_container_width=True)

    if batch_run and batch_text.strip():
        urls = [u.strip() for u in batch_text.splitlines() if u.strip()]
        bad = [u for u in urls if not u.startswith(("http://", "https://"))]
        if bad:
            st.error("Invalid URLs: " + str(bad))
        else:
            with st.status("Processing " + str(len(urls)) + " URLs...", expanded=True) as status:
                try:
                    results = _run_pipeline(urls, backend)
                    st.session_state.results = results
                    st.session_state.last_urls = urls
                    status.update(label="Done!", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="Failed", state="error", expanded=True)
                    st.error("Batch failed: " + str(exc))
                    st.stop()

    results = st.session_state.results
    if results:
        st.write("")
        st.markdown("### Results")

        rows = []
        for u, data in results.items():
            rows.append({
                "URL": u,
                "Score": round(data["score"], 3),
                "Pricing": len(data["signals"].get("pricing") or []),
                "Hiring": len(data["signals"].get("hiring") or []),
                "Tech": len(data["signals"].get("tech_stack") or []),
                "Growth": len(data["signals"].get("growth_signals") or []),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.write("")
        st.markdown("### Score breakdown")
        for u, data in results.items():
            name = data["signals"].get("company_name") or u
            with st.expander("**" + str(name) + "** - score " + str(round(data["score"], 3)), expanded=False):
                col_g, col_b = st.columns([1, 2])
                with col_g:
                    st.markdown(_score_gauge(data["score"]), unsafe_allow_html=True)
                with col_b:
                    chart_df = _score_breakdown_df(data["breakdown"])
                    if not chart_df.empty:
                        st.bar_chart(chart_df, color="#4f46e5")
                    else:
                        st.caption("No signals matched scoring rules.")

        st.write("")
        st.markdown("### Outreach")
        st.markdown("<span style='color:#6b7280;'>Generate proposal letters and emails using your business details from the sidebar.</span>", unsafe_allow_html=True)

        for i, (u, data) in enumerate(results.items()):
            name = data["signals"].get("company_name") or u
            with st.expander("**" + str(name) + "** - " + u, expanded=False):
                col_d, col_o = st.columns([1, 2])
                with col_d:
                    st.markdown("**Extracted signals**")
                    st.json(data["signals"])
                with col_o:
                    st.markdown("**Ready-to-send**")
                    signals = {
                        "company_name": name,
                        "types": data["signals"].get("tech_stack") or [],
                        "website": u,
                    }
                    tk = dict(
                        our_name=our_name, our_title=our_title,
                        our_email=our_email, our_phone=our_phone,
                        deliverables=our_services, value_prop=our_value_prop,
                    )
                    tp, te, tf = st.tabs(["Proposal letter", "Email", "Follow-up"])
                    with tp:
                        proposal_text = generate_proposal_letter(signals, **tk)
                        st.markdown(proposal_text)
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(proposal_text),
                                file_name="proposal_" + name.replace(" ", "_") + ".pdf", mime="application/pdf", key="apdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(proposal_text, "Proposal for " + name),
                                file_name="proposal_" + name.replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="adocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(proposal_text),
                                file_name="proposal_" + name.replace(" ", "_") + ".txt", mime="text/plain", key="atxt_" + str(i))
                    with te:
                        email_text = st.text_area("Edit email", value=generate_outreach_email(signals, **tk), height=200, key="aemail_edit_" + str(i))
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(email_text),
                                file_name="email_" + name.replace(" ", "_") + ".pdf", mime="application/pdf", key="aepdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(email_text, "Email for " + name),
                                file_name="email_" + name.replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="aedocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(email_text),
                                file_name="email_" + name.replace(" ", "_") + ".txt", mime="text/plain", key="aetxt_" + str(i))
                    with tf:
                        followup_text = generate_followup_email(signals, **tk)
                        st.markdown(followup_text)
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(followup_text),
                                file_name="followup_" + name.replace(" ", "_") + ".pdf", mime="application/pdf", key="afpdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(followup_text, "Follow-up for " + name),
                                file_name="followup_" + name.replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="afdocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(followup_text),
                                file_name="followup_" + name.replace(" ", "_") + ".txt", mime="text/plain", key="aftxt_" + str(i))

        st.write("")
        col_exp, _ = st.columns([1, 4])
        with col_exp:
            st.download_button("Download results (JSON)", data=json.dumps(results, indent=2, default=str),
                file_name="omnimodel_results.json", mime="application/json", use_container_width=False)
    else:
        st.info("Enter a URL above and click Analyze, or paste multiple URLs and click Run batch.")

# ---------------------------------------------------------------------------
# Tab 2: Wide scraping
# ---------------------------------------------------------------------------
with tab_wide:
    st.markdown("# Wide scraping")
    st.markdown("<span style='color:#6b7280;'>Search for companies by industry and location. Select, review, and generate outreach.</span>", unsafe_allow_html=True)
    st.write("")

    col_country, col_area, col_city, col_query = st.columns([1, 2, 2, 3])
    with col_country:
        country = st.selectbox(
            "Country", options=_COUNTRIES,
            index=_COUNTRIES.index("United States") if "United States" in _COUNTRIES else 0,
        )
    with col_area:
        areas = _AREAS_BY_COUNTRY.get(country, [])
        area = st.selectbox(
            "Area / region", options=areas if areas else ["(type manually)"], index=0,
        )
    with col_city:
        known_cities = _CITIES_BY_AREA.get(key, [])
        if known_cities:
            city_mode = st.radio(
                "City", options=["Select from list", "Type manually"],
                index=0, horizontal=True, key="city_mode_" + str(country) + "_" + str(area),
            )
            if city_mode == "Select from list":
                city = st.selectbox(
                    "City / town", options=known_cities, index=0,
                    key="city_select_" + str(country) + "_" + str(area),
                )
            else:
                city = st.text_input(
                    "City / town", placeholder="e.g. Nungua, Madina, Teshie",
                    key="city_type_" + str(country) + "_" + str(area),
                )
        else:
            city = st.text_input(
                "City / town", placeholder="Type city or town name",
                key="city_type_generic",
            )

    # Show area info for Ghana regions
    if country == "Ghana" and area in _Ghana_REGION_AREAS:
        st.markdown("")
        st.info(
            "**" + str(area) + "** region: " + _Ghana_REGION_AREAS[area] + " km2 | "
            + str(len(_Ghana_CITIES.get(area, []))) + " major cities"
        )
        if area in _Ghana_CITIES:
            city_info = _Ghana_CITIES[area]
            city_lines = []
            for cname, carea in city_info:
                if carea:
                    city_lines.append(cname + " (" + carea + " km2)")
                else:
                    city_lines.append(cname)
            st.caption("Cities: " + ", ".join(city_lines))
    with col_query:
        query = st.text_input(
            "Industry / business type", placeholder="e.g. coffee shop, plumber, dentist",
        )

    col_max, col_run = st.columns([1, 2])
    with col_max:
        max_results = st.number_input("Max results", min_value=1, max_value=20, value=10)
    with col_run:
        st.write("")
        wide_run = st.button("Search", type="primary", use_container_width=True)

    if wide_run and query:
        location = str(city) + ", " + str(country) if city != "(type manually)" else country
        with st.status("Searching Places for '" + str(query) + "' in '" + str(location) + "'...", expanded=True) as status:
            try:
                wide_results = _run_wide_search(query, location, max_results=max_results, fetch_contacts=True)
                st.session_state.wide_results = wide_results
                status.update(label="Done!", state="complete", expanded=False)
            except Exception as exc:
                status.update(label="Failed", state="error", expanded=True)
                st.error("Search failed: " + str(exc))
                st.stop()

    wide_results = st.session_state.wide_results
    if wide_results:
        st.write("")
        st.markdown("### Results (" + str(len(wide_results)) + " companies)")

        rows = []
        for r in wide_results:
            rows.append({
                "Name": r.get("name") or "",
                "Phone": r.get("phone") or "",
                "Website": r.get("website") or "",
                "Address": (r.get("address") or "")[:60],
                "Rating": r.get("rating") or "",
                "Reviews": r.get("review_count") or 0,
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.write("")
        st.markdown("### Outreach")
        st.markdown("<span style='color:#6b7280;'>Click a company to view contact details and generate outreach.</span>", unsafe_allow_html=True)

        for i, r in enumerate(wide_results):
            name = r.get("name") or "the company"
            with st.expander("**" + str(name) + "** - " + str(r.get("address", "")), expanded=False):
                col_d, col_o = st.columns([1, 2])
                with col_d:
                    st.markdown("**Contact details**")
                    _render_contacts(r)
                with col_o:
                    st.markdown("**Ready-to-send**")
                    signals = {
                        "company_name": name,
                        "types": r.get("types") or [],
                        "website": r.get("website") or "",
                    }
                    tk = dict(
                        our_name=our_name, our_title=our_title,
                        our_email=our_email, our_phone=our_phone,
                        deliverables=our_services, value_prop=our_value_prop,
                    )
                    tp, te, tf = st.tabs(["Proposal letter", "Email", "Follow-up"])
                    with tp:
                        proposal_text = generate_proposal_letter(signals, **tk)
                        st.markdown(proposal_text)
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(proposal_text),
                                file_name="proposal_" + str(name).replace(" ", "_") + ".pdf", mime="application/pdf", key="wpdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(proposal_text, "Proposal for " + str(name)),
                                file_name="proposal_" + str(name).replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="wdocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(proposal_text),
                                file_name="proposal_" + str(name).replace(" ", "_") + ".txt", mime="text/plain", key="wtxt_" + str(i))
                    with te:
                        email_text = st.text_area("Edit email", value=generate_outreach_email(signals, **tk), height=200, key="wemail_edit_" + str(i))
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(email_text),
                                file_name="email_" + str(name).replace(" ", "_") + ".pdf", mime="application/pdf", key="wepdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(email_text, "Email for " + str(name)),
                                file_name="email_" + str(name).replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="wedocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(email_text),
                                file_name="email_" + str(name).replace(" ", "_") + ".txt", mime="text/plain", key="wetxt_" + str(i))
                    with tf:
                        followup_text = generate_followup_email(signals, **tk)
                        st.markdown(followup_text)
                        col_pdf, col_docx, col_txt = st.columns(3)
                        with col_pdf:
                            st.download_button("PDF", data=export_pdf(followup_text),
                                file_name="followup_" + str(name).replace(" ", "_") + ".pdf", mime="application/pdf", key="wfpdf_" + str(i))
                        with col_docx:
                            st.download_button("DOCX", data=export_docx(followup_text, "Follow-up for " + str(name)),
                                file_name="followup_" + str(name).replace(" ", "_") + ".docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="wfdocx_" + str(i))
                        with col_txt:
                            st.download_button("TXT", data=export_txt(followup_text),
                                file_name="followup_" + str(name).replace(" ", "_") + ".txt", mime="text/plain", key="wftxt_" + str(i))

        st.write("")
        col_exp, _ = st.columns([1, 4])
        with col_exp:
            st.download_button("Download all results (JSON)", data=json.dumps(wide_results, indent=2, default=str),
                file_name="omnimodel_wide_results.json", mime="application/json", use_container_width=False)
    else:
        st.info("Select a country and city, enter an industry, then click Search.")