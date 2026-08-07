"""
This file associates infrastructure points with Census tracts and calculates
accessibility metrics
"""
import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, EXTERNAL_DIR, RAW_DIR, CRS_ANALYSIS

<<<<<<< HEAD
### Load and align CRS
=======
>>>>>>> efa26cd20a5c4a2ec804b44ff0f49937cea37a69
def load_tracts(tracts_dir: Path=None) -> gpd.GeoDataFrame:
    """Load California Census Tract geometries"""
    if not tracts_dir:
        tracts_dir = EXTERNAL_DIR / "california_tracts"
    
    shp_files = list(tracts_dir.glob('*.shp'))
    if not shp_files:
        print(f"No shp files found at {tracts_dir}")
    
<<<<<<< HEAD
    tracts = gpd.read_file(shp_files[0])
    print(f"Found {len(tracts)} tracts at {tracts_dir}")
=======
    tracts = gpd.read_files(shp_files[0])
    print(f"Found {len(tracts)} at {tracts_dir}")
>>>>>>> efa26cd20a5c4a2ec804b44ff0f49937cea37a69

    return tracts

def load_demographics(dir: Path=RAW_DIR) -> pd.DataFrame:
    """Load California ACS CSV"""
    census_files = sorted(dir.glob('census_data_*.csv'))

    if not census_files:
        print(f"No census files found at {dir}")

    census_csv = pd.read_csv(census_files[-1], dtype={"GEOID": str, "state": str, "county": str, "tract":str})

<<<<<<< HEAD
    print(f"Loaded {census_files[-1].name} with {len(census_csv)} tracts")
=======
    print(f"Loaded {census_csv[-1].name} with length {len(census_csv)}")
>>>>>>> efa26cd20a5c4a2ec804b44ff0f49937cea37a69

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
    gas_proj = gas.to_crs(target_crs)

    print(f"After projection to {target_crs}\n:")
    print(f"Tracts CRS: {tracts_proj.crs}")
    print(f"EV CRS: {ev_proj.crs}")
    print(f"Gas CRS: {gas_proj.crs}")

    for name, gdf in [("tracts", tracts_proj), ("ev", ev_proj), ("gas", gas_proj)]:
        is_meters = gdf.crs.axis_info[0].unit_name.lower() in ("metre", "meter")
        print(f"  {name} units in meters: {is_meters}")
        assert is_meters, f"{name} CRS is not in meters after projection — check target_crs"

    return tracts_proj, ev_proj, gas_proj

### Prepare tract base
def prepare_tract_base(
    tracts: gpd.GeoDataFrame,
    demographics: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """
    Join ACS demographics onto projected tract geometries, compute
    area and population density, and flag zero/null-population tracts.
    """
    # Keep only the columns we need from the tract shapefile
    tract_base = tracts[["GEOID", "geometry"]].copy()

    # Ensure GEOID is a string on both sides to prevent silent join mismatches
    tract_base["GEOID"] = tract_base["GEOID"].astype(str)
    demographics = demographics.copy()
    demographics["GEOID"] = demographics["GEOID"].astype(str)

    n_before = len(tract_base)

    # Left-join so every tract geometry is preserved even if ACS data is missing
    acs_cols = ["GEOID", "total_population", "median_income"]
    tract_base = tract_base.merge(
        demographics[acs_cols], on="GEOID", how="left"
    )

    n_after = len(tract_base)
    n_matched = tract_base["total_population"].notna().sum()
    print(f"Tracts before join : {n_before}")
    print(f"Tracts after join  : {n_after}")
    print(f"Tracts with ACS pop: {n_matched}  |  missing: {n_after - n_matched}")

    # Area in square kilometres (geometry is in EPSG:3310 metres)
    tract_base["tract_area_sq_km"] = tract_base.geometry.area / 1_000_000

    # Population density — guard against zero/null area
    tract_base["population_density"] = (
        tract_base["total_population"] / tract_base["tract_area_sq_km"]
    ).where(tract_base["tract_area_sq_km"] > 0, other=None)

    # Flags for downstream handling
    tract_base["missing_population_flag"] = tract_base["total_population"].isna()
    tract_base["zero_population_flag"] = (
        tract_base["total_population"].fillna(0) == 0
    )

    n_zero = tract_base["zero_population_flag"].sum()
    n_missing = tract_base["missing_population_flag"].sum()
    print(f"Zero-population tracts  : {n_zero}")
    print(f"Missing-population tracts: {n_missing}")

    return tract_base

### Aggregate EV infrastructure
def agg_ev(
    ev: gpd.GeoDataFrame,
    tract_base: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Aggregate EV infrastructure to California tracts"""

    # Spatially join EV stations to tracts
    joined = gpd.sjoin(ev,tract_base, how='left',predicate='within')

    # Group by tract GEOID
    ev_agg = joined.groupby('GEOID').agg(
        ev_station_count=("id", "count"),
        level2_ports=("level2_ports", "sum"),
        dcfc_ports=("dcfc_ports", "sum"),
        total_ev_ports=("total_ev_ports", "sum")
    ).reset_index()

    # Join back to all tracts
    tract_base = tract_base.merge(ev_agg,on='GEOID', how='left')

    # Fill missing infrastructure counts with 0 (fillna must be assigned back)
    fill_cols = ['ev_station_count', 'level2_ports', 'dcfc_ports', 'total_ev_ports']
    tract_base[fill_cols] = tract_base[fill_cols].fillna(0)

    # Quality Check
    print(f"EV stations in raw data: {len(ev)}")
    print(f"EV stations after joining with tracts: {tract_base['ev_station_count'].sum()}")

    return tract_base


if __name__ == "__main__":
    tracts = load_tracts()
    demographics = load_demographics()
    ev = load_ev()
    gas = load_gas()

    tracts_proj, ev_proj, gas_proj = align_crs(tracts, ev, gas)
    print("\nStep 1 complete — all layers loaded and aligned to EPSG:3310.")

    tract_base = prepare_tract_base(tracts_proj, demographics)
    print("\nStep 2 complete — tract base prepared with demographics and area metrics.")
    print(tract_base[["GEOID", "total_population", "tract_area_sq_km", "population_density"]].head())

    tract_base = agg_ev(ev_proj, tract_base)
    print("\nStep 3 complete — EV infrastructure aggregated to tracts.")
    print(tract_base[['GEOID', 'ev_station_count', 'level2_ports', 'dcfc_ports', 'total_ev_ports']].head())
