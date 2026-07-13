"""
Pipeline that reads raw snapshots, cleans attributes, creates geometries,
projects to California Albers, and writes fast processed files
"""

import sys
import re
from pathlib import Path
import pandas as pd
import geopandas as gpd
from geopandas import GeoDataFrame

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, PROCESSED_DIR, TODAY_STR, CRS_ANALYSIS

def find_latest_files(directory: Path = RAW_DIR) -> tuple[Path, Path]:
    """Find the latest EV CSV and Gas GeoJSON raw snapshots."""
    ev_files = sorted(directory.glob('afdc_ev_stations_*.csv'))
    gas_files = sorted(directory.glob('cec_gas_stations_*.geojson'))

    # Guard: check before attempting to index the list
    if not ev_files:
        print(f"[ERROR] No EV CSV found in {directory}")
        sys.exit(1)
    if not gas_files:
        print(f"[ERROR] No Gas GeoJSON found in {directory}")
        sys.exit(1)

    latest_ev_csv = ev_files[-1]
    latest_gas_geojson = gas_files[-1]

    print(f"Latest EV CSV:      {latest_ev_csv}")
    print(f"Latest Gas GeoJSON: {latest_gas_geojson}")

    return latest_ev_csv, latest_gas_geojson


def clean_ev_station(raw_path: Path) -> GeoDataFrame:
    """Clean raw AFDC EV station CSV into an analysis-ready GeoDataFrame."""
    df = pd.read_csv(raw_path)

    # Standardize column headers to lowercase snake_case
    df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

    # Convert latitude and longitude to numeric values
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

    # Drop missing coordinates
    df = df.dropna(subset=['latitude', 'longitude'])

    # Filter to CA only and enforce bounding box
    if 'state' in df.columns:
        df = df[df['state'] == 'CA'].copy()
    df = df[(df['latitude'] > 32.5) & (df['latitude'] < 43.0)]
    df = df[(df['longitude'] > -125.0) & (df['longitude'] < -113.0)]

    # Filter to public access stations
    if 'access_code' in df.columns:
        df = df[df['access_code'].str.lower() == 'public'].copy()

    # Convert port counts to numeric (AFDC column names from raw CSV)
    port_cols = {
        'ev_dc_fast_num': 'dcfc_ports',
        'ev_level1_evse_num': 'level1_ports',
        'ev_level2_evse_num': 'level2_ports',
    }
    for raw_col, clean_col in port_cols.items():
        if raw_col in df.columns:
            df[clean_col] = pd.to_numeric(df[raw_col], errors='coerce').fillna(0).astype(int)
        else:
            df[clean_col] = 0

    # Derived fields
    df['total_ev_ports'] = df['dcfc_ports'] + df['level1_ports'] + df['level2_ports']
    df['has_dcfc'] = df['dcfc_ports'] > 0
    df['source'] = 'afdc'
    df['source_snapshot_date'] = raw_path.stem.split('_')[-1]

    # Create geometry and assign native CRS (WGS84)
    geometry = gpd.points_from_xy(df['longitude'], df['latitude'])
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

    # Project to California Albers for analysis
    gdf = gdf.to_crs(CRS_ANALYSIS)

    return gdf


def clean_gas_station(raw_path: Path) -> GeoDataFrame:
    """Clean raw CEC gas station GeoJSON into an analysis-ready GeoDataFrame."""
    gas_df = gpd.read_file(raw_path)

    # Drop null geometries
    gas_df = gas_df[gas_df.geometry.notna()].copy()

    # Project to California Albers
    gas_df = gas_df.to_crs(CRS_ANALYSIS)

    # Deduplicate by rounded coordinates (~10 m precision)
    gas_df['x_round'] = gas_df.geometry.x.round(-1)
    gas_df['y_round'] = gas_df.geometry.y.round(-1)
    gas_df = gas_df.drop_duplicates(subset=['x_round', 'y_round'])
    gas_df = gas_df.drop(columns=['x_round', 'y_round'])

    # Rename source-specific columns to stable schema
    gas_df = gas_df.rename(columns={
        'OBJECTID': 'station_id',
        'Facility_Name': 'name',
        'Facility_Address': 'address',
        'City': 'city',
        'ZIP_Code': 'zip',
    })

    gas_df['source'] = 'cec'

    # Filter out non-California rows
    gas_df = gas_df[(gas_df.geometry.y > 32.5) & (gas_df.geometry.y < 43.0)]
    gas_df = gas_df[(gas_df.geometry.x > -125.0) & (gas_df.geometry.x < -113.0)]

    # Extract YYYY-MM-DD date from filename
    match = re.search(r'\d{4}-\d{2}-\d{2}', raw_path.name)
    if not match:
        raise ValueError(f"No YYYY-MM-DD date found in filename: {raw_path.name}")
    gas_df['source_snapshot_date'] = match.group(0)

    keep_cols = ['station_id', 'name', 'address', 'city', 'zip', 'source', 'source_snapshot_date', 'geometry']
    gas_df = gas_df[[col for col in keep_cols if col in gas_df.columns]]

    return gas_df


def save_processed(gdf: GeoDataFrame, filename: str) -> Path:
    """Save a GeoDataFrame to GeoParquet in the processed directory."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / filename
    gdf.to_parquet(out_path, index=False)
    print(f"Saved: {out_path}  ({len(gdf)} rows)")
    return out_path


if __name__ == '__main__':
    ev_path, gas_path = find_latest_files()

    print(f"\nCleaning EV stations...")
    ev_clean = clean_ev_station(ev_path)
    print(f"  Raw rows read:  (from {ev_path.name})")
    print(f"  Clean rows:     {len(ev_clean)}")
    save_processed(ev_clean, "ev_stations.parquet")

    print(f"\nCleaning gas stations...")
    gas_clean = clean_gas_station(gas_path)
    print(f"  Clean rows:     {len(gas_clean)}")
    save_processed(gas_clean, "gas_stations.parquet")

    print(f"\nDone. CRS: {ev_clean.crs}")
