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
import pandas as pd
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


def load_planned(path: Path = None) -> gpd.GeoDataFrame | None:
    """Loads planned (not yet open) EV stations, if the cleaning step produced them."""
    if path is None:
        path = PROCESSED_DIR / "ev_stations_planned.parquet"
    if not path.exists():
        print(f"[WARN] {path.name} not found; planned-infrastructure penalty will be 0")
        return None
    planned = gpd.read_parquet(path).to_crs(CRS_ANALYSIS)
    print(f"Loaded {len(planned)} planned EV stations")
    return planned

### Attach gas stations to tracts
def gas_to_tracts(
    gas: gpd.GeoDataFrame,
    deserts: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Attaches tract scores to respective gas stations"""

    # Subset desert tracts to keep only geometry and certain metadata columns
    tract_cols = [
        'GEOID',
        'county',
        'desert_score',
        'severity_score',
        'total_population',
        'population_density',
        'geometry'
    ]
    tract_subset = deserts[[c for c in tract_cols if c in deserts.columns]]
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
    penalty_per_station: float=3.33,
    max_penalty: float=10.0
) -> gpd.GeoDataFrame:
    """
    Counts other gas stations within 1 km of each station (excluding itself) and 
    converts the count into a score penalty (subtracting up to 10 points).
    """

    gdf = gas.copy()

    # Extract projected coords
    coords = np.column_stack([gdf.geometry.x, gdf.geometry.y])

    # Build spatial KDTree
    tree = cKDTree(coords)

    # Find all stations within 1 km
    gdf['nearby_gas_1km'] = [len(neighbors) - 1 for neighbors in tree.query_ball_point(coords, r=radius_meters)]

    # Convert nearby count into a penalty
    gdf['redundancy_penalty'] = np.minimum(gdf['nearby_gas_1km'] * penalty_per_station, max_penalty)
    
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

### Planned infrastructure
def planned_dcfc_penalty(
    gas: gpd.GeoDataFrame,
    planned: gpd.GeoDataFrame = None,
    full_penalty_km: float = 2.0,
    partial_penalty_km: float = 5.0,
    max_penalty: float = 10.0,
) -> gpd.GeoDataFrame:
    """
    Penalizes sites that already have a planned (AFDC status 'P') DCFC
    nearby: the full penalty within `full_penalty_km`, half within
    `partial_penalty_km`, otherwise 0. Adds `nearest_planned_dcfc_km` and
    `planned_infra_penalty`.
    """
    gas = gas.copy()
    if planned is None or planned.empty or 'dcfc_ports' not in planned.columns:
        gas['nearest_planned_dcfc_km'] = np.nan
        gas['planned_infra_penalty'] = 0.0
        return gas

    planned_dcfc = planned[planned['dcfc_ports'] > 0].to_crs(gas.crs)
    if planned_dcfc.empty:
        gas['nearest_planned_dcfc_km'] = np.nan
        gas['planned_infra_penalty'] = 0.0
        return gas

    nearest = gpd.sjoin_nearest(
        gas[['station_id', 'geometry']],
        planned_dcfc[['geometry']],
        how='left',
        distance_col='distance_meters'
    ).drop_duplicates(subset=['station_id'])
    nearest['nearest_planned_dcfc_km'] = nearest['distance_meters'] / 1000.0
    gas = gas.merge(nearest[['station_id', 'nearest_planned_dcfc_km']], on='station_id', how='left')

    dist = gas['nearest_planned_dcfc_km']
    gas['planned_infra_penalty'] = np.select(
        [dist <= full_penalty_km, dist <= partial_penalty_km],
        [max_penalty, max_penalty / 2.0],
        default=0.0,
    )
    return gas


def prepare_candidate_base(
    gas: gpd.GeoDataFrame,
    ev: gpd.GeoDataFrame,
    highways: gpd.GeoDataFrame = None,
    planned: gpd.GeoDataFrame = None,
) -> gpd.GeoDataFrame:
    """
    Computes the per-station inputs that do not depend on tract scoring or
    scenario settings: nearest open DCFC, nearest highway, and the planned
    DCFC penalty. Tract attributes and redundancy are added per scenario.
    """
    base = nearest_dcfc(ev, gas)
    base = nearest_highway(base, highways)
    base = planned_dcfc_penalty(base, planned)
    return base


def score_candidates(
    candidate_base: gpd.GeoDataFrame,
    deserts: gpd.GeoDataFrame,
    redundancy_radius_m: float = 1000.0,
) -> gpd.GeoDataFrame:
    """Attaches tract scores, computes redundancy, and returns ranked candidates."""
    tract_cols = ['GEOID', 'county', 'desert_score', 'severity_score', 'total_population', 'population_density']
    base = candidate_base.drop(columns=[c for c in tract_cols if c in candidate_base.columns])
    gas = gas_to_tracts(base, deserts.to_crs(base.crs))
    gas = calculate_redundant_gas(gas, radius_meters=redundancy_radius_m)
    return calculate_gas_conv(gas)


def generate_rationale(row: pd.Series) -> str:
    """Builds a readable rationale string summarizing top score drivers for candidate site."""
    reasons = []
    
    # 1. DCFC distance
    dcfc_km = row.get('nearest_dcfc_km', np.nan)
    if pd.notna(dcfc_km):
        if dcfc_km >= 15.0:
            reasons.append("15+ km from nearest DCFC")
        elif dcfc_km >= 3.0:
            reasons.append(f"{dcfc_km:.1f} km from nearest DCFC")

    # 2. Charging desert context
    severity = row.get('severity_score', '')
    d_score = row.get('desert_score', np.nan)
    if severity == 'severe_desert':
        reasons.append(f"severe charging desert (score: {d_score:.1f})")
    elif severity == 'moderate_desert':
        reasons.append(f"moderate charging desert (score: {d_score:.1f})")

    # 3. Highway corridor context
    h_km = row.get('nearest_highway_km', np.nan)
    if pd.notna(h_km) and h_km <= 5.0:
        reasons.append(f"major corridor site ({h_km:.1f} km to highway)")

    # 4. Low competition / isolation
    nearby = row.get('nearby_gas_1km', 0)
    if nearby == 0:
        reasons.append("isolated site (0 gas stations within 1 km)")

    if not reasons:
        return f"Conversion suitability score: {row.get('final_score', 0):.1f}"
        
    return "; ".join(reasons[:3])

### Apply score components
def calculate_gas_conv(
    gas: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Applies score components, calculates final score (0-100), builds rationale, and ranks candidate sites
    """

    print("Calculating gas conversion score ...")
    gdf = gas.copy()

    # Local charging gap 
    max_desert = gdf['desert_score'].max() if gdf['desert_score'].max() > 0 else 1.0
    gdf['pts_local_gap'] = (gdf['desert_score'].fillna(0) / max_desert) * 30.0

    # Nearest DCFC distance
    gdf['pts_dcfc_dist'] = np.minimum(gdf['nearest_dcfc_km'].fillna(15.0), 15.0) / 15.0 * 25.0

    # Population and corridor context. Census tracts are drawn to hold
    # roughly similar populations, so raw tract population says little about
    # local demand; use the percentile rank of tract population density
    # across candidate sites instead (stations outside a scored tract get 0).
    density = pd.to_numeric(gdf['population_density'], errors='coerce')
    n_valid = density.notna().sum()
    if n_valid > 1:
        norm_pop = ((density.rank(method='average') - 1) / (n_valid - 1)).fillna(0)
    else:
        norm_pop = pd.Series(0.0, index=gdf.index)

    if 'nearest_highway_km' in gdf.columns and gdf['nearest_highway_km'].notna().any():
        pts_pop = norm_pop * 12.0
        pts_highway = np.where(gdf['nearest_highway_km'] <= 5.0, 8.0, 0.0)
        gdf['pts_pop_corridor'] = pts_pop + pts_highway 
    else:
        gdf['pts_pop_corridor'] = norm_pop * 20.0
    
    # Site Suitability
    gdf['pts_suitability'] = 15.0 

    # Redundancy Penalty
    if 'redundancy_penalty' not in gdf.columns:
        gdf['redundancy_penalty'] = np.minimum(gdf['nearby_gas_1km'].fillna(0) * 3.33, 10.0)

    # Planned Infrastructure Penalty (see planned_dcfc_penalty)
    if 'planned_infra_penalty' not in gdf.columns:
        gdf['planned_infra_penalty'] = 0.0
    gdf['planned_infra_penalty'] = gdf['planned_infra_penalty'].fillna(0.0)

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

    # Generate rationale column
    gdf['rationale'] = gdf.apply(generate_rationale, axis=1)

    print(f"Score calculation complete!")

    return gdf

if __name__ == "__main__":
    gas, ev, deserts, highways = load_data()

    print("Computing nearest DCFC, nearest highway and planned DCFC for each gas station...")
    base = prepare_candidate_base(gas, ev, highways, load_planned())

    print("Attaching tract scores, redundancy (1 km) and final conversion scores...")
    gas = score_candidates(base, deserts, redundancy_radius_m=1000.0)

    save_path = PROCESSED_DIR / "conversion_candidates.parquet"
    gas.to_parquet(save_path)
    gas.to_csv(TABLES_DIR / "conversion_candidates.csv", index=False)

    print(f"Successfully saved conversion candidates parquet file to {save_path}")



