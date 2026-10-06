"""Profile-driven lead finder.

Pick a business profile, search by region/city/sector, score, draft outreach.
"""
import asyncio
import json

import pandas as pd
import streamlit as st

# Optional gate for when this app goes multi-tenant:
# from omnimodel.auth import require_login
from omnimodel.config import config
from omnimodel.extraction.factory import available_backends, get_extractor
from omnimodel.places.google_places import search_by_location
from omnimodel.profile_loader import list_profiles, load_profile
from omnimodel.scoring.profile_scoring import (
    best_offering,
    lead_from_signals,
    score_lead,
)
from omnimodel.scraping.playwright_scraper import fetch_pages
from omnimodel.templates.profile_templates import render

st.set_page_config(page_title="Lead Finder", layout="wide")

# Optional gate for when this app goes multi-tenant:
# require_login()


@st.cache_data(ttl=86400, show_spinner=False)
def places_search(query, location, n):
    return search_by_location(query, location, max_results=n)


def flat(p):
    return {
        "id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text") or "(unnamed)",
        "address": p.get("formattedAddress"),
        "phone": p.get("nationalPhoneNumber"),
        "website": p.get("websiteUri"),
        "rating": p.get("rating"),
        "review_count": p.get("userRatingCount"),
    }


ss = st.session_state
ss.setdefault("leads", [])
ss.setdefault("dnc", set())
ss.setdefault("analyzed", {})

with st.sidebar:
    profiles = list_profiles()
    if not profiles:
        st.error("No business profiles found in omnimodel/profiles.")
        st.stop()
    pname = st.selectbox("Business profile", profiles)
    try:
        P = load_profile(pname)
    except Exception as exc:
        st.error(f"Profile error: {exc}")
        st.stop()
    st.markdown("**Your details** (edit to override the profile)")
    biz = {
        k: st.text_input(
            k.replace("our_", "").title(), v, key=f"{pname}_{k}"
        )
        for k, v in P["business"].items()
    }
    backends = available_backends()
    backend = st.radio(
        "LLM backend",
        backends,
        index=backends.index(config.extraction_backend)
        if config.extraction_backend in backends
        else 0,
    )

OFF = {k: v["label"] for k, v in P["offerings"].items()}
st.title(f"Lead finder: {P['name']}")
c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
region = c1.selectbox("Region", list(P["geography"]))
city = c2.selectbox("City / town", P["geography"][region])
skey = c3.selectbox(
    "Industry", list(P["sectors"]), format_func=lambda k: P["sectors"][k]["label"]
)
n = c4.number_input("Max", 1, 20, 10)

if st.button("Search", type="primary", width="stretch"):
    with st.spinner("Searching Google Places..."):
        try:
            raw = places_search(
                P["sectors"][skey]["query"],
                f"{city}, {region}, {P['country']}",
                int(n),
            )
            ss.leads = [
                dict(flat(p), region=region, city=city, sector=skey) for p in raw
            ]
            ss.analyzed = {}
        except Exception as exc:
            st.error(f"Search failed: {exc}")


def lead_scores(lead):
    sig = ss.analyzed.get(lead["website"])
    return score_lead(
        lead_from_signals(sig, lead["sector"], len(ss.leads) - 1, lead, P), P
    )


def extract(text):
    ex = get_extractor(backend)
    try:
        return ex(text, signal_schema=P["signal_schema"]) or {}
    except TypeError:  # backend does not accept a custom schema
        st.warning(
            "This backend ignored the profile schema; results use default signals."
        )
        return ex(text) or {}


if ss.leads:
    rows = []
    for lead in ss.leads:
        sc = lead_scores(lead)
        best = best_offering(sc)
        rows.append(
            {
                "Company": lead["name"],
                "Best fit": OFF.get(best, "-"),
                "Score": round(sc[best]["score"] * 100) if best else 0,
                "Phone": lead["phone"] or "",
                "Website": lead["website"] or "",
                "Analyzed": "yes" if lead["website"] in ss.analyzed else "",
            }
        )
    st.dataframe(
        pd.DataFrame(rows).sort_values("Score", ascending=False),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Before analysis, scores use the sector, area cluster and Places data "
        "only. Analyze a website to add signals."
    )

    st.subheader("Lead detail")
    pick = st.selectbox(
        "Company",
        range(len(ss.leads)),
        format_func=lambda i: ss.leads[i]["name"],
    )
    lead = ss.leads[pick]
    st.write(
        f"{lead['address'] or ''}  |  {lead['phone'] or 'no phone'}  |  "
        f"{lead['website'] or 'no website'}"
    )

    if lead["website"] and st.button("Analyze website"):
        with st.spinner("Scraping and extracting..."):
            try:
                pages = asyncio.run(fetch_pages([lead["website"]]))
                text = pages.get(lead["website"]) or ""
                if not text.strip():
                    st.warning("That page returned no readable text.")
                else:
                    ss.analyzed[lead["website"]] = extract(text)
                    st.rerun()
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

    found = ss.analyzed.get(lead["website"]) or {}
    if found.get("existing_provider"):
        st.caption(
            "Current provider mentioned on site: " + str(found["existing_provider"])
        )
    sc = lead_scores(lead)
    for col, o in zip(st.columns(len(OFF)), OFF):
        col.metric(OFF[o], round(sc[o]["score"] * 100))
    default_offering = best_offering(sc) or list(OFF)[0]
    offering = st.selectbox(
        "Draft outreach for",
        list(OFF),
        index=list(OFF).index(default_offering),
        format_func=OFF.get,
    )
    st.bar_chart(pd.Series(sc[offering]["breakdown"], name="points"), width="stretch")

    if st.checkbox("Do not contact this company", value=lead["id"] in ss.dnc):
        ss.dnc.add(lead["id"])
        st.warning("Marked do-not-contact for this session. Drafts are hidden.")
    else:
        ss.dnc.discard(lead["id"])
        st.info("Drafts only. Review every message before you send it.")
        for tab, kind in zip(
            st.tabs(["Email", "Proposal", "Follow-up"]),
            ["email", "proposal", "followup"],
        ):
            with tab:
                text = render(P, kind, lead, offering, biz)
                st.text_area(
                    "Draft", text, height=280, key=f"{kind}_{lead['id']}_{offering}"
                )
                st.download_button(
                    "Download .txt",
                    text,
                    file_name=f"{kind}_{lead['name']}.txt",
                    key=f"dl_{kind}_{lead['id']}_{offering}",
                )
    st.download_button(
        "Export all leads (JSON)",
        json.dumps(ss.leads, indent=2, default=str),
        file_name="leads.json",
    )
else:
    st.info("Choose a region, city and industry, then click Search.")
