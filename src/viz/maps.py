"""Interactive Folium map for Phase 5 delivery outputs."""
from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import MarkerCluster

from ..config import CRS_WEB, GEOJSON_DIR, MAPS_DIR, PROCESSED_DIR, TABLES_DIR


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
    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron", control_scale=True)
    score_col = _first_column(deserts, ["desert_score"], required=True)
    severity_col = _first_column(deserts, ["severity_score", "severity"], required=False)
    folium.Choropleth(
        geo_data=deserts.to_json(), data=deserts, columns=[_first_column(deserts, ["GEOID", "geoid"]), score_col],
        key_on=f"feature.properties.{_first_column(deserts, ['GEOID', 'geoid'])}",
        fill_color="YlOrRd", fill_opacity=.65, line_opacity=.2, legend_name="Charging desert score",
        name="Desert score",
    ).add_to(m)

    if severity_col:
        severe = deserts[deserts[severity_col].astype(str).eq("severe_desert")]
        folium.GeoJson(severe.to_json(), name="Severe deserts", style_function=lambda _: {"fillOpacity": 0, "color": "#8b0000", "weight": 2}).add_to(m)

    ev_group = folium.FeatureGroup(name="EV stations", show=False)
    cluster = MarkerCluster(name="EV station markers").add_to(ev_group)
    dcfc_col = _first_column(ev, ["dcfc_ports"], required=False)
    for _, row in ev.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        is_dcfc = dcfc_col and float(row.get(dcfc_col, 0) or 0) > 0
        folium.CircleMarker(location=[row.geometry.y, row.geometry.x], radius=4 if is_dcfc else 2,
                            color="#0057b8" if is_dcfc else "#4f81bd", fill=True,
                            popup=f"{row.get('station_name', row.get('name', 'EV station'))}<br>DCFC ports: {row.get(dcfc_col, 0) if dcfc_col else 'n/a'}").add_to(cluster)
    ev_group.add_to(m)

    if candidate_points is not None:
        cand_group = folium.FeatureGroup(name=f"Top {top_n} candidates")
        score = _first_column(candidate_points, ["final_score"], required=False)
        rank = _first_column(candidate_points, ["rank"], required=False)
        for _, row in candidate_points.sort_values(score, ascending=False).head(top_n).iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            popup = "<br>".join([f"Rank: {row.get(rank, 'n/a')}", f"Score: {row.get(score, 'n/a')}", f"Station: {row.get('name', row.get('station_name', 'n/a'))}", f"Rationale: {row.get('rationale', 'n/a')}"])
            folium.Marker([row.geometry.y, row.geometry.x], popup=folium.Popup(popup, max_width=350), icon=folium.Icon(color="green", icon="flash")).add_to(cand_group)
        cand_group.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(output_path)
    return output_path


if __name__ == "__main__":
    print(build_map())
