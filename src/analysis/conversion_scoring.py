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
import numpy as np 
from scipy.spatial import cKDTree

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, GEOJSON_DIR, TABLES_DIR, CRS_ANALYSIS

### Load required layers
def load_data(
    gas_path: Path=None,
    ev_path: Path=None,
    deserts_path: Path=None,
    highways_path: Path = None
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame | None]:
    """
    Loads cleaned gas, EV, charging desert tracts, and optional highways layer

    Output:
        - (gas_gdf, ev_gdf, deserts_gdf, highways_gdf)
    """
    if gas_path is None:
        gas_path = PROCESSED_DIR / "gas_stations.parquet"
    if ev_path is None:
        ev_path = PROCESSED_DIR / "ev_stations.parquet"
    if deserts_path is None:
        deserts_path = GEOJSON_DIR / "charging_deserts.geojson"
    if highways_path is None:
        highways_path = PROCESSED_DIR / "highways.parquet"

    # Load parquet and geojson layers
    gas_gdf = gpd.read_parquet(gas_path)
    ev_gdf = gpd.read_parquet(ev_path)
    deserts_gdf = gpd.read_file(deserts_path)

    if highways_path.exists():
        highways_gdf = gpd.read_parquet(highways_path).to_crs(CRS_ANALYSIS)
    else:
        highways_gdf = None

    # Project all layers to EPSG:3310
    gas_gdf = gas_gdf.to_crs(CRS_ANALYSIS)
    ev_gdf = ev_gdf.to_crs(CRS_ANALYSIS)
    deserts_gdf = deserts_gdf.to_crs(CRS_ANALYSIS)

    h_count = len(highways_gdf) if highways_gdf is not None else 0
    print(f"Loaded {len(gas_gdf)} gas stations, {len(ev_gdf)} EV stations, {len(deserts_gdf)} desert tracts, {h_count} highway segments")

    return gas_gdf, ev_gdf, deserts_gdf, highways_gdf

