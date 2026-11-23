"""Interactive Folium map for Phase 5 delivery outputs."""
from __future__ import annotations

from pathlib import Path
import html
import sys

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from folium.plugins import FastMarkerCluster

try:
    from ..config import CRS_WEB, GEOJSON_DIR, MAPS_DIR, PROCESSED_DIR, TABLES_DIR
except ImportError:  # Supports direct execution by file path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import CRS_WEB, GEOJSON_DIR, MAPS_DIR, PROCESSED_DIR, TABLES_DIR  # type: ignore[no-redef]


# Each EV data row is [lat, lon, popup_html, is_dcfc]; DCFC stations are drawn larger and darker.
EV_MARKER_CALLBACK = """
function (row) {
    var isDcfc = row[3] === 1;
    var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {
        radius: isDcfc ? 5 : 3,
        color: isDcfc ? '#0057b8' : '#4f81bd',
        fill: true,
        fillOpacity: 0.8
    });
    marker.bindPopup(row[2]);
    return marker;
}
"""


def _simplify_for_map(tracts: gpd.GeoDataFrame, tolerance_m: float, decimals: int = 5) -> gpd.GeoDataFrame:
    """Coverage-simplifies tract outlines in metres and rounds coordinates (5 decimals ~ 1 m)."""
    out = tracts.to_crs("EPSG:3310")
    if tolerance_m:
        try:  # needs shapely >= 2.1 / GEOS >= 3.12
            out["geometry"] = out.geometry.simplify_coverage(tolerance_m)
        except (AttributeError, ImportError, NotImplementedError):
            print("[WARN] Coverage simplification unavailable; using per-polygon simplify")
            out["geometry"] = out.geometry.simplify(tolerance_m, preserve_topology=True)
    out = out.to_crs(CRS_WEB)
    out["geometry"] = shapely.transform(out.geometry.values, lambda xy: np.round(xy, decimals))
    return out


def _first_column(frame: pd.DataFrame, names: list[str], required: bool = True) -> str | None:
    for name in names:
        if name in frame:
            return name
    if required:
        raise KeyError(f"None of the expected columns were found: {names}")
    return None


def build_map(
    deserts_path: Path | None = None,
    candidates_path: Path | None = None,
    ev_path: Path | None = None,
    output_path: Path | None = None,
    top_n: int = 50,
    map_simplify_m: float = 150.0,
) -> Path:
    deserts_path = deserts_path or GEOJSON_DIR / "charging_deserts.geojson"
    candidates_path = candidates_path or TABLES_DIR / "conversion_candidates.csv"
    ev_path = ev_path or PROCESSED_DIR / "ev_stations.parquet"
    output_path = output_path or MAPS_DIR / "charging_deserts.html"
    for path in (deserts_path, candidates_path, ev_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing Phase 5 input: {path}")

    deserts = gpd.read_file(deserts_path).to_crs(CRS_WEB)
    candidates = pd.read_csv(candidates_path)
    ev = gpd.read_parquet(ev_path).to_crs(CRS_WEB)
    lat_col = _first_column(candidates, ["latitude", "lat", "y"], required=False)
    lon_col = _first_column(candidates, ["longitude", "lon", "lng", "x"], required=False)
    if lat_col and lon_col:
        candidate_points = gpd.GeoDataFrame(
            candidates, geometry=gpd.points_from_xy(candidates[lon_col], candidates[lat_col]), crs=CRS_WEB
        )
    else:
        candidate_points = None

    center = [36.7783, -119.4179]
    m = folium.Map(location=center, zoom_start=6, tiles="OpenStreetMap", control_scale=True)
    score_col = _first_column(deserts, ["desert_score"], required=True)
    severity_col = _first_column(deserts, ["severity_score", "severity"], required=False)
    # Only the ID, score and severity are needed on the map. Outlines get a
    # coarser, map-only simplification; it is coverage-aware so neighbouring
    # tracts keep identical shared edges (plain per-polygon simplify opens
    # slivers between tracts).
    geoid_col = _first_column(deserts, ["GEOID", "geoid"])
    map_cols = [c for c in [geoid_col, score_col, severity_col] if c]
    deserts = _simplify_for_map(deserts[map_cols + ["geometry"]], map_simplify_m)
    folium.Choropleth(
        geo_data=deserts.to_json(), data=deserts, columns=[geoid_col, score_col],
        key_on=f"feature.properties.{geoid_col}",
        fill_color="YlOrRd", fill_opacity=.65, line_opacity=.2, legend_name="Charging desert score",
        nan_fill_color="#cccccc", nan_fill_opacity=.3,  # unpopulated / not-scored tracts
        name="Desert score",
    ).add_to(m)

    if severity_col:
        severe = deserts[deserts[severity_col].astype(str).eq("severe_desert")]
        folium.GeoJson(severe.to_json(), name="Severe deserts", style_function=lambda _: {"fillOpacity": 0, "color": "#8b0000", "weight": 2}).add_to(m)

    # EV stations: FastMarkerCluster ships one compact JS array instead of a
    # separate Leaflet object per station, which keeps the HTML small.
    ev_group = folium.FeatureGroup(name="EV stations", show=False)
    dcfc_col = _first_column(ev, ["dcfc_ports"], required=False)
    name_col = _first_column(ev, ["station_name", "name"], required=False)
    ev_points = ev[ev.geometry.notna() & ~ev.geometry.is_empty]
    dcfc = pd.to_numeric(ev_points[dcfc_col], errors="coerce").fillna(0).astype(int) if dcfc_col else pd.Series(0, index=ev_points.index)
    names = ev_points[name_col].fillna("EV station").astype(str) if name_col else pd.Series("EV station", index=ev_points.index)
    ev_data = [
        [round(geom.y, 5), round(geom.x, 5), f"{html.escape(name)}<br>DCFC ports: {ports}", int(ports > 0)]
        for geom, name, ports in zip(ev_points.geometry, names, dcfc)
    ]
    FastMarkerCluster(ev_data, callback=EV_MARKER_CALLBACK).add_to(ev_group)
    ev_group.add_to(m)

    if candidate_points is not None:
        cand_group = folium.FeatureGroup(name=f"Top {top_n} candidates")
        score = _first_column(candidate_points, ["final_score"], required=False)
        rank = _first_column(candidate_points, ["rank"], required=False)
        for _, row in candidate_points.sort_values(score, ascending=False).head(top_n).iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            popup = "<br>".join([f"Rank: {row.get(rank, 'n/a')}", f"Score: {row.get(score, 'n/a')}", f"Station: {html.escape(str(row.get('name', row.get('station_name', 'n/a'))))}", f"Rationale: {html.escape(str(row.get('rationale', 'n/a')))}"])
            folium.Marker([row.geometry.y, row.geometry.x], popup=folium.Popup(popup, max_width=350), icon=folium.Icon(color="green", icon="flash")).add_to(cand_group)
        cand_group.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(output_path)
    return output_path


if __name__ == "__main__":
    print(build_map())
