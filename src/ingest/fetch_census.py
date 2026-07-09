import sys
from pathlib import Path
import requests
import pandas as pd

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, TODAY_STR, CENSUS_API_KEY

def fetch_acs_ca_demographics_2024(output_path: Path = None) -> Path:
    if not CENSUS_API_KEY:
        print("[ERROR]: CENSUS_API_KEY is not set in your .env file or environment.")
        print("Please sign up for a free Census API key at: https://api.census.gov/data/key_signup.html")
        print("Then add 'CENSUS_API_KEY=your_key_here' to your .env file and restart your kernel.")
        sys.exit(1)

    if output_path is None:
        output_path = RAW_DIR / f"census_data_{TODAY_STR}.csv"
        
    api_url = "https://api.census.gov/data/2024/acs/acs5"

    params = {
        "get": "NAME,B01003_001E,B19013_001E", # Name, Total Population, Median Household Income
        "for": "tract:*",
        "in": "state:06", # Filter to California
        "key": CENSUS_API_KEY
    }
    print(f"Fetching 2024 ACS California 5-year demographics...")
    response = requests.get(api_url, params=params)
    response.raise_for_status()


    data = response.json()
    df = pd.DataFrame(data[1:], columns=data[0])

    # Rename column names
    df = df.rename(columns={
        'B01003_001E': 'total_population',
        'B19013_001E': 'median_income'
    })

    # Construct GEOID
    df["GEOID"] = df["state"] + df["county"] + df["tract"]

    # Clean data types
    df["total_population"] = pd.to_numeric(df["total_population"], errors='coerce').fillna(0).astype(int)
    df["median_income"] = pd.to_numeric(df["median_income"], errors="coerce")

    df.to_csv(output_path, index=False)
    print(f"Success! Saved California 2024 ACS 5-year demographics to {output_path}")
    return output_path

def download_ca_tract_geometries(output_dir: Path = None) -> Path:
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

if __name__ == "__main__":
    fetch_acs_ca_demographics_2024()
    download_ca_tract_geometries()


    
    