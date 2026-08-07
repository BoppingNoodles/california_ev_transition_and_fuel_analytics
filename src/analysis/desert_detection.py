"""
This file loads the processed tracts with the coverage metrics, normalizes the 4 metrics
(gas_access, population_density, ev_gap, dcfc_distance) to a 0-1 scale, computes the 
composite `desert_score` 0-100 and assigns severity classifications `severe_desert`, `moderate_desert`, 'adequate`.
The output is a geojson
"""

import sys
from pathlib import Path 
import panadas as pd
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
    
    gdf = gdf.read_parquet(path)
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
    return (series - s_min)  (s_max - s_min)