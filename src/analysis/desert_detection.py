"""
This file loads the processed tracts with the coverage metrics, normalizes the 4 metrics
(gas_access, population_density, ev_gap, dcfc_distance) to a 0-1 scale, computes the 
composite `desert_score` 0-100 and assigns severity classifications `severe_desert`, `moderate_desert`, 'adequate`.
Outputs:
    - data/processed/charging_deserts.parquet (full resolution, EPSG:3310) for analysis
    - outputs/geojson/charging_deserts.geojson (simplified, EPSG:4326) for the map and dashboard
"""

import sys
from pathlib import Path 
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, GEOJSON_DIR, CRS_WEB

### Choose scoring inputs
def load_coverage_metrics(
    path: Path = None
) -> gpd.GeoDataFrame:
    """Loads the tract coverage metrics GeoDataFrame from parquet"""
    if path is None:
        path = PROCESSED_DIR / "tract_coverage_metrics.parquet"
    
    gdf = gpd.read_parquet(path)
    print(f"Loaded coverage metrics for {len(gdf)} tracts from {path.name}")

    return gdf

### Normalize coverage metrics
def normalize_coverage_metrics(
    series: pd.Series,
    method: str = "percentile",
) -> pd.Series:
    """
    Scales a Pandas series to the 0-1 range.

    - ``percentile`` (default): percentile rank, with ties sharing their
      average rank. Robust to the heavy right skew of density and port
      metrics, where a handful of dense downtown tracts would otherwise set
      the max and compress every other tract toward 0.
    - ``minmax``: linear (x - min) / (max - min).

    Nulls stay null. A constant series maps to 0.5.
    """
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty or valid.max() == valid.min():
        return pd.Series(np.where(s.notna(), 0.5, np.nan), index=s.index)
    if method == "percentile":
        ranks = s.rank(method="average", na_option="keep")
        return (ranks - 1) / (len(valid) - 1)
    if method == "minmax":
        return (s - valid.min()) / (valid.max() - valid.min())
    raise ValueError(f"Unknown normalization method: {method!r}")

COMPONENT_COLS = ['comp_gas_access', 'comp_pop_density', 'comp_ev_gap', 'comp_dcfc_distance']


def scorable_tracts(gdf: pd.DataFrame) -> pd.Series:
    """
    Boolean mask of tracts that should receive a desert score: tracts with
    residents and a defined (land-area) population density. Water-only,
    park and other zero-population tracts are excluded so they neither get
    labelled as deserts nor distort the normalization of populated tracts.
    """
    population = pd.to_numeric(gdf['total_population'], errors='coerce')
    density = pd.to_numeric(gdf['population_density'], errors='coerce')
    return (population > 0) & density.notna()


### Build the desert score components
def compute_desert_components(
    gdf: gpd.GeoDataFrame,
    method: str = "percentile",
) -> gpd.GeoDataFrame:
    """
    Calculates the 4 normalized component columns on a 0-1 scale.
    Normalization uses scorable (populated) tracts only; other tracts get
    null components.
    """

    df = gdf.copy()
    mask = scorable_tracts(df)
    scored = df.loc[mask]

    for col in COMPONENT_COLS:
        df[col] = np.nan

    # Gas access component
    df.loc[mask, 'comp_gas_access'] = normalize_coverage_metrics(scored['gas_access_count_2km'], method)

    # Population density
    df.loc[mask, 'comp_pop_density'] = normalize_coverage_metrics(scored['population_density'], method)

    # EV gap component
    norm_ev_supply = normalize_coverage_metrics(scored['ports_per_sq_km'], method)
    df.loc[mask, 'comp_ev_gap'] = 1.0 - norm_ev_supply

    # DCFC distance component
    df.loc[mask, 'comp_dcfc_distance'] = normalize_coverage_metrics(scored['nearest_dcfc_km'], method)

    return df

