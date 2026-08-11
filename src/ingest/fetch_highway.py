"""
This file fetches California highway data from Open Streetmap using Python

Output:
     - GeoPandasDataFrame: `data/processed/highways.parquet`
"""

import sys 
import osmnx as ox 
from pathlib import Path 

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, PROCESSED_DIR, CRS_ANALYSIS

def fetch_ca_highways():
    """
    Fetch major California highway segments from OpenStreetMap 
    and reproject to ESPG:3110
    """

    print('Fetching California high way data from OpenStreetMap...')

    highway_tags = {'highway': ['motorway', 'trunk', 'primary']}

    gdf = ox.features_from_place('California, USA', tags=highway_tags)

    # Filter to line features
    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()

    # Reproject to ESPG:3110 (California Albers)
    gdf = gdf.to_crs(CRS_ANALYSIS)

    # Save output dataset 
    output_path = PROCESSED_DIR / "highways.parquet"
    gdf.to_parquet(output_path)
    print(f"Saved {len(gdf)} highway segments to {output_path}")

if __name__ == "__main__":
    fetch_ca_highways()
