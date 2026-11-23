"""
Pulls California 2024 ACS Demographic Data (Name, Total Population, Median Household Income) 
and California Tract Geometries
"""
import sys
from pathlib import Path
import requests
import pandas as pd

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, TODAY_STR, CENSUS_API_KEY

def fetch_acs_ca_demographics_2024(output_path: Path = None) -> Path:
    """Fetches California ACS (American Community Survey) 2024 data from API and saves it as CSV"""
    if not CENSUS_API_KEY:
        print("[ERROR]: CENSUS_API_KEY is not set in your .env file or environment.")
        print("Please sign up for a free Census API key at: https://api.census.gov/data/key_signup.html")
        print("Then add 'CENSUS_API_KEY=your_key_here' to your .env file and restart your kernel.")
        sys.exit(1)

    if output_path is None:
        output_path = RAW_DIR / f"census_data_{TODAY_STR}.csv"
        
    api_url = "https://api.census.gov/data/2024/acs/acs5"

    params = {
        "get": "NAME,B01003_001E,B19013_001E,B08201_001E,B08201_002E", # Name, Population, Income, Total HH, Zero-vehicle HH
        "for": "tract:*",
        "in": "state:06", # Filter to California
        "key": CENSUS_API_KEY
    }
    print(f"Fetching 2024 ACS California 5-year demographics...")
    response = requests.get(api_url, params=params, timeout=120)
    response.raise_for_status()


    data = response.json()
    df = pd.DataFrame(data[1:], columns=data[0])

    # Rename column names
    df = df.rename(columns={
        'B01003_001E': 'total_population',
        'B19013_001E': 'median_income',
        'B08201_001E': 'total_households',
        'B08201_002E': 'no_vehicle_households'
    })

    # Construct GEOID
    df["GEOID"] = df["state"] + df["county"] + df["tract"]

    # Clean data types. ACS encodes missing/suppressed estimates as large
    # negative sentinels (e.g. -666666666 for "not computable"), so any
    # negative value is treated as missing rather than as a real number.
    value_cols = ["total_population", "median_income", "total_households", "no_vehicle_households"]
    for col in value_cols:
        values = pd.to_numeric(df[col], errors="coerce")
        df[col] = values.where(values >= 0)
    for col in ["total_population", "total_households", "no_vehicle_households"]:
        df[col] = df[col].astype("Int64")

    df.to_csv(output_path, index=False)
    print(f"Success! Saved California 2024 ACS 5-year demographics to {output_path}")
    return output_path

def download_ca_tract_geometries(output_dir: Path = None) -> Path:
    """Downloads California Tract Geometries"""
    import urllib.request
    import zipfile

    if output_dir is None:
        from config import EXTERNAL_DIR
        output_dir = EXTERNAL_DIR / "california_tracts"

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "tl_2024_06_tract.zip"
    
    # 2024 California Tracts boundary ZIP URL
    url = "https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_06_tract.zip"
    
    print(f"Downloading California Census Tract geometries zip from {url}...")
    urllib.request.urlretrieve(url, zip_path)
    
    print("Extracting ZIP contents...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(output_dir)
        
    # Clean up the zip file to save space
    zip_path.unlink()
    
    print(f"Success! Extracted Census tract shapefiles to {output_dir}")
    return output_dir

CENPOP_TRACT_URL = "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR06.txt"


def download_population_centroids(output_path: Path = None) -> Path:
    """Downloads 2020 population-weighted tract centroids for California.

    Distances measured from a tract's geometric centroid can start in empty
    land for large rural tracts; the population-weighted centroid is where
    residents actually are. 2020 tract definitions are unchanged in the 2024
    TIGER tract file used here.
    """
    if output_path is None:
        from config import EXTERNAL_DIR
        output_path = EXTERNAL_DIR / "cenpop2020_tract_centroids_06.csv"

    print(f"Downloading population-weighted tract centroids from {CENPOP_TRACT_URL}...")
    resp = requests.get(CENPOP_TRACT_URL, timeout=120)
    resp.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig strips the byte-order mark the Census file starts with
    output_path.write_text(resp.content.decode("utf-8-sig"), encoding="utf-8")
    print(f"Success! Saved population-weighted centroids to {output_path}")
    return output_path


if __name__ == "__main__":
    fetch_acs_ca_demographics_2024()
    download_ca_tract_geometries()
    download_population_centroids()


    
    