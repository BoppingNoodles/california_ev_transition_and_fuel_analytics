"""Lightweight Phase 5 dashboard for reviewing candidate rankings."""
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import GEOJSON_DIR, TABLES_DIR, MAPS_DIR


@st.cache_data
def load_candidates() -> pd.DataFrame:
    return pd.read_csv(TABLES_DIR / "conversion_candidates.csv")


@st.cache_data
def load_deserts() -> pd.DataFrame:
    import geopandas as gpd
    return gpd.read_file(GEOJSON_DIR / "charging_deserts.geojson")


def main() -> None:
    st.set_page_config(page_title="California EV Transition", layout="wide")
    st.title("California EV Transition & Fuel Station Analytics")
    required = [TABLES_DIR / "conversion_candidates.csv", GEOJSON_DIR / "charging_deserts.geojson"]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        st.warning("Run Phases 1–4 first. Missing: " + ", ".join(missing))
        return

    candidates = load_candidates()
    deserts = load_deserts()
    county_col = next((c for c in ["county", "County", "county_name"] if c in candidates), None)
    severity_col = next((c for c in ["severity_score", "severity"] if c in candidates), None)
    with st.sidebar:
        st.header("Filters")
        county = st.selectbox("County", ["All"] + sorted(candidates[county_col].dropna().astype(str).unique().tolist())) if county_col else "All"
        minimum = st.slider("Minimum candidate score", 0, 100, 0)
        severity = st.multiselect("Severity", sorted(candidates[severity_col].dropna().unique())) if severity_col else []
    filtered = candidates[candidates["final_score"].fillna(0) >= minimum].copy()
    if county_col and county != "All": filtered = filtered[filtered[county_col].astype(str) == county]
    if severity_col and severity: filtered = filtered[filtered[severity_col].isin(severity)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Analyzed gas stations", len(candidates))
    c2.metric("Severe desert tracts", int((deserts.get("severity_score", pd.Series(dtype=str)) == "severe_desert").sum()))
    c3.metric("Filtered candidates", len(filtered))
    c4.metric("Median DCFC distance (km)", round(filtered["nearest_dcfc_km"].median(), 1) if "nearest_dcfc_km" in filtered and len(filtered) else "n/a")
    st.subheader("Candidates")
    st.dataframe(filtered.sort_values("final_score", ascending=False), use_container_width=True)
    st.download_button("Download filtered CSV", filtered.to_csv(index=False), "filtered_conversion_candidates.csv", "text/csv")
    map_path = MAPS_DIR / "charging_deserts.html"
    if map_path.exists():
        st.subheader("Interactive map")
        st.components.v1.html(map_path.read_text(encoding="utf-8"), height=700, scrolling=True)


if __name__ == "__main__":
    main()
