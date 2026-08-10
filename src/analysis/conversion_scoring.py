"""
This file loads the cleaned data (gas, EV stations, charging deserts) and spatially joins
each gas station to its census tract to match its local desert_score. It measures distance from each gas station
to the nearest DC Fast charger and computes a composite 0-100 conversion suitablity score for every gas station

Output:
    - outputs/tables/conversion_candidates.csv
"""
import sys 
from pathlib import Path 
import geopandas as gpd 

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, GEOJSON_DIR, TABLES_DIR, CRS_ANALYSIS

# Load required layers
def load_data(
    gas_path: Path=None,
    ev_path: Path=None,
    deserts_path: Path=None
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Loads cleaned gas, EV, and charging desert tracts

    Output:
        - [gas_gdf, ev_gdf, deserts_gdf]
    """
    if gas_path is None:
        gas_path = PROCESSED_DIR / "gas_stations.parquet"
    if ev_path is None:
        ev_path = PROCESSED_DIR / "ev_stations.parquet"
    if deserts_path is None:
        deserts_path = GEOJSON_DIR / "charging_deserts.geojson"

    # Load parquet and geojson layers
    gas_gdf = gpd.read_parquet(gas_path)
    ev_gdf = gpd.read_parquet(ev_path)
    deserts_gdf = gpd.read_file(deserts_path)

    # Project all layers to EPSG:3310
    gas_gdf = gas_gdf.to_crs(CRS_ANALYSIS)
    ev_gdf = ev_gdf.to_crs(CRS_ANALYSIS)
    deserts_gdf = deserts_gdf.to_crs(CRS_ANALYSIS)

    print(f"Loaded {len(gas_gdf)} gas stations, {len(ev_gdf)} EV stations, {len(deserts_gdf)} desert tracts")

    return gas_gdf, ev_gdf, deserts_gdf

# Attach gas stations to tracts
def gas_to_tracts(
    gas: gpd.GeoDataFrame,
    tract_base: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Attaches tract scores to respective gas stations"""

    # Subset desert tracts to keep only geometry and certain metadata columns
    tract_subset = deserts[[
        'GEOID',
        'desert_score',
        'severity_score',
        'total_population',
        'population_density',
        'geometry'
    ]]
    # Spatially join gas gdf with tract gdf
    gas_with_tract = gpd.sjoin(gas, tract_subset, how='left', predicate='within')

    # Drop index_right column created by sjoin
    if 'index_right' in gas_with_tract.columns:
        gas_with_tract = gas_with_tract.drop(columns=['index_right'])

    return gas_with_tract



