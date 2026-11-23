"""
This file fetches California highway data from US Census TIGER Primary Roads using Python

Requires the California tract shapefile (see fetch_census.download_ca_tract_geometries),
which is dissolved into a state boundary for clipping.

Output:
     - GeoPandasDataFrame: `data/processed/highways.parquet`
"""

import sys
from pathlib import Path
import geopandas as gpd

sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import PROCESSED_DIR, EXTERNAL_DIR, CRS_ANALYSIS

TIGER_PRIMARY_ROADS_URL = "https://www2.census.gov/geo/tiger/TIGER2024/PRIMARYROADS/tl_2024_us_primaryroads.zip"


def load_ca_boundary(tracts_dir: Path = None) -> gpd.GeoDataFrame:
    """Dissolve the California tract shapefile into a single state boundary polygon."""
    if tracts_dir is None:
        tracts_dir = EXTERNAL_DIR / "california_tracts"
    shp_files = list(tracts_dir.glob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(
            f"No tract shapefile found in {tracts_dir}. Run src/ingest/fetch_census.py first."
        )
    tracts = gpd.read_file(shp_files[0])
    return gpd.GeoDataFrame(geometry=[tracts.geometry.union_all()], crs=tracts.crs)


def fetch_ca_highways(url: str = TIGER_PRIMARY_ROADS_URL, boundary: gpd.GeoDataFrame = None) -> Path:
    """
    Fetch major California highway segments (Interstates & US Primary Highways)
    from US Census TIGER/Line Primary Roads, clipped to the California boundary.

    A bounding-box filter alone keeps roads in Nevada, Oregon, Arizona and
    Mexico (e.g. Las Vegas and Reno interstates), so segments are clipped to
    the actual state polygon.
    """
    print("Fetching California highway data from US Census TIGER/Line...")
    if boundary is None:
        boundary = load_ca_boundary()

    gdf = gpd.read_file(url)

    # Cheap bounding-box prefilter before the exact clip
    gdf = gdf.cx[-124.6:-114.0, 32.4:42.1].copy()

    # Clip to the California boundary in a projected CRS
    gdf = gdf.to_crs(CRS_ANALYSIS)
    boundary = boundary.to_crs(CRS_ANALYSIS)
    gdf = gpd.clip(gdf, boundary)

    # Filter to line features (clipping can produce points/collections at the edge)
    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()

    # Save output dataset
    output_path = PROCESSED_DIR / "highways.parquet"
    gdf.to_parquet(output_path)
    print(f"Saved {len(gdf)} highway segments to {output_path}")
    return output_path


if __name__ == "__main__":
    fetch_ca_highways()
