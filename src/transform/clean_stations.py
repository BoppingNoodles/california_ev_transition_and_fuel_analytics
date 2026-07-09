"""
Pipeline that reads raw snapshots,  cleans attributes, creates geometries,
projects to California Albers, and writes fast processed files
"""

import sys
from pathlib import Path
import pandas as pd

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, TODAY_STR, CENSUS_API_KEY

def find_latest_files(directory: Path=RAW_DIR):
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

def clean_gas_station():
