"""
This file associates infrastructure points with Census tracts and calculates
accessibility metrics
"""
import re
import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, EXTERNAL_DIR, RAW_DIR, CRS_ANALYSIS

### Load and align CRS
def load_tracts(tracts_dir: Path=None) -> gpd.GeoDataFrame:
    """Load California Census Tract geometries"""
    if not tracts_dir:
        tracts_dir = EXTERNAL_DIR / "california_tracts"
    
    shp_files = list(tracts_dir.glob('*.shp'))
    if not shp_files:
        raise FileNotFoundError(f"No tract shapefile found in {tracts_dir}. Run src/ingest/fetch_census.py first.")
    
    tracts = gpd.read_file(shp_files[0])
    print(f"Found {len(tracts)} tracts at {tracts_dir}")

    return tracts

def load_demographics(dir: Path=RAW_DIR) -> pd.DataFrame:
    """Load California ACS CSV"""
    census_files = sorted(dir.glob('census_data_*.csv'))

    if not census_files:
        raise FileNotFoundError(f"No census_data_*.csv found in {dir}. Run src/ingest/fetch_census.py first.")

    census_csv = pd.read_csv(census_files[-1], dtype={"GEOID": str, "state": str, "county": str, "tract":str})

    print(f"Loaded {census_files[-1].name} with {len(census_csv)} tracts")

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

