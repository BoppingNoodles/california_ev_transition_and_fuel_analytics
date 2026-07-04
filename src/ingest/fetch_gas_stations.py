"""
Pull all California Gas Stations from the CEC ArcGIS FeatureServer and 
saving a raw GeoJSON snapshot
"""

import sys
import json
import requests
import time
from pathlib import Path
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))
from config import CEC_GAS_STATIONS_URL, RAW_DIR, TODAY_DIR

PAGE_SIZE = 2000

def fetch_gas(url: str=CEC_GAS_STATIONS_URL, page_size: int=PAGE_SIZE) -> list[dict]:
    """Paginate through ArcGIS Featureserver layer using resultOffset"""
    all_features: list[dict] = []
    offset = 0

    while True:
        params = {
            'where': '1=1',
            'outFields': '*',
            'f': 'geojson',
            'resultRecordcount': page_size,
            'resultOffset': offset
        }
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()

        if 'error' in payload:
            raise RuntimeError(f"ArcGIS error: {payload['error']}")
        features = payload.get('features', [])
        all_features.extend(features)
        print(f"  offset={offset:>6}  got {len(features)} features  (running total {len(all_features)})")

        if len(features) < page_size:
            break
        offset += page_size
        time.sleep(1)
    return all_features