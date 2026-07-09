"""
Pipeline that reads raw snapshots,  cleans attributes, creates geometries,
projects to California Albers, and writes fast processed files
"""

import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

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
    

def clean_ev_station():
    ev_csv = find_latest_files()[0]
    df = pd.read_csv(ev_csv)

    # Standardize column names into lowercase snake case
    cols = df.columns
    for col in cols:
        df[col] = df[col].strip().lower().replace(' ', '_')

def clean_gas_station():
    gas_geojson = find_latest_files()[1]
    gas = gpd.read_file(gas_geojson)
