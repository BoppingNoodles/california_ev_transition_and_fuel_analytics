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

sys.path.append(str(Path(__file__).resolve().parent / "src"))
from config import AFDC_API_URL, NREL_API_KEY, RAW_DIR, TODAY_STR, CA_STATE_ABBR

KEEP_FIELDS = [
    'id', 'station_name', 'street_address', 'city', 'state','zip',
    'latitude', 'longitude', 'status_code', 'access_code', 'ev_connector_types', 'ev_dc_fast_num', 'ev_level1_evse_num',
    'ev_level2_evse_num', 'ev_network', 'ev_pricing', 'facility_type', 'funding_sources', 'date_last_confirmed', 'open_date','owner_type_code'
]

def fetch_afdc_stations(state: str = CA_STATE_ABBR, fuel_type: str = 'ELEC') -> list:
    """Fetch all matching stations from the AFDC API"""
    params = {
        'api_key': NREL_API_KEY,
        'fuel_type': fuel_type,
        'state': state,
        'status': 'all',
        'access': 'all',
        'limit': 'all',
    }
    resp = requests.get(AFDC_API_URL, params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    stations = payload.get('fuel_stations', [])
    print(f"Fetched {len(stations)} stations from AFDC (station_counts total_results="
          f"{payload.get('station_counts', {}).get('total', 'n/a')})")
    return stations

def save_raw(stations: list[dict]) -> tuple[Path, Path]:
    """Save fetched stations to json file and flattened csv file"""
    RAW_DIR.mkdir(parents=True,exist_ok=True)
    json_path = RAW_DIR / f"afdc_ev_stations_{TODAY_STR}.json"
    csv_path = RAW_DIR / f"afdc_ev_stations_{TODAY_STR}.csv"

    with open(json_path, 'w') as f:
        json.dump(stations, f, indent=2)

    df = pd.json_normalize(stations)
    present_cols = [c for c in KEEP_FIELDS if c in df.columns]
    df[present_cols].to_csv(csv_path, index=False)

    print(f"Saved raw JSON : {json_path}")
    print(f"Saved flat csv: {csv_path}")

    return json_path, csv_path

def quality_control(stations: list[dict]) -> None:
    """Quality control to check pulled data (record count, valid lat/lon rate, non-California rows,
    access code breakdown, total DCFC ports)"""
    df = pd.json_normalize(stations)
    n = len(df)
    n_valid_geom = df[['latitude', 'longitude']].dropna().shape[0] if n else 0
    print("\n--- QC Summary ---")
    print(f" Total records:  {n}")
    print(f"Valid lat/lon:   {n_valid_geom} ({n_valid_geom / n:.1%})" if n else "Valid lat/lon: 0")
    if "state" in df.columns:
        non_ca = df[df['state'] != CA_STATE_ABBR]
        print(f" Non-California rows:  {len(non_ca)}")
    if 'access_code' in df.columns:
        print(f"Access Code Breakdown: \n", df['access_code'].value_counts(dropna=False).to_string())
    if 'ev_dc_fast_num' in df.columns:
        dfdc_total = pd.to_numeric(df['ev_dc_fast_num'], errors='coerce').fillna(0).sum()
        print(f"DFDC ports: {int(dfdc_total)}")

if __name__ == '__main__':
    t0 = time.time()
    stations = fetch_afdc_stations()
    if not stations:
        print("[WARNING]: Zero AFDC Stations fetched. ")
        sys.exit(1)
    save_raw(stations)
    quality_control(stations)
    print(f"Time taken: {time.time() - t0:.1f}s")