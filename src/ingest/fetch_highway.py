"""
This file fetches California highway data from Open Streetmap using Python

Output:
     - GeoPandasDataFrame: `data/processed/highways.parquet`
"""

import sys
from pathlib import Path
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, PROCESSED_DIR, CRS_ANALYSIS

def fetch_ca_highways():
    """
    Fetch major California highway segments (Interstates & US Primary Highways)
    from US Census TIGER/Line Primary Roads dataset.
    """
    print("Fetching California highway data from US Census TIGER/Line...")

    # US Census TIGER Primary Roads dataset
    tiger_url = "https://www2.census.gov/geo/tiger/TIGER2023/PRIMARYROADS/tl_2023_us_primaryroads.zip"
    
    gdf = gpd.read_file(tiger_url)

    # Filter spatially to California bounding box (lon: -124.48 to -114.13, lat: 32.53 to 42.01)
    gdf = gdf.cx[-124.48:-114.13, 32.53:42.01].copy()

    # Filter to line features
    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()

    # Reproject to EPSG:3310 (California Albers)
    gdf = gdf.to_crs(CRS_ANALYSIS)

    # Save output dataset
    output_path = PROCESSED_DIR / "highways.parquet"
    gdf.to_parquet(output_path)
    print(f"Saved {len(gdf)} highway segments to {output_path}")

if __name__ == "__main__":
    fetch_ca_highways()
