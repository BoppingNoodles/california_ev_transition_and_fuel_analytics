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
    if not tracts_dir:
        tracts_dir = EXTERNAL_DIR / "california_tracts"
    
    shp_files = list(tracts_dir.glob('*.shp'))
    if shp_files is None:
        print(f"No shp files found at {tracts_dir}")
    
    tracts = gdp.read_files(shp_files[0])
    print(f"Found {len(tracts)} at {tracts_dir}")

    return tracts

def load_demographics(dir: Path=RAW_DIR) -> pd.DataFrame:
    """Load California ACS CSV"""
    census_files = sorted(dir.glob('census_data_*.csv'))

    if not census_files:
        print(f"No census files found at {dir}")
        
    census_csv = pd.read_csv(census_files[-1], dtype={"GEOID": str, "state": str, "county": str, "tract":str})

    print(f"Loaded {census_csv.name} with length {len(census_csv)}")

    return census_csv