### Compute final score
def compute_desert_score(
    gdf: gpd.GeoDataFrame,
    w_gas: float=0.25,
    w_pop: float=0.25,
    w_ev: float=0.35,
    w_dcfc: float=0.15
) -> gpd.GeoDataFrame:
    """Computes the composite desert score (0-100) from the 4 normalized components"""
    df = gdf.copy()

    # Score
    df['desert_score'] = 100.0 * (
        w_gas * df['comp_gas_access'] +
        w_pop * df['comp_pop_density'] + 
        w_ev * df['comp_ev_gap'] +
        w_dcfc * df['comp_dcfc_distance']
    )
    df['desert_score'] = df['desert_score'].round(2)

    return df

### Add severity labels
def add_severity_labels(
    gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Adds severity labels to respective desert score
        - `severe_desert`: `desert_score` >= 75
        - `moderate_desert`: 50 <= `desert_score` < 75
        - `adequate`: `desert_score` < 50
        - `not_scored`: unpopulated / water-only tracts (null `desert_score`)
    """
    df = gdf.copy()

    df['severity_score'] = 'not_scored'
    df.loc[df['desert_score'] < 50, 'severity_score'] = 'adequate'
    df.loc[(df['desert_score'] >= 50) & (df['desert_score'] < 75), 'severity_score'] = 'moderate_desert'
    df.loc[df['desert_score'] >= 75, 'severity_score'] = 'severe_desert'
    
    return df

### Saved scored tracts to GeoJSON
def save_desert_parquet(
    gdf: gpd.GeoDataFrame,
    output_path: Path = None
) -> Path:
    """Saves the full-resolution scored tracts (EPSG:3310) for downstream analysis."""
    if output_path is None:
        output_path = PROCESSED_DIR / "charging_deserts.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(output_path)
    print(f"Saved full-resolution desert layer to {output_path}")
    return output_path


def export_desert_geojson(
    gdf: gpd.GeoDataFrame,
    output_path: Path = None,
    simplify_m: float = 50.0,
    coord_decimals: int = 5,
    value_decimals: int = 4,
) -> Path:
    """
    Exports a lightweight web copy of the charging desert layer to GeoJSON.

    Full-resolution TIGER tract outlines make this file ~100 MB, which is
    too heavy for the map and dashboard. The export therefore:
    - simplifies outlines by `simplify_m` metres in EPSG:3310, using
      coverage-aware simplification when available so neighbouring tracts
      keep identical shared edges (no slivers or gaps);
    - rounds coordinates to `coord_decimals` (5 decimals ~ 1 m) and float
      properties to `value_decimals`;
    - writes compact JSON.

    Use the full-resolution parquet (save_desert_parquet) for spatial joins.
    """
    if output_path is None:
        output_path = GEOJSON_DIR / "charging_deserts.geojson"

    web = gdf.to_crs("EPSG:3310").copy()
    if simplify_m:
        if hasattr(web.geometry, "simplify_coverage"):
            web["geometry"] = web.geometry.simplify_coverage(simplify_m)
        else:  # geopandas/shapely without coverage support
            web["geometry"] = web.geometry.simplify(simplify_m, preserve_topology=True)
    web = web.to_crs(CRS_WEB)
    web["geometry"] = shapely.transform(web.geometry.values, lambda xy: np.round(xy, coord_decimals))

    float_cols = web.select_dtypes(include="float").columns
    web[float_cols] = web[float_cols].round(value_decimals)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(web.to_json(drop_id=True, separators=(",", ":")), encoding="utf-8")
    size_mb = output_path.stat().st_size / 1e6
    print(f"Exported charging deserts GeoJSON to {output_path} ({size_mb:.1f} MB)")

    return output_path

if __name__ == "__main__":
    print("--- Starting Desert Detection ---")

    metrics_gdf = load_coverage_metrics()
    
    components_gdf = compute_desert_components(metrics_gdf)
    print("Computed normalized component scores.")

    scored_gdf = compute_desert_score(components_gdf)
    print("Calculated composite desert scores.")

    labeled_gdf = add_severity_labels(scored_gdf)
    print("Severity distribution:")
    print(labeled_gdf['severity_score'].value_counts())

    save_desert_parquet(labeled_gdf)
    export_desert_geojson(labeled_gdf)
    print("Phase 3.2 pipeline complete.")