### Attach gas stations to tracts
def gas_to_tracts(
    gas: gpd.GeoDataFrame,
    deserts: gpd.GeoDataFrame
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

### Calculate nearest DCFC distance
def nearest_dcfc(
    ev: gpd.GeoDataFrame,
    gas: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Filters EV stations to DCFC locations and calculates the nearest DCFC distance for each gas station
    """

    # Filter EV stations to DCFC locations
    dcfc = ev.copy()
    dcfc = dcfc[dcfc['dcfc_ports'] > 0]

    # Calculate nearest DCFC distance for each gas station
    nearest = gpd.sjoin_nearest(
        gas[['station_id', 'geometry']],
        dcfc[['geometry']],
        how='left',
        distance_col='distance_meters'
    )

    # Convert to kilometers
    nearest['nearest_dcfc_km'] = nearest['distance_meters'] / 1000.0

    # Drop duplicates
    nearest = nearest.drop_duplicates(subset=['station_id'])
    # Merge to gas
    gas = gas.merge(
        nearest[['station_id', 'nearest_dcfc_km']],
        on='station_id',
        how='left'
    )
    
    return gas

### Calculate redundancy
def calculate_redundant_gas(
    gas: gpd.GeoDataFrame,
    radius_meters: float=1000.0,
    penalty_per_station: float=5.0,
    max_penalty: float=25.0
) -> gpd.GeoDataFrame:
    """
    Counts other gas stations within 1 km of each station (excluding itself) and 
    converts the count into a score penalty
    """

    gdf = gas.copy()

    # Extract projected coords
    coords = np.column_stack([gdf.geometry.x, gdf.geometry.y])

    # Build spatial KDTree
    tree = cKDTree(coords)

    # Find all stations within 1 km
    gdf['nearby_gas_1km'] = [len(neighbors) - 1 for neighbors in tree.query_ball_point(coords,r=radius_meters)]

    # Convert nearby count into a penalty
    gdf['redundancy_penalty'] = np.minimum(gdf['nearby_gas_1km'] * penalty_per_station,
                                          max_penalty)
    
    return gdf

### Find nearest highway
def nearest_highway(
    gas: gpd.GeoDataFrame,
    highways: gpd.GeoDataFrame=None
) -> gpd.GeoDataFrame:
    """
    Calculates distance in km to nearest major highway segment for each gas station
    and awards corridor context points
    """

    gas = gas.copy()
    
    # Spatially join to find nearest highway for each gas station
    if highways is not None and not highways.empty:
        nearest = gpd.sjoin_nearest(
            gas[['station_id', 'geometry']],
            highways[['geometry']],
            how='left',
            distance_col='distance_meters'
        )

        nearest = nearest.drop_duplicates(subset=['station_id'])
        nearest['nearest_highway_km'] = nearest['distance_meters'] / 1000.0
        # Merge back to gas stations
        gas = gas.merge(
            nearest[['station_id','nearest_highway_km']],
            on='station_id',
            how='left'
        )
    else: 
        gas['nearest_highway_km'] = np.nan
    
    return gas

### Apply score components
def calculate_gas_conv(
    gas: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Applies score components, calculates final score (0-100), and ranks candidate sites
    """

    print("Calculating gas conversion score ...")
    gdf = gas.copy()

    # Local charging gap 
    max_desert = gdf['desert_score'].max() if gdf['desert_score'].max() > 0 else 1.0
    gdf['pts_local_gap'] = (gdf['desert_score'].fillna(0) / max_desert) * 30.0

    # Nearest DCFC distance
    gdf['pts_dcfc_dist'] = np.minimum(gdf['nearest_dcfc_km'].fillna(15.0), 15.0) / 15.0 * 25.0

    # Population and corridor context
    max_pop = gdf['total_population'].max() if gdf['total_population'].max() > 0 else 1.0
    norm_pop = gdf['total_population'].fillna(0) / max_pop 

    if 'nearest_highway_km' in gdf.columns and gdf['nearest_highway_km'].notna().any():
        pts_pop = norm_pop * 12.0
        pts_highway = np.where(gdf['nearest_highway_km'] <= 5.0, 8.0, 0.0)
        gdf['pts_pop_corridor'] = pts_pop + pts_highway 
    else:
        gdf['pts_pop_corridor'] = norm_pop * 20.0
    
    # Site Suitability
    gdf['pts_suitability'] = 15.0 

    # Reundancy Penalty
    gdf['redundancy_penalty'] = np.minimum(gdf['nearby_gas_1km'].fillna(0) * 3.33, 10.0)

    # Planned Infrastructure Penalty
    gdf['planned_infra_penalty'] = 0.0

    # Combine score components and clamp
    gdf['raw_score'] = (
        gdf['pts_local_gap'] +
        gdf['pts_dcfc_dist'] + 
        gdf['pts_pop_corridor']
        + gdf['pts_suitability']
        - gdf['redundancy_penalty']
        - gdf['planned_infra_penalty']
    )
    
    # Clamp Score between 0-100
    gdf['final_score'] = np.clip(gdf['raw_score'], 0.0, 100.0)

    # Sort descending and assign rank (1 = best candidate)
    gdf = gdf.sort_values(by='final_score', ascending=False).reset_index(drop=True)
    gdf['rank'] = gdf.index + 1

    print(f"Score calculation complete!")

    
    return gdf

if __name__ == "__main__":
    gas, ev, deserts, highways = load_data()

    print("Attaching gas stations to respective tracts...")
    gas = gas_to_tracts(gas, deserts)

    print("Finding nearest DCFC to gas station...")
    gas = nearest_dcfc(ev,gas)

    print("Finding nearby gas stations within 1 km...")
    gas = calculate_redundant_gas(gas)

    print("Finding nearest highway to gas station...")
    gas = nearest_highway(gas, highways)

    print("Calculating final conversion scores...")
    gas = calculate_gas_conv(gas)   

    gas.to_parquet(PROCESSED_DIR / "conversion_candidates.paruqet")
    gas.to_csv(TABLES_DIR / "conversion_candidates", index=False)