def parse_county_name(acs_name) -> str | None:
    """Extracts the county name from an ACS tract NAME (';' or ',' separated)."""
    if not isinstance(acs_name, str):
        return None
    for part in re.split(r"[;,]", acs_name):
        part = part.strip()
        if part.endswith(" County"):
            return part[: -len(" County")]
    return None


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
    keep = ["GEOID", "ALAND", "geometry"] if "ALAND" in tracts.columns else ["GEOID", "geometry"]
    tract_base = tracts[keep].copy()

    # Ensure GEOID is a string on both sides to prevent silent join mismatches
    tract_base["GEOID"] = tract_base["GEOID"].astype(str)
    demographics = demographics.copy()
    demographics["GEOID"] = demographics["GEOID"].astype(str)

    n_before = len(tract_base)

    # County name from the ACS NAME field, e.g.
    # "Census Tract 4001; Alameda County; California" -> "Alameda"
    # The raw ACS 'county' column is a FIPS code ('001'); drop it so 'county'
    # only ever holds a name (or is null when NAME is unavailable).
    demographics = demographics.drop(columns=["county"], errors="ignore")
    if "NAME" in demographics.columns:
        demographics["county"] = demographics["NAME"].map(parse_county_name)

    # Left-join so every tract geometry is preserved even if ACS data is missing
    acs_cols = [c for c in ["GEOID", "county", "total_population", "median_income"] if c in demographics.columns]
    tract_base = tract_base.merge(
        demographics[acs_cols], on="GEOID", how="left"
    )

    n_after = len(tract_base)
    n_matched = tract_base["total_population"].notna().sum()
    print(f"Tracts before join : {n_before}")
    print(f"Tracts after join  : {n_after}")
    print(f"Tracts with ACS pop: {n_matched}  |  missing: {n_after - n_matched}")

    # Area in square kilometres. TIGER tract polygons include water (bays,
    # lakes, ocean out to the 3-mile line), which deflates densities in
    # coastal tracts, so densities use land area (ALAND, in m^2) when
    # available. Total polygon area is kept for reference.
    tract_base["tract_total_area_sq_km"] = tract_base.geometry.area / 1_000_000
    if "ALAND" in tract_base.columns:
        tract_base["tract_area_sq_km"] = pd.to_numeric(tract_base["ALAND"], errors="coerce") / 1_000_000
        tract_base = tract_base.drop(columns=["ALAND"])
    else:
        print("[WARN] ALAND not in tract file; using total polygon area (includes water)")
        tract_base["tract_area_sq_km"] = tract_base["tract_total_area_sq_km"]

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

    id_col = "station_id" if "station_id" in joined.columns else "id"
    ev_agg = joined.groupby('GEOID').agg(
        ev_station_count=(id_col, "count"),
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

### Aggregate gas infrastructure
def agg_gas(
    gas: gpd.GeoDataFrame,
    tract_base: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Aggregate gas infrastructure to California tract base"""

    # Spatially join gas stations to tracts
    joined = gpd.sjoin(gas,tract_base,how='left', predicate='within')

    # Group by GEOID
    gas_agg = joined.groupby("GEOID").agg(
        gas_station_count=("station_id", "count")
    ).reset_index()

    # Join counts back to all tracts
    tract_base = tract_base.merge(gas_agg,on='GEOID', how='left')
    
    # Fill missing gas counts with 0
    fill_cols = ['gas_station_count']
    tract_base[fill_cols] = tract_base[fill_cols].fillna(0)

    return tract_base

### Tract reference points (population-weighted centroids)
def add_reference_points(
    tract_base: gpd.GeoDataFrame,
    centroids_path: Path = None,
) -> gpd.GeoDataFrame:
    """
    Adds `ref_x` / `ref_y` (in the tract CRS) marking where each tract's
    residents are, used as the origin for distance and buffer metrics.

    Uses the Census 2020 population-weighted centroid when available and
    falls back to `representative_point()`, which (unlike the geometric
    centroid) is guaranteed to fall inside the tract polygon.
    """
    if centroids_path is None:
        centroids_path = EXTERNAL_DIR / "cenpop2020_tract_centroids_06.csv"

    tract_base = tract_base.copy()
    fallback = tract_base.geometry.representative_point()
    ref = gpd.GeoSeries(fallback.values, index=tract_base.index, crs=tract_base.crs)
    source = pd.Series("representative_point", index=tract_base.index)

    if centroids_path.exists():
        cenpop = pd.read_csv(centroids_path, dtype={"STATEFP": str, "COUNTYFP": str, "TRACTCE": str})
        cenpop["GEOID"] = cenpop["STATEFP"].str.zfill(2) + cenpop["COUNTYFP"].str.zfill(3) + cenpop["TRACTCE"].str.zfill(6)
        pts = gpd.GeoDataFrame(
            cenpop[["GEOID"]],
            geometry=gpd.points_from_xy(cenpop["LONGITUDE"], cenpop["LATITUDE"]),
            crs="EPSG:4326",
        ).to_crs(tract_base.crs)
        lookup = pts.set_index("GEOID").geometry
        matched = tract_base["GEOID"].astype(str).map(lookup)
        has_match = matched.notna()
        ref[has_match] = gpd.GeoSeries(matched[has_match].values, index=matched[has_match].index, crs=tract_base.crs)
        source[has_match] = "population_weighted"
    else:
        print(f"[WARN] {centroids_path.name} not found; using representative points for all tracts")

    tract_base["ref_x"] = ref.x
    tract_base["ref_y"] = ref.y
    tract_base["ref_point_source"] = source
    print(f"Reference points: {source.value_counts().to_dict()}")
    return tract_base


def reference_points(tract_base: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Returns a GEOID + point GeoDataFrame of each tract's reference point."""
    if {"ref_x", "ref_y"}.issubset(tract_base.columns):
        geometry = gpd.points_from_xy(tract_base["ref_x"], tract_base["ref_y"])
    else:
        geometry = tract_base.geometry.representative_point().values
    return gpd.GeoDataFrame(tract_base[["GEOID"]].copy(), geometry=geometry, crs=tract_base.crs)


### Calculate gas access near tract reference points
def gas_access(
    gas: gpd.GeoDataFrame,
    tract_base: gpd.GeoDataFrame,
    buffer_m: float = 2000.0,
) -> gpd.GeoDataFrame:
    """
    Counts gas stations within `buffer_m` metres of each tract's reference
    point and stores it in `gas_access_count_2km` (the column name is kept
    stable so downstream scoring works for any buffer size).
    """
    tract_base = tract_base.drop(columns=["gas_access_count_2km"], errors="ignore")

    # Buffer around each tract reference point (EPSG:3310, metres)
    buffer = reference_points(tract_base)
    buffer['geometry'] = buffer.geometry.buffer(buffer_m)

    # Spatial join
    joined = gpd.sjoin(gas[['station_id', 'geometry']], buffer, predicate="intersects")

    # Count nearby gas stations
    gas_counts = joined.groupby('GEOID').agg(
        gas_access_count_2km=('station_id', 'count')
    ).reset_index()

    # Merge back to tract base
    tract_base = tract_base.merge(gas_counts, on='GEOID', how='left')

    # Fill in missing counts with 0
    tract_base['gas_access_count_2km'] = tract_base['gas_access_count_2km'].fillna(0)

    return tract_base

### Calculate nearest DCFC distance
def calculate_nearest_dcfc(
    ev: gpd.GeoDataFrame,
    tract_base: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Calculates straight-line distance to the nearest DCFC from each tract reference point"""

    # Filter EV stations where dcfc_ports > 0
    ev_stations = ev.copy()
    ev_stations = ev_stations[ev_stations['dcfc_ports'] > 0]

    # Population-weighted reference point of each tract
    centroids = reference_points(tract_base)

    # Calculate nearest neighbor distance using sjoin_nearest
    nearest = gpd.sjoin_nearest(
        centroids[['GEOID', 'geometry']],
        ev_stations[['geometry']],
        how='left',
        distance_col='distance_meters'
    )

    # Convert distance from meters to kilometers
    nearest['nearest_dcfc_km'] = nearest['distance_meters'] / 1000.0
    nearest = nearest.drop_duplicates(subset=['GEOID'])

    # Merge back onto tract_base
    tract_base = tract_base.merge(
        nearest[['GEOID', 'nearest_dcfc_km']],
        on='GEOID',
        how='left'
    )

    return tract_base

### Create final metric columns
def create_final_metrics(
    tract_base: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Creates the final metric columns: 
        - `ports_per_sq_km`: EV ports per square kilometer
        - `ports_per_1000`: EV ports per 1000 people
        - `dcfc_per_1000`: DCFC ports per 1000 people
    """
    tract = tract_base.copy()

    tract['ports_per_sq_km'] = (tract['total_ev_ports'] / tract['tract_area_sq_km']).where(tract['tract_area_sq_km'] > 0, 0.0)
    tract['ports_per_1000'] = (tract['total_ev_ports'] / tract['total_population'] * 1000.0).where(tract['total_population'] > 0, 0.0)
    tract['dcfc_per_1000'] = (tract['dcfc_ports'] / tract['total_population'] * 1000.0).where(tract['total_population'] > 0, 0.0)

    return tract

### Save intermediate metrics
def save_metrics(
    tract_base: gpd.GeoDataFrame,
    output_path: Path = None
) -> Path:
    """Saves the completed tract coverage metrics GeoDataFrame to Parquet format"""
    
    if output_path is None:
        output_path = PROCESSED_DIR / "tract_coverage_metrics.parquet"

    tract_base.to_parquet(output_path)
    print(f"Saved tract coverage metrics to {output_path}")

    return output_path

if __name__ == "__main__":
    print("--- Starting Phase 3.1: Tract Coverage Metrics Calculation ---")

    # Step 1: Load and align CRS
    tracts = load_tracts()
    demographics = load_demographics()
    ev = load_ev()
    gas = load_gas()
    tracts_proj, ev_proj, gas_proj = align_crs(tracts, ev, gas)
    print("\nStep 1 complete — all layers loaded and aligned to EPSG:3310.")

    # Step 2: Prepare tract base
    tract_base = prepare_tract_base(tracts_proj, demographics)
    print("\nStep 2 complete — tract base prepared with demographics and area metrics.")
    print(tract_base[["GEOID", "total_population", "tract_area_sq_km", "population_density"]].head(2))
    tract_base = add_reference_points(tract_base)

    # Step 3: Aggregate EV infrastructure
    tract_base = agg_ev(ev_proj, tract_base)
    print("\nStep 3 complete — EV infrastructure aggregated to tracts.")
    print(tract_base[["GEOID", "ev_station_count", "total_ev_ports", "dcfc_ports"]].head(2))

    # Step 4: Aggregate gas infrastructure
    tract_base = agg_gas(gas_proj, tract_base)
    print("\nStep 4 complete — Gas infrastructure aggregated to tracts.")
    print(tract_base[["GEOID", "gas_station_count"]].head(2))

    # Step 5: Gas access near tract reference points (2 km buffer)
    tract_base = gas_access(gas_proj, tract_base, buffer_m=2000)
    print("\nStep 5 complete — Gas access within 2 km of population-weighted centroids calculated.")
    print(tract_base[["GEOID", "gas_access_count_2km"]].head(2))

    # Step 6: Calculate distance to nearest DCFC station
    tract_base = calculate_nearest_dcfc(ev_proj, tract_base)
    print("\nStep 6 complete — Nearest DCFC distance calculated.")
    print(tract_base[["GEOID", "nearest_dcfc_km"]].head(2))

    # Step 7: Create final metric columns
    tract_base = create_final_metrics(tract_base)
    print("\nStep 7 complete — Final density and population rates computed.")
    print(tract_base[["GEOID", "ports_per_sq_km", "ports_per_1000", "dcfc_per_1000"]].head(2))

    # Step 8: Save intermediate metrics file
    print("\nStep 8: Saving intermediate metrics...")
    save_metrics(tract_base)

    print("\nPhase 3.1 pipeline executed successfully.")


