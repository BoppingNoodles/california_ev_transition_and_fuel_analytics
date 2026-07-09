"""
Pipeline that reads raw snapshots,  cleans attributes, creates geometries,
projects to California Albers, and writes fast processed files
"""

import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd
from geopandas import GeoDataFrame

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, TODAY_STR, CENSUS_API_KEY

def find_latest_files(directory: Path=RAW_DIR) -> tuple[Path, Path]:
    """Find the latest EV CSV and Gas GeoJSON"""
    latest_ev_csv = sorted(RAW_DIR.glob('afdc_ev_stations_*.csv'))[-1]
    latest_gas_geojson = sorted(RAW_DIR.glob('*cec_gas_station_*.geojson'))[-1]

    print(f"Latest EV CSV: {latest_ev_csv}")
    print(f"Latest Gas GeoJSON: {latest_gas_geojson}")

    if not latest_ev_csv or not latest_gas_geojson:
        if not latest_ev_csv:
            print(f"No EV CSV found in {RAW_DIR}")
        if not latest_gas_geojson:
            print(f"No Gas GeoJSON found in {RAW_DIR}")
        sys.exit(1)
    
    return latest_ev_csv, latest_gas_geojson
    

def clean_ev_station(raw_path: Path) -> GeoDataFrame:
    # Load raw csv
    df = pd.read_csv(raw_path)

    # Standardize column names into lowercase snake case
    cols = df.columns
    for col in cols:
        df[col] = df[col].strip().lower().replace(' ', '_')
    
    # Convert latitude and longitude into numeric values
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

    # Conver port counts to numeric
    for col in ['ev_dc_fast_count', 'ev_level_1_count', 'ev_level_2_count']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    # Create a 'total_ev_ports' field
    df['total_ev_ports'] = df['ev_dc_fast_count'] + df['ev_level_1_count'] + df['ev_level_2_count']

    # Create a 'has_dcfc' boolean
    df['has_dcfc'] = df['ev_dc_fast_count'] > 0

    # Drop missing coordinates
    df = df.dropna(subset=['latitude', 'longitude'])

    # Filter to CA only
    df = df[df['state'] == 'CA'].copy()
    df = df[(df['latitude'] > 32.5) & (df['latitude'] < 43.0)]
    df = df[(df['longitude'] > -125.0) & (df['longitude'] < -113.0)]

    # Filter to public access
    if 'access_code' in df.columns:
        df = df[df['access_code'].str.lower() == 'public'].copy()

    # Create geometry and assign CRS AS EPSG:4325
    geometry = gpd.points_from_xy(df['longitude'], df['latitude'])
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

    # Project to EPSG:3310
    gdf = gdf.to_crs("EPSG:3310")

    return gdf
    
def clean_gas_station():
    gas_geojson = find_latest_files()[1]
    gas = gpd.read_file(gas_geojson)
