"""
This file loads the processed tracts with the coverage metrics, normalizes the 4 metrics
(gas_access, population_density, ev_gap, dcfc_distance) to a 0-1 scale, computes the 
composite `desert_score` 0-100 and assigns severity classifications `severe_desert`, `moderate_desert`, 'adequate`.
The output is a geojson
"""

import sys
from pathlib import Path 
import pandas as pd
import geopandas as gpd

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
    print(f"Loaded coverage metrics for {len(gdf)} tracts form {path.name}")

    return gdf

### Normalize coverage metrics
def normalize_coverage_metrics(
    series: pd.Series
) -> pd.Series:
    """Scales a Pandas series to 0-1 range"""
    s_min = series.min()
    s_max = series.max()
    if s_max == s_min:
        return pd.Series(0.5, index=series.index)
    return (series - s_min) / (s_max - s_min)

### Build the desert score components
def compute_desert_components(
    gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Calculates the 4 normalized component columns on a 0-1 scale"""

    df = gdf.copy()

    # Gas access component
    df['comp_gas_access'] = normalize_coverage_metrics(df['gas_access_count_2km'])

    # Population density
    df['comp_pop_density'] = normalize_coverage_metrics(df['population_density'])

    # EV gap component
    norm_ev_supply = normalize_coverage_metrics(df['ports_per_sq_km'])
    df['comp_ev_gap'] = 1.0 - norm_ev_supply 

    # DCFC distance component
    df['comp_dcfc_distance'] = normalize_coverage_metrics(df['nearest_dcfc_km'])

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
        - `moderate_desert`: `desert_score` >= 50
        - `adequate`: `desert_score` < 50
        
    Exports to GeoJSON
    """

    df = gdf.copy()

    df['severity_score'] = 'adequate'
    df.loc[df['desert_score'] >= 75, 'severity_score'] = 'severe_desert'
    df.loc[df['desert_score'] >= 50, 'severity_score'] = 'moderate_desert'
    
    return df
