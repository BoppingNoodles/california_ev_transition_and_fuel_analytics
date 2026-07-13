"""
This file associates infrastructure points with Census tracts and calculates
accessibility metrics
"""
import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parents[2]))
from config import PROCESSED_DIR, EXTERNAL_DIR, RAW_DIR, CRS_ANALYSIS

def load_tracts(dir: Path=None) -> gpd.GeoDataFrame:
    """Load California Census Tract geometries"""
    if tracts_dir is None:
        tracts_dir = EXTERNAL_DIR / "california_tracts"
    
    shp_files = list(tracts_dir.glob('*.shp'))
    if shp_files is None:
        print(f"No shp files found at {tracts_dir}")
    
    tracts = gdp.read_files(shp_files[0])
    print(f"Found {len(tracts)} at {tracts_dir}")

    return tracts