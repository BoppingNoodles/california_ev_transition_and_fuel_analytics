"""
Pulls all California electric charging stations from the NREL AFDC API
and saves a data raw snapshot
"""
import sys
import json
import time
from pathlib import Path
import requests
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))
from config import AFDC_API_KEY, NREL_API_KEY, RAW_DIR, TODAY_STR, CA_STATE_ABBR

KEEP_FIELDS = [
    'id', 'station_name', 'street_address', 'city', 'state','zip',
    'latitude', 'longitude', 'status_code', 'access_code', 'ev_connector_types', 'ev_dc_fast_num', 'ev_level1_evse_num',
    'ev_level2_evse_num', 'ev_network', 'ev_pricing', 'facility_type', 'funding_sources', 'date_last_confirmed', 'open_date','owner_type_code'
]

def fetch_afdc_stations(state: str = CA_STATE_ABBR, fuel_type: str = 'ELEC') -> list:
    """Fetch all matching statiosn from the AFDC API"""
    params = {
        'api_key': NREL_API_KEY,
        'fuel_type': fuel_type,
        'state': state,
        'status': all,
        'access': all,
    }
    resp = requests.get(AFDC_API_KEY, params=params,timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    stations = payload.get('fuel_stations', [])
    print(f"Fetched {len(stations)} stations from AFDC (station_counts total_results="
          f"{payload.get('station_counts', {}).get('total', 'n/a')})")
    return stations
