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

def load_ev(dir: Path=PROCESSED_DIR) -> gpd.GeoDataFrame:
    """Load cleaned and processed EV station data from parquet file"""
    ev_parquet = gpd.read_parquet(dir / "ev_stations.parquet")

    print(f"Loaded EV parquet file succcessfully at {dir} with size {len(ev_parquet)}")

    return ev_parquet

def load_gas(dir: Path=PROCESSED_DIR) -> gpd.GeoDataFrame:
    """Load cleaned and processed gas station data from parquet file"""
    gas_parquet = gpd.read_parquet(dir / "gas_stations.parquet")

    print(f"Loaded Gas parquet file successfully at {dir} with size {len(gas_parquet)}")

    return gas_parquet

def align_crs(tracts: gpd.GeoDataFrame,
              ev: gpd.GeoDataFrame, 
              gas: gpd.GeoDataFrame,
              target_crs: str=CRS_ANALYSIS) -> tuple:
    """Projects tracts and both point layers to shared CRS (meters)"""
    tracts_proj = tracts.to_crs(target_crs)
    ev_proj = ev.to_crs(target_crs)
    gas_proj = ev.to_crs(target_crs)

    print(f"After projection to {target_crs}\n:")
    print(f"Tracts CRS: {tracts_proj.crs}")
    print(f"EV CRS: {ev_proj.crs}")
    print(f"Gas CRS: {gas_proj.crs}")

    for name, gdf in [("tracts", tracts_proj), ("ev", ev_proj), ("gas", gas_proj)]:
        is_meters = gdf.crs.axis_info[0].unit_name.lower() in ("metre", "meter")
        print(f"  {name} units in meters: {is_meters}")
        assert is_meters, f"{name} CRS is not in meters after projection — check target_crs"

    return tracts_proj, ev_proj, gas_proj

if __name__ == "__main__":
    tracts = load_tracts()
    demographics = load_demographics()
    ev = load_ev()
    gas = load_gas()

    tracts_proj, ev_proj, gas_proj = align_crs(tracts, ev, gas)
    
    print("\nStep 1 complete — all layers loaded and aligned to EPSG:3310.")


