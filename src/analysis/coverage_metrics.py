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

def prepare_tract_base(tracts_proj: gpd.GeoDataFrame, demo: pd.DataFrame) -> gpd.GeoDataFrame:
    """Build the tract-level base table: GEOID, geometry, demographics, area, density"""

    # Keep only GEOID and geometry from the tract shapefile
    tract_base = tracts_proj[['GEOID', 'geometry']].copy()
    print(f"Tract base: {len(tract_base)} tracts")

    # Join ACS fields onto tracts
    tract_base = tracts_proj.merge(
        demo[['GEOID', 'total_population', 'total_income']],
        on='GEOID',
        how='left'
    )

    # Calculate tract area in square kilometers
    tract_base['tract_area_square_km'] = tract_base.geometry.area / 1_000_000

    # Calculate population density (people per square km)
    tract_base['population_density'] = tract_base['total_population'] / tract_base['tract_area_square_km']
    tract_base['population_density'] = tract_base['population_density'].replace([float('-inf'), -float('inf')], None)

    # Flag zero-population and missing population tracts
    tract_base['zero_population'] = tract_base['total_population'] == 0
    tract_base['missing_population'] = tract_base['zero_population'].isna()

    print(f"Number of tracts with zero population: {tract_base['zero_population'].sum()}")
    print(f"Number of tracts with missing population: {tract_base['total_population'].sum()}")

    return tract_base

def agg_ev(tracts_proj: gpd.GeoDataFrame, ev_proj: gpd.GeoDataFrame) -> pd.DataFrame:
    """Spatially join EV infrastructure to tracts and aggregate port counts per tract"""
    # Spatially join EV stations to tracts
    joined = gpd.sjoin(ev_proj, tracts_proj[['GEOID', 'geometry']], how='inner', predicate='within')

    print(f"EV stations matched to a tract: {len(joined)} / {len(ev_proj)}")

    # Group by tract GEOID
    agg = joined.groupby('GEOID').agg(
        ev_station_count=('station_id' if 'station_id' in joined.columns else 'id', 'count')
        level2_ports=('level2_ports', 'sum'),
        dcfc_ports=('dcfc_ports','sum'),
        total_ev_ports=('total_ev_ports', 'sum'),
    ).reset_index()

    # Join aggregate back onto all tracts
    tracts_with_ev = tracts_proj[['GEOID']].merge(agg, on='GEOID', how='left')
    fill_cols = ['ev_station_count', 'level2_ports', 'dcfc_ports', 'total_ev_ports']
    tracts_with_ev[fill_cols] = tracts_with_ev[fill_cols].fillna(0).astype(int)

    print(f"Number of tracts with zero EV stations: {(tracts_with_ev['ev_station_count'] == 0).sum()}")

    return tracts_with_ev

def agg_gas(tracts_proj: gpd.GeoDataFrame, gas_proj: gpd.GeoDataFrame) -> pd.DataFrame:
    """Spatially join Gas infrastructure to tracts"""
    joined = gpd.sjoin(gas_proj, tracts_proj[['GEOID', 'geometry']], how='inner',predicate='within')

    print(f"Gas stations matched to a tract: {len(joined)} / {len(gas_proj)}")

    # Group by tract GEOID and count stations per tract
    agg = joined.groupby('GEOID').agg(
        gas_station_count=('station_id' if 'station_id' in joined.columns else 'id', 'count')
    ).reset_index()

    # Join counts back to all tracts
    tracts_with_gas = tracts_proj[['GEOID']].merge(agg, on='GEOID', how='left')
    fill_cols = ['gas_station_count']
    tracts_with_gas[fill_cols] = tracts_with_gas[fill_cols].fillna(0).astype(int)

    print(f"Number of tracts with zero gas stations: {(tracts_with_gas['gas_station_count'] == 0).sum()}")

    return tracts_with_gas



if __name__ == "__main__":
    tracts = load_tracts()
    demographics = load_demographics()
    ev = load_ev()
    gas = load_gas()

    tracts_proj, ev_proj, gas_proj = align_crs(tracts, ev, gas)
    
    print("\nStep 1 complete — all layers loaded and aligned to EPSG:3310.")


