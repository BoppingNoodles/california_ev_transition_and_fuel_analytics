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
from config import CEC_GAS_STATIONS_URL, RAW_DIR, TODAY_STR

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

def save_raw(features: list[dict]) -> tuple[Path, Path]:
    RAW_DIR.mkdir(parents=True,exist_ok=True)
    geojson_path = RAW_DIR / f'cec_gas_stations_{TODAY_STR}.geojson'
    csv_path = RAW_DIR / f'cec_gas_stations_{TODAY_STR}.csv'

    fc = {'type': 'FeatureCollection', 'features': features}
    with open(geojson_path, 'w') as f:
        json.dump(fc,f)

    rows = []
    for feat in features:
        props = dict(feat.get("properties", {}))
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates", [None, None])
        props["longitude"] = coords[0]
        props["latitude"] = coords[1]
        rows.append(props)
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)

    print(f"Saved raw GeoJson: {geojson_path}")
    print(f"Saved flat CSV: {csv_path}")
    return geojson_path, csv_path
def qc_summary(features: list[dict]) -> None:
    n = len(features)
    n_valid_geom = sum(
        1 for f in features
        if f.get("geometry") and f["geometry"].get("coordinates") not in (None, [None, None])
    )
    print("\n--- QC summary ---")
    print(f"Total records:     {n}")
    print(f"Valid geometries:  {n_valid_geom} ({n_valid_geom / n:.1%})" if n else "Valid geometries: 0")

    